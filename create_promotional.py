"""
create_promotional.py
======================
Build step for the `promotional` project type.

A promotional video is a single STILL image of ONE of your characters speaking a
short promotional line — intended as a vertical Instagram story that links to a
reel. Unlike the dialogue types, there is NO GPT pass: the user supplies the
character, an image-situation description, and the exact text to be spoken.

build_promotional_project() turns those three inputs into ONE universal scene
(image + TTS audio + subtitle) that the normal audio → images → video → assemble
pipeline then renders. Vertical only; no intro, no horizontal variant.
"""

import argparse
import json
import logging
from pathlib import Path

from utils_config import load_config, load_new_characters
import create_script as cs  # reuse style/framing tokens (no GPT call is made)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _promo_image_prompt(character: str, char_data: dict, situation: str,
                        framing_tokens: str | None = None) -> str:
    """Text-to-image prompt: the character, talking to camera, in the given situation."""
    cs._load_style_tokens()
    style   = cs._STYLE_TOKENS
    framing = framing_tokens or cs._FRAMING_TOKENS
    fixed   = char_data.get("fixed_description", "") or ""
    situation = situation or "a clean, simple background"
    return (
        f"{style}\n"
        f"FRAMING: {framing}\n\n"
        f"Character: {character} — {fixed}\n\n"
        f"Situation: {situation}\n\n"
        "A single still shot of the character in this situation, facing the viewer as if "
        "speaking directly to camera (addressing the audience). Match exact clothing, hair, "
        "and facial features from the reference. Integrate the character naturally into the "
        "setting. No text, no subtitles, no speech bubbles, no anime eyes, no watermarks."
    )


def build_promotional_project(project_name: str, character: str,
                              situation: str, text: str) -> dict:
    """Construct the single promotional scene and write it into the manifest.

    Parameters
    ----------
    project_name : existing project folder (created by create_project).
    character    : key of one of your characters (assets/characters/characters.json).
    situation    : English description of the image / setting for the still.
    text         : the exact German line the character says (TTS + subtitle).
    """
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found — run create_project first")

    character = (character or "").strip()
    situation = (situation or "").strip()
    text      = (text or "").strip()
    if not character:
        raise ValueError("A character is required for a promotional video.")
    if not text:
        raise ValueError("The text the character says is required.")

    chars_data = load_new_characters(cfg["assets_dir"])
    if character not in chars_data:
        raise ValueError(f"Character '{character}' not found in characters.json")
    char_data = chars_data[character]
    voice_id  = char_data.get("voice_id", "")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    img_prompt = _promo_image_prompt(character, char_data, situation,
                                     cfg.get("image_framing_tokens"))

    # One still scene: image (single character ref) + spoken line + subtitle.
    # scene["characters"] is left EMPTY so the dialog speaker-icon is NOT overlaid
    # (the whole frame is already the character); image generation uses image.speaker.
    scene = {
        "id": "scene_001",
        "description": f"promotional [{character}]",
        "characters": [],
        "scene_visual": situation,
        "scene_characters": "speaker_only",
        "image": {
            "file_path": None,
            "prompt_to_create": img_prompt,
            "reference_type": "single_speaker",
            "speaker": character,
        },
        "audio": {"type": "tts", "file_path": None, "tts_text": text,
                  "voice_id": voice_id, "duration_ms": None},
        "subtitle_text": text,
        "duration_ms": None,
    }

    gen = manifest.setdefault("generation_config", {})
    gen["characters"] = [character]
    gen["promotional"] = {"character": character, "situation": situation, "text": text}
    manifest.setdefault("video_info", {})["video_format"] = "vertical"
    if not manifest["video_info"].get("title"):
        manifest["video_info"]["title"] = text[:60]
    manifest["scenes"] = [scene]

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info("promotional scene built: character=%s, %d chars of text", character, len(text))
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="Build a promotional (single-image) scene")
    p.add_argument("project_name")
    p.add_argument("--character", required=True, help="Character key (from characters.json)")
    p.add_argument("--situation", default="", help="Image situation / setting description")
    p.add_argument("--text", required=True, help="The line the character says")
    a = p.parse_args()
    build_promotional_project(a.project_name, a.character, a.situation, a.text)


if __name__ == "__main__":
    main()
