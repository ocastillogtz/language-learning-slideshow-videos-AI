"""
podcast.py
==========
The "podcast" video type (Brezel Podcast): two hosts talk about a topic in a podcast
studio. The full episode is a horizontal 16:9 video; its best moments are re-cut as
vertical 9:16 Shorts that send viewers to the full episode.

Pieces
------
Studio art
    Every "studio" line shows the SAME image: the two hosts at the desk with headphones,
    pop-filter microphones, acoustic foam and the neon "Brezel Podcast" sign. It is
    generated ONCE per host pair + orientation and cached in assets/podcast_studio/, so
    every later episode with the same hosts reuses it for free. The cache file name
    carries a hash of the prompt — editing the studio prompt makes a new image instead
    of silently reusing the old one. Both orientations are made together: horizontal
    for the episode, vertical for the Shorts.

Script
    Normal create_script flow. Each dialog item carries setting = "studio" | "example";
    build_scene_list points studio lines at the shared studio (reference_type
    "podcast_studio") and gives example lines their own situation image (consecutive
    lines with the same example_id share one image).

Shorts
    select_shorts() asks GPT for the best self-contained stretches of the episode
    (dialog index ranges, stored in manifest["podcast"]["shorts"]). build_shorts()
    renders only those scenes as vertical clips into videos/v/ and assembles
    final_<project>_short<N>_YT.mp4 (+ _Meta twin) with a corner label and a
    "full episode" end card.
"""

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

from utils_config import load_config, load_new_characters, load_project_types, apply_video_format

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STUDIO_REF_TYPE = "podcast_studio"
STUDIO_ASSET_DIR = "podcast_studio"
# Project-local copies of the cached studio art (the per-scene image paths point here).
STUDIO_PROJECT_FILES = {
    "horizontal": "images/podcast_studio.png",
    "vertical":   "images/podcast_studio_v.png",
}
SHORTS_SUBDIR = "v"   # vertical short clips: projects/<p>/videos/v/<scene>.mp4

_FRAMING = {
    "horizontal": ("Horizontal 16:9 widescreen composition. Medium-wide shot: both hosts fully visible "
                   "at the desk, the neon sign clearly readable on the wall behind them."),
    "vertical":   ("Vertical 9:16 portrait composition. The two hosts sit close together at the desk in "
                   "the lower two thirds of the frame, both fully visible; the neon sign is clearly "
                   "readable on the wall above them."),
}
_FRAMING_LINE_RE = re.compile(r"^FRAMING: .*$", re.M)


# =============================================================================
# STUDIO IMAGE
# =============================================================================

def is_podcast(project_type: dict) -> bool:
    return bool((project_type.get("scene_builder_rules") or {}).get("podcast_studio"))


def _studio_description(project_types: dict | None = None) -> str:
    if project_types is None:
        project_types = load_project_types(load_config()["assets_dir"])
    return (project_types.get("podcast") or {}).get("studio_description") or "a podcast studio"


def studio_prompt(char_a: str, char_b: str, chars_data: dict, orientation: str = "horizontal",
                  studio_desc: str | None = None, style_tokens: str | None = None) -> str:
    """Image prompt for the shared studio shot (host A left, host B right).

    Unlike the per-line prompts this one ALLOWS text — the neon sign must read
    "Brezel Podcast" — and forbids any other lettering."""
    if style_tokens is None:
        style_tokens = load_config()["image_style_tokens"]
    desc = studio_desc or _studio_description()
    fa = (chars_data.get(char_a, {}) or {}).get("fixed_description", "") or ""
    fb = (chars_data.get(char_b, {}) or {}).get("fixed_description", "") or ""
    return (
        f"{style_tokens}\n"
        f"FRAMING: {_FRAMING[orientation]}\n\n"
        f"Scene at: {desc}\n"
        f"{char_a} (sits on the LEFT): {fa}\n"
        f"{char_b} (sits on the RIGHT): {fb}\n\n"
        "Both hosts are recording their podcast together: headphones on, each speaking into their own "
        "microphone with a pop filter, relaxed and engaged, looking at each other or toward the camera. "
        "Match exact clothing, hair, and facial features from reference. "
        "The ONLY text anywhere in the image is the neon sign reading exactly \"Brezel Podcast\" — "
        "no other text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


def _for_orientation(prompt: str, orientation: str) -> str:
    """Swap the FRAMING line of a (possibly user-edited) studio prompt for `orientation`."""
    line = f"FRAMING: {_FRAMING[orientation]}"
    if _FRAMING_LINE_RE.search(prompt):
        return _FRAMING_LINE_RE.sub(lambda _m: line, prompt, count=1)
    return f"{line}\n\n{prompt}"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_") or "x"


def studio_cache_path(assets_dir: Path, char_a: str, char_b: str, orientation: str, prompt: str) -> Path:
    h = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]
    return assets_dir / STUDIO_ASSET_DIR / f"{_slug(char_a)}__{_slug(char_b)}__{orientation}_{h}.png"


def studio_scenes(manifest: dict) -> list[dict]:
    return [s for s in manifest.get("scenes", [])
            if (s.get("image") or {}).get("reference_type") == STUDIO_REF_TYPE]


def ensure_studio_images(project_name: str, manifest: dict, *, regenerate: bool = False,
                         prompt: str | None = None, model_override: str | None = None) -> dict:
    """Make sure both studio images exist (cached in assets/, copied into the project)
    and point every studio scene at them. Only calls fal.ai for an orientation whose
    cached image is missing, or when regenerate=True. Mutates `manifest` in place;
    the caller writes it. Returns {orientation: project-relative path}."""
    from create_images import _char_ref_path, _edit_with_refs, _resolve_model

    cfg        = load_config()
    assets_dir = cfg["assets_dir"]
    project    = cfg["projects_dir"] / project_name
    chars_data = load_new_characters(assets_dir)
    cast       = manifest["generation_config"].get("characters") or []
    if len(cast) < 2:
        raise ValueError("A podcast needs two hosts (generation_config.characters).")
    char_a, char_b = cast[0], cast[1]

    # The stored prompt (possibly hand-edited in the Items tab) wins over the template.
    base = prompt
    if not base:
        stored = [s["image"].get("prompt_to_create") for s in studio_scenes(manifest)]
        base = next((p for p in stored if p), None)
    if not base:
        base = studio_prompt(char_a, char_b, chars_data, "horizontal",
                             style_tokens=cfg["image_style_tokens"])

    refs  = [_char_ref_path(chars_data[c], assets_dir) for c in (char_a, char_b) if c in chars_data]
    model = _resolve_model(cfg, model_override)
    out   = {}
    for orientation, rel in STUDIO_PROJECT_FILES.items():
        o_prompt = _for_orientation(base, orientation)
        cached   = studio_cache_path(assets_dir, char_a, char_b, orientation, o_prompt)
        if regenerate or not cached.exists():
            size = dict(cfg)
            apply_video_format(size, orientation)
            logger.info("Generating %s podcast studio for %s + %s (fal.ai) …", orientation, char_a, char_b)
            data = _edit_with_refs(o_prompt, refs, model, cfg["fal_t2i_model"], size["fal_image_size"])
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
            logger.info("  Cached → %s", cached)
        else:
            logger.info("Reusing cached %s studio: %s", orientation, cached.name)
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, dest)
        out[orientation] = rel

    for s in studio_scenes(manifest):
        img = s["image"]
        img["prompt_to_create"]   = base
        img["file_path"]          = out["horizontal"]
        img["file_path_vertical"] = out["vertical"]
    return out


def invalidate_studio_clips(project_name: str, manifest: dict) -> None:
    """Delete rendered clips of every studio scene (episode + shorts) after the art changed."""
    project = load_config()["projects_dir"] / project_name
    for s in studio_scenes(manifest):
        for sub in ("", SHORTS_SUBDIR):
            clip = project / "videos" / sub / f"{s['id']}.mp4"
            if clip.exists():
                clip.unlink()


# =============================================================================
# SHORTS SELECTION (GPT)
# =============================================================================

def _dialog_lines(manifest: dict) -> list[dict]:
    """[{index, speaker, text, setting}] for every podcast dialog scene, in order.
    Reads the manifest scenes (not the raw GPT output) so review fixes are included."""
    from create_script import _strip_fancy_notation
    lines = []
    for s in manifest.get("scenes", []):
        if "_dialog_index" not in s:
            continue
        text = s.get("subtitle_text") or (s.get("audio") or {}).get("tts_text") or ""
        lines.append({
            "index":   s["_dialog_index"],
            "speaker": (s.get("characters") or ["?"])[0],
            "text":    _strip_fancy_notation(text),
            "setting": s.get("_podcast_setting", "studio"),
        })
    return lines


def _shorts_prompt(lines: list[dict], count: int, min_lines: int, max_lines: int, level: str) -> str:
    numbered = "\n".join(
        f"{l['index']}. [{l['setting']}] {l['speaker']}: {l['text']}" for l in lines)
    return f"""You are a social-media editor for the "Brezel Podcast", a German-learning podcast (level {level}).
Below is the full episode transcript. Each line is: <index>. [studio|example] <speaker>: <text>.

Pick the {count} BEST moments to publish as standalone vertical Shorts (YouTube Shorts / Reels) that make
viewers want to watch the full episode.

Each moment must:
- be a CONTIGUOUS range of lines, between {min_lines} and {max_lines} lines long;
- make sense on its own without the rest of the episode (no dangling "wie gesagt ..." at the start);
- start with a strong hook line (a surprising fact, a question, a funny or relatable moment);
- teach something concrete — ideally include at least one "example" line (those have their own illustration);
- NOT overlap with the other moments. Prefer moments from different parts of the episode.

For each moment also write:
- "title": a catchy Short title UNDER 90 characters, German or mixed German/English, ending with
  "({level}) 🥨 #shorts #deutschlernen".
- "description": 2-3 plain-text sentences (no markdown) saying what the viewer learns, then a new line
  "Ganze Folge: {{LINK}}" (write the literal placeholder {{LINK}}), then a new line with 3-5 hashtags.
- "why": one short sentence on why this moment works as a Short.

Return ONLY this JSON:
{{"shorts": [{{"start": <first line index>, "end": <last line index, inclusive>, "title": "...",
  "description": "...", "why": "..."}}]}}

TRANSCRIPT:
{numbered}
"""


def _clean_shorts(raw: list, valid: list[int], min_lines: int, max_lines: int) -> list[dict]:
    """Clamp GPT's ranges to real dialog indices and the allowed length; drop overlaps."""
    if not valid:
        return []
    lo, hi = min(valid), max(valid)
    taken: set[int] = set()
    out = []
    for r in raw or []:
        try:
            start, end = int(r.get("start")), int(r.get("end"))
        except (TypeError, ValueError, AttributeError):
            continue
        start, end = max(lo, min(start, end)), min(hi, max(start, end))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
        if end - start + 1 < min(min_lines, hi - lo + 1):
            continue
        span = set(range(start, end + 1))
        if span & taken:
            continue
        taken |= span
        out.append({
            "start": start, "end": end,
            "title": (r.get("title") or "").strip(),
            "description": (r.get("description") or "").strip(),
            "why": (r.get("why") or "").strip(),
        })
    out.sort(key=lambda x: x["start"])
    return out


def pick_shorts(manifest: dict, count: int | None = None) -> list[dict]:
    """GPT picks the best moments. Pure: returns the list, doesn't touch the manifest."""
    from create_script import client, _check_not_truncated
    cfg       = load_config()
    count     = int(count or cfg["podcast_shorts_count"])
    min_lines = cfg["podcast_short_min_lines"]
    max_lines = cfg["podcast_short_max_lines"]
    lines     = _dialog_lines(manifest)
    if not lines:
        raise ValueError("No podcast dialog scenes found — generate the script first.")
    level  = manifest["generation_config"].get("level", "")
    prompt = _shorts_prompt(lines, count, min_lines, max_lines, level)
    logger.info("Picking %d podcast shorts with GPT (%s) …", count, cfg["script_model"])
    resp = client.chat.completions.create(
        model=cfg["script_model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    _check_not_truncated(resp, "podcast shorts selection")
    data = json.loads(resp.choices[0].message.content)
    shorts = _clean_shorts(data.get("shorts"), [l["index"] for l in lines], min_lines, max_lines)
    logger.info("Picked %d shorts: %s", len(shorts), [(s["start"], s["end"]) for s in shorts])
    return shorts


def write_shorts_txt(project_name: str, manifest: dict) -> None:
    """Human-readable list of the Shorts (title, description with link, transcript)."""
    cfg     = load_config()
    project = cfg["projects_dir"] / project_name
    link    = cfg["podcast_full_episode_url"] or "{LINK}"
    by_idx  = {l["index"]: l for l in _dialog_lines(manifest)}
    out = [f"# Shorts for: {manifest.get('video_info', {}).get('title', '')}", ""]
    for n, sh in enumerate((manifest.get("podcast") or {}).get("shorts") or [], start=1):
        out += [f"## Short {n}  (lines {sh['start']}–{sh['end']})",
                f"Title: {sh.get('title', '')}",
                "Description:",
                (sh.get("description") or "").replace("{LINK}", link),
                ""]
        out += [f"  {by_idx[i]['speaker']}: {by_idx[i]['text']}" for i in range(sh["start"], sh["end"] + 1)
                if i in by_idx]
        out.append("")
    (project / "shorts.txt").write_text("\n".join(out), encoding="utf-8")


def select_shorts(project_name: str, count: int | None = None) -> list[dict]:
    """Re-pick the Shorts for an existing podcast project and save them."""
    cfg  = load_config()
    path = cfg["projects_dir"] / project_name / "project_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    shorts = pick_shorts(manifest, count)
    manifest.setdefault("podcast", {})["shorts"] = shorts
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_shorts_txt(project_name, manifest)
    return shorts


def clean_shorts_for(manifest: dict, shorts: list[dict]) -> list[dict]:
    """Validate hand-chosen Short ranges against a manifest's dialog (no length limit,
    overlaps dropped). Pure: doesn't touch the manifest."""
    valid = [l["index"] for l in _dialog_lines(manifest)]
    return _clean_shorts(shorts, valid, 1, 10 ** 6)


def save_shorts(project_name: str, shorts: list[dict]) -> list[dict]:
    """Store hand-edited Short ranges/titles (validated against the dialog)."""
    cfg  = load_config()
    path = cfg["projects_dir"] / project_name / "project_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    clean = clean_shorts_for(manifest, shorts)
    manifest.setdefault("podcast", {})["shorts"] = clean
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_shorts_txt(project_name, manifest)
    return clean


# =============================================================================
# SHORTS RENDER + ASSEMBLY
# =============================================================================

def short_scene_ids(scenes: list[dict], start: int, end: int) -> list[str]:
    """Scene ids from the dialog line `start` through `end` (inclusive), keeping the
    pauses between them but not the pause after the last line."""
    ids, inside = [], False
    for s in scenes:
        di = s.get("_dialog_index")
        if di is not None:
            if di > end:
                break
            inside = di >= start
        if inside:
            ids.append(s["id"])
    while ids and "_dialog_index" not in next(s for s in scenes if s["id"] == ids[-1]):
        ids.pop()
    return ids


def build_shorts(project_name: str, overwrite: bool = False, annotated_subtitles: bool = False,
                 bg_audio_name: str | None = None, bg_audio_gain_db: float | None = None,
                 speed_factor: float | None = None, branding_file: str | None = None,
                 branding_mode: str = "none", only: list[int] | None = None,
                 bg_tracks: dict | None = None) -> list[Path]:
    """Render the chosen moments as vertical clips (videos/v/) and assemble each into
    final_<project>_short<N>_YT.mp4 (+ _Meta/_TikTok twins when bg_tracks names a
    track for that platform). `only` = 1-based short numbers to build (None = all)."""
    import assemble_reading as ar
    from create_video import create_videos

    cfg      = load_config()
    project  = cfg["projects_dir"] / project_name
    man_path = project / "project_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    shorts   = (manifest.get("podcast") or {}).get("shorts") or []
    if not shorts:
        raise ValueError("No shorts chosen yet — pick them in the Shorts step first.")
    numbers = [n for n in range(1, len(shorts) + 1) if not only or n in only]

    # Vertical studio art (cached — only generated if this host pair has none yet).
    if studio_scenes(manifest):
        ensure_studio_images(project_name, manifest)
        man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    groups = {n: short_scene_ids(manifest["scenes"], shorts[n - 1]["start"], shorts[n - 1]["end"])
              for n in numbers}
    all_ids = [sid for n in numbers for sid in groups[n]]
    create_videos(project_name, overwrite=overwrite, annotated_subtitles=annotated_subtitles,
                  format_override="vertical", out_subdir=SHORTS_SUBDIR, scene_ids=all_ids)

    # _finalize's end card + corner label read the reading_* keys; point them at the podcast ones.
    fcfg = apply_video_format(dict(cfg), "vertical")
    fcfg["continuation_text"]    = cfg["podcast_short_cta_text"]
    fcfg["continuation_seconds"] = cfg["podcast_short_cta_seconds"]
    if bg_audio_name is None:
        bg_audio_name = cfg["podcast_short_bg_audio_name"]
    if bg_audio_gain_db is None:
        bg_audio_gain_db = cfg["podcast_short_bg_audio_gain_db"]
    if speed_factor is None:
        speed_factor = cfg.get("speed_factor", 1.0)

    v_dir, outputs = project / "videos" / SHORTS_SUBDIR, []
    for n in numbers:
        out = project / f"final_{project_name}_short{n}.mp4"
        res = ar._finalize(
            [v_dir / f"{sid}.mp4" for sid in groups[n]], out, fcfg, cfg["assets_dir"], project,
            bg_audio_name or "", float(speed_factor), branding_file, branding_mode, overwrite,
            tag=f"short{n}", corner_label=cfg["podcast_short_label"] or None,
            add_continuation=True, bg_audio_gain_db=bg_audio_gain_db, bg_tracks=bg_tracks,
        )
        if res:
            # "file" = the YouTube variant (or the first one built); "files" = all of them.
            shorts[n - 1]["file"]  = (res.get("yt") or next(iter(res.values()))).name
            shorts[n - 1]["files"] = {k: v.name for k, v in res.items()}
            outputs.extend(res.values())

    manifest.setdefault("podcast", {})["shorts"] = shorts
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_shorts_txt(project_name, manifest)
    logger.info("build_shorts produced %d file(s).", len(outputs))
    return outputs


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Brezel Podcast helpers")
    sub = p.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("pick", help="(Re-)pick the best moments with GPT")
    s1.add_argument("project_name"); s1.add_argument("--count", type=int, default=None)
    s2 = sub.add_parser("build", help="Render + assemble the vertical Shorts")
    s2.add_argument("project_name"); s2.add_argument("--overwrite", action="store_true")
    s2.add_argument("--annotated", action="store_true")
    s2.add_argument("--only", type=int, nargs="*", default=None, help="1-based short numbers")
    s3 = sub.add_parser("studio", help="Create/refresh the cached studio images")
    s3.add_argument("project_name"); s3.add_argument("--regenerate", action="store_true")
    a = p.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    if a.cmd == "pick":
        for sh in select_shorts(a.project_name, a.count):
            print(f"{sh['start']}-{sh['end']}: {sh['title']}")
    elif a.cmd == "build":
        build_shorts(a.project_name, a.overwrite, a.annotated, only=a.only)
    else:
        cfg  = load_config()
        path = cfg["projects_dir"] / a.project_name / "project_manifest.json"
        m    = json.loads(path.read_text(encoding="utf-8"))
        print(ensure_studio_images(a.project_name, m, regenerate=a.regenerate))
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
