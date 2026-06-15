"""
create_reading_source.py
========================
Phase 3 of the `reading_together` project type -- the pre-project stage.

3a  modernize_and_split() : raw archaic story -> modern German + slide-sized sentences
3b  build_reading_scenes(): sentences -> universal scene objects (one per sentence)
    build_reading_project(): orchestrates the above into a project manifest

Later phases add per-sentence scene visuals + grammar annotations (3c) and
character casting (3d) on top of these scenes.

All GPT calls degrade gracefully (naive fallback) so the pipeline never hard-fails.

CLI
---
  python create_reading_source.py split story.txt --level B1 --max-words 16 --per-part 6
  python create_reading_source.py build <project_name> --per-part 6
"""

import argparse
import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_LEVEL = "B1"
DEFAULT_MAX_WORDS = 16
DEFAULT_PER_PART = 6


# =============================================================================
# 3a -- MODERNIZE + SPLIT
# =============================================================================

_PROMPT_TEMPLATE = """
You are preparing a public-domain German short story for a language-learning
"reading together" video for {LEVEL} learners.

Do TWO things and return ONLY a JSON object.

1. MODERNIZE the text below into natural, contemporary German:
   - Fix archaic spelling and outdated grammar (e.g. "thun" -> "tun", "giebt" -> "gibt").
   - Replace dated vocabulary and phrasing with modern equivalents.
   - Lightly rephrase so it reads as fresh contemporary German, but PRESERVE the
     plot, the characters, the narrative order and the meaning. Do not summarize,
     do not add or remove events.
   - Target language difficulty: {LEVEL}.
   - Keep direct speech as direct speech.

2. SPLIT the modernized text into short, self-contained sentences, each suitable
   for ONE slide of a video:
   - Aim for at most about {MAX_WORDS} words per sentence.
   - Break long compound/complex sentences at natural clause boundaries, but every
     resulting sentence must be grammatical and make sense on its own.
   - Keep the sentences in the original narrative order.
   - Do not merge separate ideas into one sentence.

Return ONLY this JSON object:
{{"modernized_text": "the full modernized story as one string",
  "sentences": ["sentence 1", "sentence 2", "..."]}}

STORY:
\"\"\"
{TEXT}
\"\"\"
""".strip()


def _build_prompt(raw_text, level, max_words):
    return (_PROMPT_TEMPLATE
            .replace("{LEVEL}", str(level))
            .replace("{MAX_WORDS}", str(max_words))
            .replace("{TEXT}", raw_text.strip()))


_SENT_SPLIT_RE = re.compile(r'(?<=[.!?…])\s+')


def _naive_split(text, max_words=DEFAULT_MAX_WORDS):
    """Fallback splitter: sentence punctuation, then break over-long sentences."""
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if not text:
        return []
    out = []
    for sent in _SENT_SPLIT_RE.split(text):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent.split()) <= max_words:
            out.append(sent)
            continue
        chunk = []
        for piece in re.split(r'(?<=[,;:])\s+', sent):
            chunk.append(piece)
            if len(' '.join(chunk).split()) >= max_words:
                out.append(' '.join(chunk).strip())
                chunk = []
        if chunk:
            out.append(' '.join(chunk).strip())
    return [s for s in out if s]


def chunk_into_parts(sentences, per_part=DEFAULT_PER_PART):
    """Group sentences into parts of `per_part` (last part takes the remainder)."""
    per_part = max(1, int(per_part))
    return [sentences[i:i + per_part] for i in range(0, len(sentences), per_part)]


def modernize_and_split(raw_text, level=DEFAULT_LEVEL, max_words=DEFAULT_MAX_WORDS,
                        model=DEFAULT_MODEL):
    """Return {"raw_text","modernized_text","sentences","level","max_words"}. Never raises."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return {"raw_text": "", "modernized_text": "", "sentences": [],
                "level": level, "max_words": max_words}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _build_prompt(raw_text, level, max_words)}],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        data = json.loads(resp.choices[0].message.content)
        modern = str(data.get("modernized_text", "")).strip()
        sentences = [str(s).strip() for s in data.get("sentences", []) if str(s).strip()]
        if not sentences:
            sentences = _naive_split(modern or raw_text, max_words)
        if not modern:
            modern = " ".join(sentences)
        return {"raw_text": raw_text, "modernized_text": modern, "sentences": sentences,
                "level": level, "max_words": max_words}
    except Exception as e:
        logger.warning("modernize_and_split failed (%s) -- naive fallback on original text", e)
        sentences = _naive_split(raw_text, max_words)
        return {"raw_text": raw_text, "modernized_text": raw_text, "sentences": sentences,
                "level": level, "max_words": max_words}


# =============================================================================
# 3b -- READING SCENE BUILDER
# =============================================================================

def build_reading_scenes(sentences, narrator_voice="", inter_pause_ms=300,
                         per_part=DEFAULT_PER_PART):
    """
    Convert a list of sentences into universal scene objects (one per sentence),
    matching the schema consumed by create_audio / create_video.

    Each reading scene:
      - audio.type == "tts"  (single narrator voice)
      - subtitle_text == the sentence  (grammar-annotated at render time)
      - _reading / _part_index / _sentence_index tags for packaging (Phase 5)
      - image is None for now; Phase 3c fills scene_visual + an image prompt.

    A silent pause scene is inserted after each sentence.
    """
    scenes = []
    idx = 1

    def _sid():
        nonlocal idx
        s = f"scene_{idx:03d}"
        idx += 1
        return s

    for i, sent in enumerate(sentences):
        sent = (sent or "").strip()
        if not sent:
            continue
        scenes.append({
            "id": _sid(),
            "description": f"reading_{i:03d}",
            "characters": [],
            "subtitle_text": sent,
            "scene_visual": "",          # filled by Phase 3c
            "_reading": True,
            "_part_index": i // max(1, per_part),
            "_sentence_index": i,
            "image": None,               # filled by Phase 3c (scene illustration)
            "audio": {"type": "tts", "file_path": None, "tts_text": sent,
                      "voice_id": narrator_voice, "duration_ms": None},
            "duration_ms": None,
        })
        scenes.append({
            "id": _sid(), "description": "pause", "characters": [],
            "image": None, "audio": None, "subtitle_text": None,
            "duration_ms": inter_pause_ms,
        })
    return scenes


def build_reading_project(project_name, per_part=None, max_words=None, model=DEFAULT_MODEL):
    """
    Pre-project step for a `reading_together` project: read the raw story from the
    manifest, modernize + split it, build reading scenes, and write everything back.

    The raw story is taken from generation_config.reading.raw_text if present,
    otherwise from generation_config.provided_context.
    """
    from utils_config import load_config, load_new_characters, load_project_types

    cfg = load_config()
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found -- run create_project first")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    gen = manifest["generation_config"]
    ptypes = load_project_types(cfg["assets_dir"])
    ptype_key = manifest["project_metadata"]["project_type_key"]
    ptype = ptypes.get(ptype_key, {})

    raw = (gen.get("reading", {}) or {}).get("raw_text") or gen.get("provided_context", "")
    level = gen.get("level", DEFAULT_LEVEL)
    per_part = int(per_part or ptype.get("default_sentences_per_part", DEFAULT_PER_PART))
    max_words = int(max_words or ptype.get("default_max_words", DEFAULT_MAX_WORDS))

    result = modernize_and_split(raw, level=level, max_words=max_words, model=model)

    style_tokens = cfg.get("image_style_tokens", "")
    framing_tokens = cfg.get("image_framing_tokens", "")
    analysis = analyze_story(result["sentences"], level=level,
                             style_tokens=style_tokens, model=model)

    chars = load_new_characters(cfg["assets_dir"])
    narrator_voice = chars.get("Narrator", {}).get("voice_id", "")
    inter_pause = manifest.get("pipeline_config", {}).get("inter_pause_ms", 300)

    scenes = build_reading_scenes(result["sentences"], narrator_voice, inter_pause, per_part)
    enrich_reading_scenes(scenes, analysis, style_tokens, framing_tokens)

    gen["reading"] = {**result, "sentences_per_part": per_part,
                      "characters": analysis.get("characters", [])}
    manifest["scenes"] = scenes
    manifest["video_info"]["video_format"] = ptype.get("format", "vertical")

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Human-readable dump
    parts = chunk_into_parts(result["sentences"], per_part)
    lines = [f"# reading_together: {project_name}", f"level: {level}",
             f"{len(result['sentences'])} sentences, {len(parts)} parts of {per_part}", ""]
    for pi, part in enumerate(parts, 1):
        lines.append(f"-- Part {pi} --")
        lines += [f"  {si}. {s}" for si, s in enumerate(part, 1)]
        lines.append("")
    (project_path / "reading_script.txt").write_text("\n".join(lines), encoding="utf-8")

    logger.info("reading_together built: %d sentences, %d parts, %d scenes",
                len(result["sentences"]), len(parts), len(scenes))
    return manifest



# =============================================================================
# 3c + 3d -- STORY ANALYSIS (character casting + per-sentence scene visuals)
# =============================================================================

_ANALYZE_TEMPLATE = """
You are the art director + casting director for a German "reading together" video
made from the story sentences below (level {LEVEL}). Return ONLY a JSON object.

1. CAST the characters of the story:
   - Include EVERY character that appears or acts: humans, animals, and creatures.
     Do NOT skip humans. A character counts even if it appears in only one or two
     sentences, and even if the story never gives it a proper name.
   - "name": a short, stable German name for the character. For unnamed characters
     use a capitalized noun from the story (e.g. "Mann", "Mueller", "Frau", "Koenig",
     "Bauer", "Kind"). Reuse the same name everywhere that character appears.
   - "kind": one of human | animal | creature | object.
   - "description": a vivid English visual description usable by an image model
     (age/build/appearance, clothing, colours, personality cues). For ANIMALS /
     non-human characters, design a consistent ANTHROPOMORPHIC look (e.g. "a clever
     red fox with a bushy tail, walks upright, wears a green vest") so they can be
     drawn identically in every scene.

2. For EACH numbered sentence, plan one illustration:
   - "index": the sentence number.
   - "scene_visual": a DETAILED English description (3-5 sentences) of the
     illustration for that sentence. It MUST cover all three of:
       (a) ACTION & INTERACTION -- what each character is doing and, when more than
           one is present, how they INTERACT with each other (who faces/looks at
           whom, gestures, touch, distance, who reacts to whom, body language,
           facial expressions, emotional tone of the exchange);
       (b) LOCATION / ENVIRONMENT -- describe the setting concretely: indoor or
           outdoor, key objects/furniture/landscape, time of day, light, weather,
           season, colours and mood of the surroundings;
       (c) COMPOSITION -- where the characters are placed in the scene and what they
           are near or holding.
     Follow the CONTENT of the sentence (do not invent events), be specific,
     concrete and drawable, and keep characters visually consistent with their
     cast descriptions. Avoid vague phrasing like "a character stands and talks".
   - "characters": the subset of cast names (exact) that appear in this scene.
     Use [] for pure scenery / narration with no character on screen.

Return ONLY this JSON object:
{{"characters": [{{"name": "...", "kind": "animal", "description": "..."}}],
  "sentences": [{{"index": 0, "scene_visual": "...", "characters": ["..."]}}]}}

SENTENCES:
{NUMBERED}
""".strip()

_VALID_KINDS = {"human", "animal", "creature", "object"}


def _clean_cast(raw):
    out = []
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        desc = str(c.get("description", "")).strip()
        if not name or not desc:
            continue
        kind = str(c.get("kind", "")).lower().strip()
        if kind not in _VALID_KINDS:
            kind = "human"
        out.append({"name": name, "kind": kind, "description": desc})
    return out


def _clean_plans(raw, n):
    by_index = {}
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        try:
            i = int(p.get("index"))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n):
            continue
        chars = [str(x).strip() for x in (p.get("characters") or []) if str(x).strip()]
        by_index[i] = {"index": i,
                       "scene_visual": str(p.get("scene_visual", "")).strip(),
                       "characters": chars}
    # ensure every sentence has a plan (fill gaps)
    return [by_index.get(i, {"index": i, "scene_visual": "", "characters": []})
            for i in range(n)]


def analyze_story(sentences, level=DEFAULT_LEVEL, style_tokens="", model=DEFAULT_MODEL):
    """Cast the story + plan per-sentence illustrations. Never raises."""
    sentences = [s for s in (sentences or []) if s and s.strip()]
    if not sentences:
        return {"characters": [], "sentences": []}
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    prompt = _ANALYZE_TEMPLATE.replace("{LEVEL}", str(level)).replace("{NUMBERED}", numbered)
    try:
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}, temperature=0.5)
        data = json.loads(resp.choices[0].message.content)
        return {"characters": _clean_cast(data.get("characters", [])),
                "sentences": _clean_plans(data.get("sentences", []), len(sentences))}
    except Exception as e:
        logger.warning("analyze_story failed (%s) -- empty illustration plans", e)
        return {"characters": [], "sentences": _clean_plans([], len(sentences))}


def _reading_image_prompt(scene_visual, char_descs, style_tokens="", framing_tokens=""):
    """Build a text-to-image prompt for one reading scene."""
    parts = []
    if style_tokens:
        parts.append(style_tokens)
    if framing_tokens:
        parts.append(f"FRAMING: {framing_tokens}")
    parts.append(f"Scene: {scene_visual}")
    if char_descs:
        parts.append("Characters in the scene (keep them visually consistent): "
                     + "; ".join(char_descs))
    parts.append("No text, no subtitles, no speech bubbles, no watermarks.")
    return "\n".join(parts)


def enrich_reading_scenes(scenes, analysis, style_tokens="", framing_tokens=""):
    """
    Attach scene_visual + an image prompt to each reading scene using the story
    analysis.  Characters present are stored in scene["_cast"] (NOT scene["characters"],
    to avoid triggering the dialog speaker-icon).  reference_type is "none" (text-only)
    until Phase 4 creates single-image character assets to composite from.
    """
    cast = {c["name"]: c for c in analysis.get("characters", [])}
    plans = {p["index"]: p for p in analysis.get("sentences", [])}
    for scene in scenes:
        if not scene.get("_reading"):
            continue
        plan = plans.get(scene.get("_sentence_index"))
        if not plan:
            continue
        sv = plan.get("scene_visual", "").strip()
        names = [n for n in plan.get("characters", []) if n in cast]
        scene["scene_visual"] = sv
        scene["_cast"] = names
        if sv:
            descs = [f'{cast[n]["name"]}: {cast[n]["description"]}' for n in names]
            scene["image"] = {
                "file_path": None,
                "prompt_to_create": _reading_image_prompt(sv, descs, style_tokens, framing_tokens),
                "reference_type": "none",   # Phase 4: "single_ref"/"both" once cast assets exist
                "_cast": names,
            }
    return scenes


# =============================================================================
# 4 -- MATERIALIZE CAST (single-image character assets)
# =============================================================================

def _slug(name):
    import re, unicodedata
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "char"


def materialize_reading_cast(project_name, regenerate=False, reanalyze=True,
                             cast_mapping=None, model=DEFAULT_MODEL):
    """
    Turn the story cast (generation_config.reading.characters) into reusable
    single-image character assets and point the reading scenes at them
    (reference_type "reading_cast").

    Non-destructive and idempotent:
      * existing character assets and their reference images are preserved
        (regenerated only when regenerate=True);
      * re-running MERGES any newly detected characters (e.g. humans missed on the
        first pass) without dropping the ones you already created;
      * scene cast references survive repeated runs (key mapping is idempotent).

    reanalyze=True re-detects characters from the already-split sentences and
    merges them in, WITHOUT re-modernizing/re-splitting the text or wiping any
    generated images, scene visuals or prompts.

    cast_mapping lets you cast one of your OWN existing characters in a story role
    instead of auto-generating a new one. It is a dict {story_role_name:
    existing_character_key}; an empty/falsy value reverts that role to
    auto-generation. The mapping is merged into (and persisted in)
    generation_config.reading.cast_mapping, so it sticks across re-runs. A mapped
    role uses the existing character's own reference art — no new asset is created
    and no art is generated for it.
    """
    from utils_config import load_config
    import manage_characters as mc

    cfg = load_config()
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    gen = manifest["generation_config"]
    reading = gen.get("reading", {}) or {}
    assets_dir = cfg["assets_dir"]

    # --- optional non-destructive re-analysis to pick up missing characters ---
    if reanalyze and reading.get("sentences"):
        style_tokens   = cfg.get("image_style_tokens", "")
        framing_tokens = cfg.get("image_framing_tokens", "")
        level = reading.get("level", gen.get("level", DEFAULT_LEVEL))
        analysis = analyze_story(reading["sentences"], level=level,
                                 style_tokens=style_tokens, model=model)

        existing = reading.get("characters", []) or []
        by_name = {c["name"]: c for c in existing if c.get("name")}
        added = 0
        for c in analysis.get("characters", []):
            if c.get("name") and c["name"] not in by_name:
                existing.append(c)
                by_name[c["name"]] = c
                added += 1
        reading["characters"] = existing
        logger.info("re-analysis merged %d new character(s); cast now %d", added, len(existing))

        plans = {p["index"]: p for p in analysis.get("sentences", [])}
        for scene in manifest.get("scenes", []):
            if not scene.get("_reading"):
                continue
            plan = plans.get(scene.get("_sentence_index"))
            if not plan:
                continue
            names = [n for n in plan.get("characters", []) if n in by_name]
            scene["_cast"] = names  # story names; remapped to asset keys below
            if not scene.get("scene_visual") and plan.get("scene_visual"):
                scene["scene_visual"] = plan["scene_visual"]
            # only create an image entry for scenes that never got one (don't clobber)
            if scene.get("image") is None and scene.get("scene_visual"):
                descs = [f'{by_name[n]["name"]}: {by_name[n]["description"]}' for n in names]
                scene["image"] = {
                    "file_path": None,
                    "prompt_to_create": _reading_image_prompt(scene["scene_visual"], descs,
                                                              style_tokens, framing_tokens),
                    "reference_type": "reading_cast",
                }

    cast = reading.get("characters", []) or []

    # --- merge + persist the role -> existing-character mapping ---
    # A truthy value casts one of the user's existing characters in that role; an
    # empty value reverts the role to auto-generation. Previously chosen mappings
    # are kept when this run doesn't mention them.
    role_mapping = dict(reading.get("cast_mapping", {}) or {})
    for nm, key in (cast_mapping or {}).items():
        nm = str(nm).strip()
        if not nm:
            continue
        key = str(key).strip() if key else ""
        if key:
            role_mapping[nm] = key
        else:
            role_mapping.pop(nm, None)
    reading["cast_mapping"] = role_mapping

    all_chars = mc.load_characters(assets_dir)   # to validate mapped keys exist

    # --- create / reuse single-image assets (existing images are never overwritten) ---
    name_to_key = {}
    for c in cast:
        nm = c.get("name")
        if not nm:
            continue
        # If this role is mapped to one of the user's existing characters, use that
        # character directly — no new asset, no art generation.
        mapped = role_mapping.get(nm)
        if mapped and mapped in all_chars:
            name_to_key[nm] = mapped
            logger.info("reading cast: role '%s' -> existing character '%s'", nm, mapped)
            continue
        if mapped and mapped not in all_chars:
            logger.warning("mapped character '%s' for role '%s' not found -- auto-generating",
                           mapped, nm)
        key = "rt_" + _slug(nm)
        mc.add_single_ref_character(assets_dir, key, c.get("description", ""),
                                    kind=c.get("kind", "animal"))
        chars = mc.load_characters(assets_dir)
        if regenerate or not chars.get(key, {}).get("ref_image_file_path"):
            try:
                mc.generate_single_ref_art(assets_dir, key)
            except Exception as e:
                logger.warning("single-ref art generation failed for %s: %s", key, e)
        name_to_key[nm] = key

    # Idempotent resolver: accept either a story name or an already-mapped asset key.
    resolve = dict(name_to_key)
    for k in name_to_key.values():
        resolve[k] = k

    for scene in manifest.get("scenes", []):
        if not scene.get("_reading"):
            continue
        keys = []
        for x in (scene.get("_cast") or []):
            k = resolve.get(x)
            if k and k not in keys:
                keys.append(k)
        scene["_cast"] = keys
        img = scene.get("image")
        if img:
            img["reference_type"] = "reading_cast"
            img["_cast"] = keys

    reading["cast_assets"] = name_to_key
    gen["reading"] = reading
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info("Materialized %d reading cast assets: %s", len(name_to_key), name_to_key)
    return manifest


# =============================================================================
# CLI
# =============================================================================

def _cmd_split(a):
    raw = open(a.textfile, encoding="utf-8").read()
    result = modernize_and_split(raw, level=a.level, max_words=a.max_words)
    parts = chunk_into_parts(result["sentences"], a.per_part)
    print("\n=== MODERNIZED TEXT ===\n")
    print(result["modernized_text"])
    print(f"\n=== {len(result['sentences'])} SENTENCES ({len(parts)} parts of {a.per_part}) ===\n")
    for pi, part in enumerate(parts, 1):
        print(f"-- Part {pi} --")
        for si, s in enumerate(part, 1):
            print(f"  {si}. {s}")
    if a.json:
        result["parts"] = parts
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nSaved JSON -> {a.json}")


def _cmd_build(a):
    build_reading_project(a.project_name, per_part=a.per_part, max_words=a.max_words)
    print(f"Built reading_together manifest for '{a.project_name}'.")


def _cmd_cast(a):
    mapping = {}
    for item in (a.map or []):
        if "=" in item:
            role, key = item.split("=", 1)
            mapping[role.strip()] = key.strip()
    materialize_reading_cast(a.project_name, regenerate=a.regenerate,
                             reanalyze=not a.no_reanalyze,
                             cast_mapping=mapping or None)
    print(f"Materialized cast for '{a.project_name}'.")


def main():
    p = argparse.ArgumentParser(description="reading_together pre-project (phase 3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("split", help="Modernize + split a .txt story (preview)")
    s.add_argument("textfile")
    s.add_argument("--level", default=DEFAULT_LEVEL)
    s.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS, dest="max_words")
    s.add_argument("--per-part", type=int, default=DEFAULT_PER_PART, dest="per_part")
    s.add_argument("--json", default=None)
    s.set_defaults(func=_cmd_split)

    b = sub.add_parser("build", help="Build the reading scenes into a project manifest")
    b.add_argument("project_name")
    b.add_argument("--per-part", type=int, default=None, dest="per_part")
    b.add_argument("--max-words", type=int, default=None, dest="max_words")
    b.set_defaults(func=_cmd_build)

    c = sub.add_parser("cast", help="Create single-image cast assets + wire them into scenes")
    c.add_argument("project_name")
    c.add_argument("--regenerate", action="store_true",
                   help="Re-create character reference images even if they already exist")
    c.add_argument("--no-reanalyze", action="store_true",
                   help="Do not re-detect characters; only materialize the existing cast list")
    c.add_argument("--map", action="append", metavar="ROLE=CHAR_KEY",
                   help="Cast an existing character in a story role (repeatable), "
                        "e.g. --map Fuchs=Zahra. Use ROLE= (empty) to revert to auto.")
    c.set_defaults(func=_cmd_cast)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
