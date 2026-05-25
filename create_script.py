"""
create_script.py
================
Calls GPT to generate the scene list for a project.

How it works
------------
1. Loads the project_type from assets/project_types/project_types.json using
   the manifest's project_metadata.project_type_key.
2. Injects character and location data into the project_type's
   description_for_prompt template (uses {PLACEHOLDER} markers).
3. Calls GPT with the project_type's output_json_schema as response_format.
4. Runs build_scene_list() which converts GPT output into a flat list of
   universal scene objects driven by the project_type's scene_builder_rules.
5. Writes the resulting scenes[] array back to the manifest.

Adding a new video type requires only a new entry in project_types.json.
No changes to this file are needed unless the new type requires a scene
pattern that scene_builder_rules cannot express.

Prompt placeholders
-------------------
{LEVEL}                    — language level (e.g. B1)
{LEVEL_LOWER}              — language level lowercased (e.g. b1), used in hashtags
{LOCATION_KEY}             — location key (e.g. cafe)
{LOCATION_DESC}            — location description
{CHAR_A} / {CHAR_B}        — character names
{CHAR_A_DESC}              — fixed + variable description for char A
{CHAR_B_DESC}              — fixed + variable description for char B
{WORDS_LIST}               — comma-separated word list (word_learning only)
{PROVIDED_CONTEXT}         — user-supplied scene description
{PROVIDED_LEARNING_POINTS} — user-supplied learning objectives

Dialog item fields (GPT output)
--------------------------------
  text             — German dialog text
  speaker          — character name
  scene_visual     — English action description for the illustration
  scene_characters — "speaker_only" | "both"
"""

import json
import logging
import argparse
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from utils_config import (
    load_config,
    load_new_characters,
    load_project_types,
    get_new_locations_flat,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Style/framing tokens are loaded from config.ini [image_prompts] at runtime.
# These module-level vars are populated once by _load_style_tokens() on first use.
_STYLE_TOKENS:   str = ""
_FRAMING_TOKENS: str = ""


def _load_style_tokens() -> None:
    """Populate module-level style/framing vars from config (called once)."""
    global _STYLE_TOKENS, _FRAMING_TOKENS
    if _STYLE_TOKENS:
        return
    cfg = load_config()
    _STYLE_TOKENS   = cfg["image_style_tokens"]
    _FRAMING_TOKENS = cfg["image_framing_tokens"]


# =============================================================================
# PROMPT BUILDER
# =============================================================================

def _build_prompt(
    project_type: dict,
    manifest: dict,
    chars_data: dict,
    all_locs: dict,
) -> str:
    """
    Inject runtime values into the project_type's description_for_prompt template.
    Returns the complete prompt string ready for GPT.
    """
    gen        = manifest["generation_config"]
    char_names = gen["characters"]
    char_a, char_b = char_names[0], char_names[1]
    location_key   = gen.get("location_key") or ""
    level          = gen["level"]
    dialog_count   = gen.get("dialog_count") or None

    if location_key and location_key in all_locs:
        loc_data      = all_locs[location_key]
        location_desc = loc_data["description"]
    else:
        location_key  = ""
        location_desc = (
            "a suitable location that fits the scene — "
            "choose naturally based on what the characters are discussing"
        )

    char_a_data = chars_data[char_a]
    char_b_data = chars_data[char_b]

    def _full_desc(c: dict) -> str:
        fixed    = c.get("fixed_description", "") or ""
        variable = c.get("variable_description", "") or ""
        return f"{fixed}, {variable}".strip(", ")

    char_a_desc = _full_desc(char_a_data)
    char_b_desc = _full_desc(char_b_data)

    words_list = ", ".join(gen.get("words", []) or [])

    # Dialog count: use provided value, or fall back to project_type default (or "4-6")
    if dialog_count:
        dialog_count_str = str(dialog_count)
    else:
        dialog_count_str = project_type.get("default_dialog_count", "4-6")

    template = project_type["description_for_prompt"]
    prompt = template.format(
        LEVEL                    = level,
        LEVEL_LOWER              = level.lower(),
        LOCATION_KEY             = location_key or "(model's choice)",
        LOCATION_DESC            = location_desc,
        CHAR_A                   = char_a,
        CHAR_B                   = char_b,
        CHAR_A_DESC              = char_a_desc,
        CHAR_B_DESC              = char_b_desc,
        WORDS_LIST               = words_list,
        DIALOG_COUNT             = dialog_count_str,
        PROVIDED_CONTEXT         = gen.get("provided_context", ""),
        PROVIDED_LEARNING_POINTS = gen.get("provided_learning_points", ""),
    )
    return prompt


# =============================================================================
# REPETITION SELECTION (shadowing only — second GPT pass)
# =============================================================================

def _build_repetitions_prompt(dialog_texts: list[str], level: str) -> str:
    numbered = "\n".join(f"  {i}. {t}" for i, t in enumerate(dialog_texts))
    return f"""
You are a German language learning expert selecting sentences for a shadowing exercise.
Level: {level}

Select exactly 3 sentences from the dialog below that are most pedagogically valuable
for a {level} learner to shadow.

Criteria (in order of priority):
1. Contains the key grammar structure or vocabulary being taught
2. Natural spoken German that sounds good when repeated aloud
3. Varied sentence structures across the 3 chosen lines
4. Appropriate length — not too short (trivial) and not too long (hard to repeat)

Dialog lines:
{numbered}

Return ONLY valid JSON (no markdown, no backticks):
{{
  "repetitions": [
    {{"text": "exact German sentence copied from the dialog lines above"}},
    {{"text": "exact German sentence copied from the dialog lines above"}},
    {{"text": "exact German sentence copied from the dialog lines above"}}
  ]
}}

Rules:
- Copy the text EXACTLY as it appears above — do not paraphrase or modify
- Return exactly 3 items
- Do NOT include "Bitte wiederholen" — that is a fixed pre-recorded intro handled separately
- Output ONLY the JSON object
""".strip()


def _select_repetitions(
    dialog_texts: list[str],
    level: str,
    model: str,
) -> tuple[list[str], str]:
    prompt = _build_repetitions_prompt(dialog_texts, level)
    resp = client.chat.completions.create(
        model           = model,
        messages        = [{"role": "user", "content": prompt}],
        response_format = {"type": "json_object"},
        temperature     = 0.2,
    )
    data  = json.loads(resp.choices[0].message.content)
    texts = [r["text"] for r in data.get("repetitions", []) if r.get("text")]
    if len(texts) != 3:
        logger.warning(f"Expected 3 repetitions, got {len(texts)}")
    return texts, prompt


# =============================================================================
# IMAGE PROMPT BUILDERS
# =============================================================================

def _narrator_image_prompt(loc_desc: str, framing_tokens: str = None) -> str:
    _load_style_tokens()
    framing = framing_tokens or _FRAMING_TOKENS
    return (
        f"{_STYLE_TOKENS}\n"
        f"FRAMING: {framing}\n\n"
        f"Wide establishing shot. {loc_desc}. "
        "Characters smaller in frame, environment clearly visible. "
        "Storytelling mood. No text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


def _action_single_prompt(char_name: str, char_data: dict, loc_desc: str, scene_visual: str,
                          framing_tokens: str = None) -> str:
    """One character performing an action related to what they're saying."""
    _load_style_tokens()
    fixed = char_data.get("fixed_description", "") or ""
    framing = framing_tokens or _FRAMING_TOKENS
    return (
        f"{_STYLE_TOKENS}\n"
        f"FRAMING: {framing}\n\n"
        f"Scene at: {loc_desc}\n"
        f"Character: {char_name} — {fixed}\n\n"
        f"Action: {scene_visual}\n\n"
        "Show the character actively engaged with the action described. "
        "Match exact clothing, hair, and facial features from reference. "
        "Integrate them naturally into the environment. "
        "No text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


def _action_both_prompt(char_a: str, char_a_data: dict,
                        char_b: str, char_b_data: dict,
                        loc_desc: str, scene_visual: str,
                        framing_tokens: str = None) -> str:
    """Both characters in a shared action scene."""
    _load_style_tokens()
    def _fixed(c): return c.get("fixed_description", "") or ""
    framing = framing_tokens or _FRAMING_TOKENS
    return (
        f"{_STYLE_TOKENS}\n"
        f"FRAMING: {framing}\n\n"
        f"Scene at: {loc_desc}\n"
        f"{char_a}: {_fixed(char_a_data)}\n"
        f"{char_b}: {_fixed(char_b_data)}\n\n"
        f"Action: {scene_visual}\n\n"
        "Show both characters actively engaged in the described scene. "
        "Match exact clothing, hair, and facial features from reference. "
        "Integrate them naturally into the environment. "
        "No text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


# =============================================================================
# SCENE LIST BUILDER
# =============================================================================

def build_scene_list(
    gpt_output: dict,
    project_type: dict,
    manifest: dict,
    chars_data: dict,
    all_locs: dict,
    repetition_texts: list[str] | None = None,
) -> list[dict]:
    """
    Convert GPT output + project_type rules into a flat list of universal scene objects.
    """
    rules      = project_type["scene_builder_rules"]
    gen        = manifest["generation_config"]
    pipe       = manifest["pipeline_config"]
    loc_key    = gen.get("location_key") or ""
    char_names = gen["characters"]
    char_a, char_b = char_names[0], char_names[1]
    char_a_data    = chars_data[char_a]
    char_b_data    = chars_data[char_b]
    if loc_key and loc_key in all_locs:
        loc_data = all_locs[loc_key]
        loc_desc = loc_data["description"]
    else:
        loc_desc = "a setting chosen by the model to fit the scene"
    inter_ms       = pipe["inter_pause_ms"]
    rep_factor     = pipe["repetition_pause_factor"]
    # Framing tokens: use project type override for horizontal formats, else None (falls back to config)
    framing_tokens = project_type.get("framing_tokens") or None

    narrator_voice = chars_data.get("Narrator", {}).get("voice_id", "")
    char_a_voice   = char_a_data.get("voice_id", "")
    char_b_voice   = char_b_data.get("voice_id", "")

    def _voice(speaker: str) -> str:
        if speaker == char_a: return char_a_voice
        if speaker == char_b: return char_b_voice
        return narrator_voice

    scenes: list[dict] = []
    idx = 1

    def _sid() -> str:
        nonlocal idx; s = f"scene_{idx:03d}"; idx += 1; return s

    def _pause(ms: int) -> dict:
        return {"id": _sid(), "description": "pause", "characters": [],
                "image": None, "audio": None, "subtitle_text": None, "duration_ms": ms}

    def _sfx(asset_key: str, path: str, desc: str) -> dict:
        return {"id": _sid(), "description": desc, "characters": [], "image": None,
                "audio": {"type": "sfx", "asset_key": asset_key, "file_path": path, "duration_ms": None},
                "subtitle_text": None, "duration_ms": None}

    # --- Narration ---
    if rules.get("include_narration"):
        nar_raw  = gpt_output.get("narration", {})
        # GPT sometimes returns "narration": "text" (string) instead of {"text": "..."}
        if isinstance(nar_raw, str):
            nar_text = nar_raw
        elif isinstance(nar_raw, dict):
            nar_text = nar_raw.get("text", "")
        else:
            nar_text = ""
        if not nar_text:
            logger.warning("Narration text is empty — GPT may have omitted or misformatted it")
        scenes.append({
            "id": _sid(), "description": "narration", "characters": [char_a, char_b],
            "_is_narration": True,
            "image": {
                "file_path": None,
                "prompt_to_create": _narrator_image_prompt(loc_desc, framing_tokens),
                "reference_type": "both",
            },
            "audio": {"type": "tts", "file_path": None, "tts_text": nar_text,
                      "voice_id": narrator_voice, "duration_ms": None},
            "subtitle_text": nar_text, "duration_ms": None,
        })
        if rules.get("inter_pause_between_scenes"):
            scenes.append(_pause(inter_ms))

    # --- Dialog ---
    if rules.get("include_dialog"):
        for i, item in enumerate(gpt_output.get("dialog", [])):
            # GPT models sometimes use "character" instead of "speaker" — handle both
            speaker = item.get("speaker") or item.get("character") or char_a
            if not item.get("speaker") and not item.get("character"):
                logger.warning(f"Dialog item {i} missing 'speaker'/'character' field — defaulting to {char_a}")
            elif not item.get("speaker") and item.get("character"):
                logger.warning(f"Dialog item {i} used 'character' key instead of 'speaker' — accepting it")
            text           = item.get("text", "")
            scene_visual   = item.get("scene_visual", "")
            scene_chars    = item.get("scene_characters", "speaker_only")

            if scene_chars == "both":
                img_prompt     = _action_both_prompt(char_a, char_a_data, char_b, char_b_data, loc_desc, scene_visual, framing_tokens)
                reference_type = "both"
            else:
                spk_data       = char_a_data if speaker == char_a else char_b_data
                img_prompt     = _action_single_prompt(speaker, spk_data, loc_desc, scene_visual, framing_tokens)
                reference_type = "single_speaker"

            scenes.append({
                "id": _sid(),
                "description": f"dialog_{i:03d} [{speaker}]",
                "characters": [speaker],
                "scene_visual":     scene_visual,    # stored for UI display
                "scene_characters": scene_chars,     # stored for UI display
                "image": {
                    "file_path": None,
                    "prompt_to_create": img_prompt,
                    "reference_type": reference_type,
                    "speaker": speaker,
                },
                "audio": {"type": "tts", "file_path": None, "tts_text": text,
                          "voice_id": _voice(speaker), "duration_ms": None},
                "subtitle_text": text, "duration_ms": None,
            })
            if rules.get("inter_pause_between_scenes"):
                scenes.append(_pause(inter_ms))

    # --- Repetition section ---
    if rules.get("include_repetition_section") and repetition_texts:
        scenes.append(_sfx("bitte_wiederholen", "assets/sfx/bitte_wiederholen.mp3", "bitte_wiederholen intro"))
        if rules.get("inter_pause_between_scenes"):
            scenes.append(_pause(inter_ms))

        for rep_text in repetition_texts:
            if rules.get("bell_before_repetition"):
                scenes.append(_sfx("bell", "assets/sfx/bell.mp3", "bell"))
            scenes.append({
                "id": _sid(),
                "description": f"repetition: {rep_text[:40]}",
                "characters": [],
                "image": None,
                "audio": {"type": "tts", "file_path": None, "tts_text": rep_text,
                          "voice_id": narrator_voice, "duration_ms": None},
                "subtitle_text": rep_text, "duration_ms": None,
                "_is_repetition": True,
                "_rep_pause_factor": rep_factor,
            })

    return scenes


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def create_script(
    project_name: str,
    char_a: str,
    char_b: str,
    location_key: str | None = None,
    project_type_key: str | None = None,
    prompt_override: str | None = None,
    words: list[str] | None = None,
    dialog_count: int | None = None,
) -> dict:
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found — run create_project first")

    chars_data    = load_new_characters(cfg["assets_dir"])
    project_types = load_project_types(cfg["assets_dir"])
    all_locs      = get_new_locations_flat(cfg["assets_dir"])

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # project_type_key arg overrides the manifest value (lets the UI change it on the fly)
    if project_type_key:
        manifest["project_metadata"]["project_type_key"] = project_type_key
    project_type_key = manifest["project_metadata"]["project_type_key"]
    if project_type_key not in project_types:
        raise ValueError(f"Project type '{project_type_key}' not found in project_types.json")
    project_type = project_types[project_type_key]

    # Resolve base_type inheritance: long types reference a base type for description_for_prompt
    # and output_json_schema, then override with their own fields (format, dialog_count, etc.)
    base_type_key = project_type.get("base_type")
    if base_type_key and base_type_key in project_types:
        base = project_types[base_type_key]
        project_type = {**base, **project_type}  # long type fields win over base

    # Sync video_format in manifest from the (resolved) project type
    manifest["video_info"]["video_format"] = project_type.get("format", "vertical")

    for name in (char_a, char_b):
        if name not in chars_data:
            raise ValueError(f"Character '{name}' not found in characters.json")
    if location_key and location_key not in all_locs:
        raise ValueError(f"Location '{location_key}' not found. Available: {sorted(all_locs.keys())}")

    manifest["generation_config"]["location_key"] = location_key or ""
    manifest["generation_config"]["characters"]   = [char_a, char_b]
    if words:
        manifest["generation_config"]["words"] = words
    if dialog_count:
        manifest["generation_config"]["dialog_count"] = dialog_count

    prompt = prompt_override or _build_prompt(project_type, manifest, chars_data, all_locs)
    manifest["generation_config"]["prompt_script"] = prompt

    logger.info(f"Calling GPT ({cfg['script_model']}) for {project_name} …")
    resp = client.chat.completions.create(
        model           = cfg["script_model"],
        messages        = [{"role": "user", "content": prompt}],
        response_format = {"type": "json_object"},
    )
    raw_content = resp.choices[0].message.content

    # Save raw GPT response before parsing — useful for debugging parse failures
    manifest["generation_config"]["raw_gpt_script"] = raw_content

    gpt_output: dict = json.loads(raw_content)

    manifest["video_info"]["title"]    = gpt_output.get("title")
    manifest["video_info"]["tags"]     = gpt_output.get("tags")
    manifest["video_info"]["insights"] = gpt_output.get("insights")

    repetition_texts = None
    if project_type["scene_builder_rules"].get("include_repetition_section"):
        dialog_texts = [item.get("text", "") for item in gpt_output.get("dialog", []) if item.get("text")]
        rep_texts, rep_prompt = _select_repetitions(
            dialog_texts,
            manifest["generation_config"]["level"],
            cfg["script_model"],
        )
        repetition_texts = rep_texts
        manifest["generation_config"]["prompt_repetitions"] = rep_prompt

    manifest["scenes"] = build_scene_list(
        gpt_output       = gpt_output,
        project_type     = project_type,
        manifest         = manifest,
        chars_data       = chars_data,
        all_locs         = all_locs,
        repetition_texts = repetition_texts,
    )

    manifest["project_metadata"]["update_date"] = datetime.utcnow().isoformat()

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    _write_script_txt(project_path, manifest, gpt_output, repetition_texts)

    logger.info(
        f"Script done — type={project_type_key}, location={location_key or '(auto)'}, "
        f"{len(gpt_output.get('dialog', []))} dialog lines, "
        f"{len(repetition_texts or [])} repetitions, "
        f"{len(manifest['scenes'])} total scenes"
    )
    return manifest


def _write_script_txt(project_path, manifest, gpt_output, repetition_texts):
    vi    = manifest["video_info"]
    ptype = manifest["project_metadata"]["project_type_key"]
    lines = [f"# {vi.get('title','')}", f"type: {ptype}", ""]
    lines.append(f"[NARRATION] {gpt_output.get('narration',{}).get('text','')}")
    lines.append("")
    for d in gpt_output.get("dialog", []):
        visual = f"  [VISUAL({d.get('scene_characters','speaker_only')}): {d.get('scene_visual','')}]" if d.get("scene_visual") else ""
        lines.append(f"[{d.get('speaker','?')}] {d.get('text','')}{visual}")
    if repetition_texts:
        lines += ["", "[SHADOWING SECTION]"]
        lines += [f"  → {t}" for t in repetition_texts]
    (project_path / "script.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project_name")
    p.add_argument("--char-a",   required=True)
    p.add_argument("--char-b",   required=True)
    p.add_argument("--location-key", required=False, default=None, dest="location_key")
    p.add_argument("--project-type",  default="story",  dest="project_type_key")
    p.add_argument("--prompt-override", default=None,   dest="prompt_override")
    a = p.parse_args()
    create_script(
        a.project_name, a.char_a, a.char_b, a.location_key,
        project_type_key=a.project_type_key,
        prompt_override=a.prompt_override,
    )


if __name__ == "__main__":
    main()
