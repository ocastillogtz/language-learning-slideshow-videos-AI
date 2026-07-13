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
import re
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

# Max distinct characters drawn into ONE scene image. The video's overall cast can be
# larger (multi-character types); each individual scene is capped here so the image
# model keeps every character on-model. Overridable via config.ini [script]
# max_scene_characters. Keep >= 1 (1 = always solo, 2 = speaker + one other, …).
MAX_SCENE_CHARACTERS = 2


class ScriptTruncatedError(RuntimeError):
    """Raised when the model stopped because it hit the output-token ceiling
    (finish_reason == 'length'), so the returned JSON is incomplete."""


def _check_not_truncated(resp, what: str) -> None:
    """Detect a length-truncated completion. In JSON mode the model closes the
    JSON gracefully when it runs out of output budget, so json.loads() still
    succeeds and the short result looks valid — this is the only signal that a
    long request (e.g. a 200-line dialog) was silently cut off."""
    finish = resp.choices[0].finish_reason
    if finish == "length":
        raise ScriptTruncatedError(
            f"{what}: the model hit its output-token limit (finish_reason='length') "
            f"and the result is incomplete. Reduce the dialogue count, switch "
            f"[script] openai_model to a model with a larger output window, or "
            f"generate the dialog in smaller batches."
        )
    if finish not in (None, "stop"):
        logger.warning(f"{what}: unexpected finish_reason={finish!r}")


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
    max_scene_chars: int = MAX_SCENE_CHARACTERS,
    dialog_count_override=None,
) -> str:
    """
    Inject runtime values into the project_type's description_for_prompt template.
    Returns the complete prompt string ready for GPT.

    dialog_count_override lets the batched generator ask for just one chunk's worth
    of lines instead of the manifest's full requested count.
    """
    gen        = manifest["generation_config"]
    char_names = gen["characters"]
    char_a, char_b = char_names[0], char_names[1]
    location_key   = gen.get("location_key") or ""
    level          = gen["level"]
    dialog_count   = dialog_count_override if dialog_count_override is not None else (gen.get("dialog_count") or None)

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

    # Multi-character conversational types: introduce any extra cast members and the
    # multi-speaker rules by APPENDING to the (untouched) two-person template above.
    cast = gen.get("characters", []) or []
    if project_type.get("supports_multi_character") and len(cast) > 2:
        def _cast_desc(nm):
            cd = chars_data.get(nm, {})
            return f"{cd.get('fixed_description','') or ''}, {cd.get('variable_description','') or ''}".strip(", ")
        extra_lines = "\n".join(f"  {nm} — {_cast_desc(nm)}" for nm in cast[2:])
        roster = ", ".join(cast)
        prompt += (
            "\n\n=== ADDITIONAL CHARACTERS (multi-character conversation) ===\n"
            f"This conversation has MORE than two participants. The full cast is: {roster}.\n"
            f"In addition to {char_a} and {char_b} (described above), these characters also take "
            f"part and may speak and appear on screen:\n{extra_lines}\n\n"
            "Rules when there are multiple characters:\n"
            f"- ANY cast member ({roster}) may be the speaker of a line. Put that character's "
            "EXACT name in the \"speaker\" field.\n"
            "- Distribute the lines naturally among the participants; don't silently drop anyone.\n"
            "- For EVERY dialog line, ALSO include a \"present_characters\" array with the EXACT names "
            "of the characters visible in that line's illustration. Always include the speaker. To keep "
            f"each illustration clean, list AT MOST {max_scene_chars} characters per line (the speaker "
            f"plus up to {max(0, max_scene_chars - 1)} other). The conversation as a whole still "
            "involves the full cast — just don't crowd a single image. Use this instead of "
            "\"scene_characters\".\n"
        )
    return prompt


# =============================================================================
# BATCHED DIALOG GENERATION (long videos — avoids the output-token ceiling)
# =============================================================================

def _parse_int_count(dialog_count) -> int | None:
    """Return dialog_count as an int if it's an explicit number, else None
    (ranges like "10-14" or None mean 'use the type default' — those are short
    enough that batching isn't needed)."""
    try:
        return int(str(dialog_count).strip())
    except (TypeError, ValueError):
        return None


def _continuation_block(prior_dialog: list, this_batch: int, remaining: int, target: int) -> str:
    """Appended to the per-type template for every batch after the first. Recaps
    the recent lines (for continuity) and asks ONLY for the next chunk of dialog."""
    recap_all = []
    for i, item in enumerate(prior_dialog):
        sp = item.get("speaker") or item.get("character") or "?"
        recap_all.append(f"{i + 1}. {sp}: {item.get('text', '')}")
    # Only the tail is needed for continuity; keeps input tokens bounded on long runs.
    recap = "\n".join(recap_all[-12:])
    done  = len(prior_dialog)
    final = remaining <= this_batch
    close = ("This is the FINAL batch — bring the conversation to a natural close."
             if final else "Do NOT conclude the conversation yet; more lines will follow.")
    return f"""

=== CONTINUATION MODE ===
This dialog is being written in batches. {done} of {target} lines already exist.
Most recent lines so far (for continuity — do NOT repeat or re-number them):
{recap}

Now write the NEXT {this_batch} dialog lines ONLY, continuing the SAME conversation
naturally from where it left off. Do not restart, recap, or repeat earlier lines.
Keep the same characters, setting, register and style, and follow every dialog and
scene_visual rule given above. {close}

Return ONLY a JSON object of the form {{"dialog": [ ... ]}} holding exactly the
{this_batch} new line objects (same fields as specified above). The title, tags,
insights, narration and other top-level fields already exist — omit them entirely.
""".strip("\n")


def _generate_script_batched(
    project_type: dict,
    manifest: dict,
    chars_data: dict,
    all_locs: dict,
    *,
    max_scene_chars: int,
    model: str,
    target: int,
    batch_size: int,
) -> tuple[dict, str]:
    """Generate a long dialog in chunks of `batch_size` lines, merging the result
    into a single gpt_output. The first call also yields title/tags/insights/
    narration; later calls only add dialog lines. Returns (gpt_output, raw_text)."""
    logger.info(f"Batched script generation: {target} lines in chunks of {batch_size}")
    gpt_output: dict | None = None
    dialog: list = []
    raws: list[str] = []
    batch_no = 0

    while len(dialog) < target:
        batch_no += 1
        remaining  = target - len(dialog)
        this_batch = min(batch_size, remaining)
        first      = gpt_output is None

        prompt = _build_prompt(project_type, manifest, chars_data, all_locs,
                               max_scene_chars=max_scene_chars,
                               dialog_count_override=this_batch)
        if not first:
            prompt += "\n\n" + _continuation_block(dialog, this_batch, remaining, target)

        logger.info(f"  batch {batch_no}: requesting {this_batch} lines "
                    f"({len(dialog)}/{target} done)")
        resp = client.chat.completions.create(
            model           = model,
            messages        = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},
        )
        _check_not_truncated(resp, f"script batch {batch_no}")
        raws.append(resp.choices[0].message.content)
        out = json.loads(resp.choices[0].message.content)
        new_lines = out.get("dialog", []) or []

        if first:
            gpt_output = out
            dialog = list(new_lines)
        else:
            if not new_lines:
                logger.warning("Continuation batch returned no new dialog lines — "
                               "stopping early.")
                break
            dialog.extend(new_lines)

        # Safety valve: if a batch yields fewer than asked and we've matched/exceeded
        # the request, the loop's while-condition ends it; this guards a stuck model
        # that keeps returning nothing despite remaining > 0.
        if batch_no > 0 and len(dialog) == 0:
            break

    if gpt_output is None:  # pragma: no cover — target>0 guarantees one pass
        gpt_output = {"dialog": []}
    # The model may overshoot on the final batch; trim to exactly what was requested.
    gpt_output["dialog"] = dialog[:target]
    logger.info(f"Batched generation produced {len(gpt_output['dialog'])} dialog lines")
    raw_content = "\n\n/* ---- batch boundary ---- */\n\n".join(raws)
    return gpt_output, raw_content


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
    _check_not_truncated(resp, "repetition selection")
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


def _action_multi_prompt(present: list, chars_data: dict, loc_desc: str, scene_visual: str,
                         framing_tokens: str = None) -> str:
    """N present characters sharing an action scene (multi-character conversation)."""
    _load_style_tokens()
    framing = framing_tokens or _FRAMING_TOKENS
    roster  = "\n".join(
        f"{nm}: {chars_data.get(nm, {}).get('fixed_description', '') or ''}" for nm in present
    )
    return (
        f"{_STYLE_TOKENS}\n"
        f"FRAMING: {framing}\n\n"
        f"Scene at: {loc_desc}\n"
        f"{roster}\n\n"
        f"Action: {scene_visual}\n\n"
        "Show all of the listed characters actively engaged in the described scene. "
        "Match exact clothing, hair, and facial features from reference. "
        "Integrate them naturally into the environment. "
        "No text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


_ACTION_SEGMENT_RE = re.compile(r"(Action: ).*?(\n\n)", re.S)


def update_prompt_scene_visual(prompt: str, scene_visual: str) -> str:
    """Swap the visual/action portion of a stored image prompt for a new one,
    keeping the style/framing header and closing instructions intact.

    Dialog prompts embed the visual as an "Action: ...\\n\\n" paragraph — that
    segment is replaced. Narration prompts have no Action marker; there the whole
    body after the style/FRAMING header is replaced by the new visual (plus the
    standard no-text safety tokens). Unrecognized shapes are returned unchanged.
    """
    if not prompt or not scene_visual:
        return prompt
    if "Action: " in prompt:
        return _ACTION_SEGMENT_RE.sub(
            lambda m: m.group(1) + scene_visual + m.group(2), prompt, count=1)
    head, sep, _body = prompt.partition("\n\n")
    if not sep:
        return prompt
    return (f"{head}{sep}{scene_visual}. "
            "No text, no subtitles, no speech bubbles, no anime eyes, no watermarks.")


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
    max_scene_chars: int = MAX_SCENE_CHARACTERS,
) -> list[dict]:
    """
    Convert GPT output + project_type rules into a flat list of universal scene objects.
    """
    rules      = project_type["scene_builder_rules"]
    gen        = manifest["generation_config"]
    pipe       = manifest["pipeline_config"]
    loc_key    = gen.get("location_key") or ""
    char_names = gen["characters"]
    cast       = list(char_names)
    multi      = bool(project_type.get("supports_multi_character")) and len(cast) > 2
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
    # Voice per cast member (covers any number of speakers, not just A/B).
    voices = {nm: chars_data.get(nm, {}).get("voice_id", "") for nm in cast}

    def _voice(speaker: str) -> str:
        return voices.get(speaker) or narrator_voice

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
        nar_img = {
            "file_path": None,
            "prompt_to_create": _narrator_image_prompt(loc_desc, framing_tokens),
            "reference_type": "multi" if multi else "both",
        }
        if multi:
            nar_img["_cast"] = list(cast)[:max_scene_chars]
        scenes.append({
            "id": _sid(), "description": "narration", "characters": list(cast),
            "_is_narration": True,
            "image": nar_img,
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
            img_extra      = {}

            if multi:
                # Resolve who is visible in this line's illustration. Prefer the
                # model's "present_characters"; always ensure the speaker is included.
                present = item.get("present_characters")
                names   = []
                if isinstance(present, list):
                    for nm in present:
                        nm = nm.strip() if isinstance(nm, str) else ""
                        if nm in chars_data and nm not in names:
                            names.append(nm)
                if speaker in chars_data and speaker not in names:
                    names.insert(0, speaker)
                if not names:
                    names = [speaker] if speaker in chars_data else cast[:1]
                # Cap how many characters share a single illustration (speaker kept first).
                names = names[:max(1, max_scene_chars)]
                img_prompt     = _action_multi_prompt(names, chars_data, loc_desc, scene_visual, framing_tokens)
                reference_type = "multi"
                img_extra      = {"_cast": names}
            elif scene_chars == "both":
                img_prompt     = _action_both_prompt(char_a, char_a_data, char_b, char_b_data, loc_desc, scene_visual, framing_tokens)
                reference_type = "both"
            else:
                spk_data       = char_a_data if speaker == char_a else char_b_data
                img_prompt     = _action_single_prompt(speaker, spk_data, loc_desc, scene_visual, framing_tokens)
                reference_type = "single_speaker"

            image_obj = {
                "file_path": None,
                "prompt_to_create": img_prompt,
                "reference_type": reference_type,
                "speaker": speaker,
            }
            image_obj.update(img_extra)
            scenes.append({
                "id": _sid(),
                "description": f"dialog_{i:03d} [{speaker}]",
                "characters": [speaker],
                "scene_visual":     scene_visual,    # stored for UI display
                "scene_characters": scene_chars,     # stored for UI display
                "image": image_obj,
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
    characters: list[str] | None = None,
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

    # Full speaking cast: char_a + char_b first, then any extra characters (multi-
    # character conversational types). Order preserved, de-duplicated, blanks dropped.
    cast = []
    for nm in [char_a, char_b, *(characters or [])]:
        nm = (nm or "").strip()
        if nm and nm not in cast:
            cast.append(nm)
    for name in cast:
        if name not in chars_data:
            raise ValueError(f"Character '{name}' not found in characters.json")
    if location_key and location_key not in all_locs:
        raise ValueError(f"Location '{location_key}' not found. Available: {sorted(all_locs.keys())}")

    manifest["generation_config"]["location_key"] = location_key or ""
    manifest["generation_config"]["characters"]   = cast
    if words:
        manifest["generation_config"]["words"] = words
    if dialog_count:
        manifest["generation_config"]["dialog_count"] = dialog_count

    max_scene_chars = int(cfg.get("max_scene_characters") or MAX_SCENE_CHARACTERS)
    prompt = prompt_override or _build_prompt(project_type, manifest, chars_data, all_locs,
                                              max_scene_chars=max_scene_chars)
    manifest["generation_config"]["prompt_script"] = prompt

    # Long dialogs are split into chunks so no single request hits the model's
    # output-token ceiling (which silently truncates the result). Only kicks in for
    # an explicit numeric dialog_count above the batch size; a custom prompt_override
    # is sent as-is in one call.
    batch_size   = int(cfg.get("dialog_batch_size") or 40)
    target_count = _parse_int_count(manifest["generation_config"].get("dialog_count"))

    if not prompt_override and target_count and target_count > batch_size:
        logger.info(f"Calling GPT ({cfg['script_model']}) for {project_name} — "
                    f"batched ({target_count} lines) …")
        gpt_output, raw_content = _generate_script_batched(
            project_type, manifest, chars_data, all_locs,
            max_scene_chars=max_scene_chars, model=cfg["script_model"],
            target=target_count, batch_size=batch_size,
        )
        manifest["generation_config"]["raw_gpt_script"] = raw_content
    else:
        logger.info(f"Calling GPT ({cfg['script_model']}) for {project_name} …")
        resp = client.chat.completions.create(
            model           = cfg["script_model"],
            messages        = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},
        )
        _check_not_truncated(resp, "script generation")
        raw_content = resp.choices[0].message.content
        # Save raw GPT response before parsing — useful for debugging parse failures
        manifest["generation_config"]["raw_gpt_script"] = raw_content
        gpt_output = json.loads(raw_content)

    manifest["video_info"]["title"]    = gpt_output.get("title")
    manifest["video_info"]["tags"]     = gpt_output.get("tags")
    manifest["video_info"]["insights"] = gpt_output.get("insights")

    # Compact plain-text dialog for grammar review — no markup, easy to copy-paste
    manifest["generation_config"]["compact_dialog"] = _build_compact_dialog(gpt_output)

    # Auto-evaluate grammar and naturality of each dialog line. Operates on the
    # dialog list directly (keyed dialog_0..N-1, matching the dialog scenes) and is
    # batched so long dialogs don't truncate the evaluation.
    logger.info("Evaluating dialog grammar/naturality …")
    eval_texts = [_strip_fancy_notation(item.get("text", ""))
                  for item in gpt_output.get("dialog", []) if item.get("text")]
    manifest["generation_config"]["dialog_auto_evaluation"] = _evaluate_dialog(
        dialog_texts = eval_texts,
        level        = manifest["generation_config"]["level"],
        model        = cfg["script_model"],
        batch_size   = batch_size,
    )

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
        max_scene_chars  = max_scene_chars,
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


def _strip_fancy_notation(text: str) -> str:
    """
    Remove markdown-style emphasis and other decorative notation from dialog text.
    E.g. _Stillleben_ → Stillleben, **word** → word.
    Returns plain readable text suitable for grammar review.
    """
    import re
    # Remove **bold** and __bold__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    # Remove *italic* and _italic_
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    # Remove backtick code spans
    text = re.sub(r"`(.+?)`",       r"\1", text)
    return text.strip()


# =============================================================================
# DIALOG AUTO-EVALUATION (third GPT pass)
# =============================================================================

def _build_evaluation_prompt(dialog_texts: list[str], level: str, offset: int) -> str:
    """Evaluation prompt for one chunk of dialog. Lines are numbered with their
    GLOBAL index (offset + position) so the returned dialog_N keys line up with the
    full dialog regardless of which batch they came from."""
    numbered = "\n".join(f"dialog_{offset + i}: {t}" for i, t in enumerate(dialog_texts))
    return f"""You are a German language expert evaluating dialog written for a {level} learner.

Evaluate EACH line below for grammar correctness and natural spoken German.
Each line is already tagged with its key ("dialog_N"). Use that EXACT key in your answer.

Return ONLY valid JSON (no markdown, no backticks):
{{
  "dialog_{offset}": "excellent — natural phrasing, grammar is correct",
  "dialog_{offset + 1}": "bad — 'ich bin gegangen nach Hause' is wrong; correct form is 'ich bin nach Hause gegangen' (verb-final in subordinate position)"
}}

Rules:
- Be concise: one sentence per line max
- If a line is correct and natural, say "excellent" or "good" and briefly say why
- If a line has an issue, describe the problem and give the corrected version
- Return one entry for EVERY key shown below, and do not invent extra keys
- Output ONLY the JSON object

Dialog:
{numbered}
""".strip()


def _evaluate_dialog(dialog_texts: list[str], level: str, model: str,
                     batch_size: int = 40) -> dict:
    """Evaluate every dialog line for grammar/naturality, in chunks so a long
    dialog never hits the output-token ceiling. Keyed dialog_0..dialog_{N-1}."""
    result: dict = {}
    truncated = False
    for start in range(0, len(dialog_texts), batch_size):
        chunk  = dialog_texts[start:start + batch_size]
        prompt = _build_evaluation_prompt(chunk, level, start)
        resp = client.chat.completions.create(
            model           = model,
            messages        = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},
            temperature     = 0.2,
        )
        if resp.choices[0].finish_reason == "length":
            # A single chunk shouldn't truncate; if it does, flag it but keep going.
            truncated = True
            logger.warning("dialog_auto_evaluation chunk hit the output-token limit "
                           f"(lines {start}+). Lower [script] dialog_batch_size.")
        try:
            result.update(json.loads(resp.choices[0].message.content))
        except json.JSONDecodeError as e:
            logger.warning(f"dialog_auto_evaluation parse failed for chunk {start}: {e}")
    if truncated:
        result["_truncated"] = (
            "⚠ Evaluation was cut off at the model's output-token limit — some "
            "lines were not evaluated."
        )
    return result


def _build_compact_dialog(gpt_output: dict) -> str:
    """
    Build a plain, copy-pasteable dialog string from GPT output.
    Includes narration and all dialog lines — no scene visuals, no metadata,
    no markup. Intended for grammar review.
    """
    lines = []

    # Narration
    nar_raw = gpt_output.get("narration", {})
    if isinstance(nar_raw, str):
        nar_text = nar_raw
    elif isinstance(nar_raw, dict):
        nar_text = nar_raw.get("text", "")
    else:
        nar_text = ""
    if nar_text:
        lines.append(f"[Erzähler] {_strip_fancy_notation(nar_text)}")
        lines.append("")

    # Dialog
    for item in gpt_output.get("dialog", []):
        speaker = item.get("speaker") or item.get("character") or "?"
        text    = _strip_fancy_notation(item.get("text", ""))
        lines.append(f"{speaker}: {text}")

    return "\n".join(lines)


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
    p.add_argument("--character", action="append", dest="characters", metavar="NAME",
                   help="Extra cast member for multi-character conversational types "
                        "(repeatable, e.g. --character Mario --character Olena).")
    p.add_argument("--location-key", required=False, default=None, dest="location_key")
    p.add_argument("--project-type",  default="story",  dest="project_type_key")
    p.add_argument("--prompt-override", default=None,   dest="prompt_override")
    a = p.parse_args()
    create_script(
        a.project_name, a.char_a, a.char_b, a.location_key,
        project_type_key=a.project_type_key,
        prompt_override=a.prompt_override,
        characters=a.characters,
    )


if __name__ == "__main__":
    main()
