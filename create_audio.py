"""
create_audio.py

Generate per-scene audio and update project_manifest.json

Input:
    project_manifest.json

Output:
    audio/*.mp3
    updated project_manifest.json
"""

import os
import io
import json
import base64
import logging
import argparse
import configparser
from pathlib import Path

from pydub import AudioSegment
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

# =========================
# CONFIG
# =========================
LOG_LEVEL = logging.INFO

# Valid model for convert_with_timestamps
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# ENV
# =========================
load_dotenv()

eleven_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)
    return (
        Path(config["paths"]["projects_dir"]),
        Path(config["paths"]["assets_dir"])
    )

# =========================
# LOAD CHARACTERS
# =========================
def load_characters(assets_dir: Path):
    path = assets_dir / "characters.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing characters.json at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# =========================
# WORD BUILDER
# =========================
def characters_to_words(chars, starts, ends):
    words = []
    current_word = ""
    word_start = None

    for i, char in enumerate(chars):
        if char != " ":
            if current_word == "":
                word_start = starts[i]
            current_word += char
            word_end = ends[i]
        else:
            if current_word:
                words.append({"word": current_word, "start": word_start, "end": word_end})
                current_word = ""

    if current_word:
        words.append({"word": current_word, "start": word_start, "end": word_end})

    return words

# =========================
# MAIN
# =========================
def create_audio(project_name: str):

    projects_dir, assets_dir = load_config()
    project_path = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"
    audio_dir = project_path / "audio"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    audio_dir.mkdir(parents=True, exist_ok=True)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    characters = load_characters(assets_dir)
    scenes = manifest.get("scenes", [])

    dialogue_scenes = [s for s in scenes if s["type"] == "dialogue"]

    for scene in scenes:

        scene_id = scene["id"]
        scene_type = scene["type"]

        logger.info(f"Processing {scene_id} | {scene_type}")

        if scene_type != "dialogue":
            continue

        # Skip already-generated audio
        if scene.get("audio") and scene["audio"].get("file"):
            audio_path = project_path / scene["audio"]["file"]
            if audio_path.exists():
                logger.info(f"  Skipping {scene_id} (audio exists)")
                continue

        character = scene["character"]

        if character not in characters:
            logger.warning(f"Character not found in characters.json: {character}")
            continue

        voice_id = characters[character]["voice_id"]

        # ----------------------
        # CONTEXT TEXTS
        # Find the previous and next dialogue scenes for prosody context.
        # ElevenLabs uses these to improve intonation at sentence boundaries.
        # ----------------------
        scene_idx     = dialogue_scenes.index(scene)
        previous_text = dialogue_scenes[scene_idx - 1]["text"] if scene_idx > 0 else None
        next_text     = dialogue_scenes[scene_idx + 1]["text"] if scene_idx < len(dialogue_scenes) - 1 else None

        # ----------------------
        # GENERATE AUDIO
        # ----------------------
        logger.info(f"  Generating audio for {scene_id} ({character})")

        result = eleven_client.text_to_speech.convert_with_timestamps(
            text=scene["text"],
            voice_id=voice_id,
            model_id=ELEVENLABS_MODEL,
            output_format="mp3_44100_128",
            previous_text=previous_text,
            next_text=next_text,
        )

        # convert_with_timestamps always returns an object with audio_base_64
        if not hasattr(result, "audio_base_64"):
            logger.error(f"  Unexpected response type for {scene_id}: {type(result)}")
            continue

        audio_bytes = base64.b64decode(result.audio_base_64)
        alignment = result.normalized_alignment

        # ----------------------
        # SAVE AUDIO FILE
        # ----------------------
        audio_filename = f"{scene_id}.mp3"
        audio_path = audio_dir / audio_filename

        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # ----------------------
        # GET DURATION
        # ----------------------
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        duration_ms = len(audio_segment)

        # ----------------------
        # WORD TIMESTAMPS
        # ----------------------
        words = []
        if alignment and alignment.characters:
            words = characters_to_words(
                alignment.characters,
                alignment.character_start_times_seconds,
                alignment.character_end_times_seconds
            )

        # ----------------------
        # UPDATE SCENE (relative path)
        # ----------------------
        scene["audio"] = {
            "file": f"audio/{audio_filename}",  # always relative
            "duration_ms": duration_ms,
            "words": words
        }

        logger.info(f"  Done: {audio_filename} ({duration_ms}ms, {len(words)} words)")

    # ----------------------
    # SAVE MANIFEST
    # ----------------------
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info("Audio generation complete and manifest updated")

# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Generate audio and update manifest")
    parser.add_argument("project_name", help="Project name")
    args = parser.parse_args()
    create_audio(args.project_name)

# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    create_audio("office_convo_4")