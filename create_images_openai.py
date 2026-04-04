"""
create_images_openai.py

Generate images per scene using project manifest — OpenAI provider.

Each dialogue scene uses its own visual_context field from the manifest
(written by create_script.py) to drive a scene-specific image:
  - Narrator / establishing scenes: room composition from global visual_context
  - Dialogue scenes: illustrate what the character is talking ABOUT.
    e.g. if they mention going to the movies → show that character at a cinema.
    If no per-scene context is set, falls back to a standard room shot.

Character art reference images are still passed to OpenAI for consistency.
Saves RELATIVE (posix) paths in manifest.
"""

import os
import json
import base64
import logging
import argparse
import configparser
from pathlib import Path
from typing import List
import random

from PIL import Image
from dotenv import load_dotenv

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
random.seed()


# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)

    assets_dir    = Path(config["paths"]["assets_dir"])
    projects_dir  = Path(config["paths"]["projects_dir"])
    openai_model  = config.get("images", "openai_model",         fallback="gpt-image-1")
    shorts_res    = config.get("images", "shorts_resolution",    fallback="1024x1536")
    landscape_res = config.get("images", "landscape_resolution", fallback="1536x1024")
    extend_pad    = config.getfloat("images", "extend_pad_ratio", fallback=0.12)
    log_level     = config.get("images", "log_level",            fallback="INFO")

    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return assets_dir, projects_dir, openai_model, {
        "shorts": shorts_res, "landscape": landscape_res
    }, extend_pad


# =========================
# LOAD CHARACTERS
# =========================
def load_characters(assets_dir: Path) -> dict:
    path = assets_dir / "characters.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# RELATIVE PATH HELPER
# =========================
def to_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# =========================
# IMAGE UTIL
# =========================
def extend_image_vertical(input_path: Path, pad_ratio: float = 0.12):
    img = Image.open(input_path).convert("RGB")
    width, height = img.size
    pad = int(height * pad_ratio)
    new_img = Image.new("RGB", (width, height + pad), (255, 255, 255))
    new_img.paste(img, (0, pad // 2))
    new_img.save(input_path)


# =========================
# CHARACTER ART LOADER
# =========================
def load_character_images(characters: List[str], characters_data: dict, assets_dir: Path) -> list:
    image_inputs = []
    for c in characters:
        art_path = characters_data.get(c, {}).get("art")
        if not art_path:
            logger.warning(f"No art path for character: {c}")
            continue
        art_relative = Path(art_path)
        if art_relative.parts[0] == "assets":
            art_relative = Path(*art_relative.parts[1:])
        full_path = assets_dir / art_relative
        if full_path.exists():
            image_inputs.append(open(full_path, "rb"))
        else:
            logger.warning(f"Missing art file: {full_path}")
    if not image_inputs:
        raise RuntimeError("No character reference images found")
    return image_inputs


# =========================
# STYLE BLOCK
# =========================
STYLE_BLOCK = """Style:
- watercolor
- soft tones
- minimal facial detail, minimal clothing detail
- clean thicker outlines
- NEVER render text on images. no subtitles, no speech bubbles, no text.
- no anime eyes

Framing:
- vertical 9:16 composition
- central 80% contains important elements
- leave at least 8% margin on all sides
- no faces near edges
- characters centered
- background softly fades into white at the bottom

Consistency:
- characters MUST match reference images
- clothing, colors, facial features must remain consistent
- characters must appear only once per image"""


# =========================
# NARRATOR / ESTABLISHING SHOT PROMPT
# =========================
def build_narrator_prompt(
    global_visual_context: str,
    scene_visual_context: str,
    character_details: str,
    characters: List[str],
) -> str:
    scene_note = f"\nScene action: {scene_visual_context}" if scene_visual_context else ""
    return f"""Create a vertical illustration for a YouTube Shorts video.

Setting:
{global_visual_context}{scene_note}

Character details (STRICT consistency required):
{character_details}

{STYLE_BLOCK}

Scene composition:
Wide cinematic establishing shot showing: {', '.join(characters)}.
- Environment clearly visible
- Characters smaller in frame
- Storytelling mood"""


# =========================
# DIALOGUE SCENE PROMPT
# =========================
def build_scene_prompt(
    global_visual_context: str,
    scene_visual_context: str,
    character_details: str,
    speaker: str,
    text: str,
    others: List[str],
) -> str:
    """
    When scene_visual_context is set, it drives the scene completely —
    the image shows what the character is talking ABOUT (cinema, street, etc.).
    The global_visual_context is still referenced for character style anchoring.
    Falls back to a standard room two-shot when scene_visual_context is empty.
    """
    if scene_visual_context:
        scene_description = scene_visual_context
        composition_note  = (
            f"{speaker} is the visual focus. "
            + (f"Other character(s) may appear if relevant: {', '.join(others)}." if others else "")
        )
    else:
        shot_type = random.choice(["over_shoulder", "two_shot"])
        if shot_type == "over_shoulder":
            composition_note = (
                f"Shot: over-the-shoulder. Focus on {speaker}. "
                f"Show {', '.join(others) if others else 'environment'} softly in background."
            )
        else:
            composition_note = (
                f"Shot: two-shot. Show {speaker} and "
                f"{', '.join(others) if others else speaker}. Natural interaction."
            )
        scene_description = global_visual_context

    return f"""Create a vertical illustration for a YouTube Shorts video.

Character style reference (appearance must match these descriptions):
{global_visual_context}

Character details (STRICT consistency required):
{character_details}

{STYLE_BLOCK}

Scene to illustrate:
{scene_description}

{speaker} is speaking: "{text}"

Composition: {composition_note}"""


# =========================
# IMAGE GENERATION (OpenAI)
# =========================
def generate_image(prompt: str, image_inputs: list, model: str, size: str) -> bytes:
    from openai import OpenAI
    oa = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("Prompt:\n" + prompt + "\n")
    response = oa.images.edit(
        model=model,
        image=image_inputs,
        prompt=prompt,
        quality="medium",
        input_fidelity="high",
        size=size,
    )
    return base64.b64decode(response.data[0].b64_json)


# =========================
# SHARED SETUP HELPER
# =========================
def _setup(project_name: str):
    assets_dir, projects_dir, openai_model, resolutions, extend_pad = load_config()
    characters_data = load_characters(assets_dir)

    project_path  = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("Missing project_manifest.json")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    global_visual_context = manifest["script"].get("visual_context", "")
    scenes = manifest["scenes"]

    all_characters = list({
        s["character"] for s in scenes
        if s["type"] == "dialogue" and not s.get("is_narrator", False)
    })
    char_descriptions = "\n".join(
        f"{c}: {characters_data.get(c, {}).get('description', '')}"
        for c in all_characters
    )

    return (
        assets_dir, projects_dir, openai_model, resolutions, extend_pad,
        characters_data, project_path, manifest_path, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    )


# =========================
# TEST FUNCTION
# =========================
def test_image_generation(project_name: str, output_path: str = "test_image.png"):
    (
        assets_dir, _, openai_model, resolutions, extend_pad,
        characters_data, _, _, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    ) = _setup(project_name)

    first_narrator = next(
        (s for s in scenes if s.get("is_narrator") and s.get("visual_context")), None
    )
    scene_vc = first_narrator["visual_context"] if first_narrator else ""

    prompt       = build_narrator_prompt(global_visual_context, scene_vc, char_descriptions, all_characters)
    image_inputs = load_character_images(all_characters, characters_data, assets_dir)

    logger.info("Test image generation (narrator, OpenAI)")
    image_bytes = generate_image(prompt, image_inputs, openai_model, resolutions["shorts"])

    out = Path(output_path)
    with open(out, "wb") as f:
        f.write(image_bytes)
    extend_image_vertical(out, extend_pad)
    logger.info(f"Test image saved: {out}")


# =========================
# MAIN
# =========================
def generate_images(project_name: str, format_type: str = "shorts"):
    (
        assets_dir, projects_dir, openai_model, resolutions, extend_pad,
        characters_data, project_path, manifest_path, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    ) = _setup(project_name)

    size       = resolutions[format_type]
    images_dir = project_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # ---- NARRATOR / ESTABLISHING IMAGE ----
    narrator_path = images_dir / "scene_narrator.png"

    if not narrator_path.exists():
        logger.info("Generating narrator image...")
        first_narrator = next(
            (s for s in scenes if s.get("is_narrator") and s.get("visual_context")), None
        )
        scene_vc     = first_narrator["visual_context"] if first_narrator else ""
        prompt       = build_narrator_prompt(global_visual_context, scene_vc, char_descriptions, all_characters)
        image_inputs = load_character_images(all_characters, characters_data, assets_dir)
        image_bytes  = generate_image(prompt, image_inputs, openai_model, size)

        with open(narrator_path, "wb") as f:
            f.write(image_bytes)
        extend_image_vertical(narrator_path, extend_pad)
        logger.info("Narrator image saved.")
    else:
        logger.info("Narrator image already exists, skipping.")

    manifest["narrator_image"] = to_relative(narrator_path, project_path)

    # ---- SCENE IMAGES ----
    for scene in scenes:
        if scene["type"] != "dialogue":
            continue

        if scene.get("is_narrator", False):
            scene["image"] = manifest["narrator_image"]
            continue

        scene_id    = scene["id"]
        speaker     = scene["character"]
        text        = scene["text"]
        scene_vc    = scene.get("visual_context", "")
        output_path = images_dir / f"{scene_id}.png"

        if output_path.exists():
            logger.info(f"Skipping existing {scene_id}")
            scene["image"] = to_relative(output_path, project_path)
            continue

        logger.info(f"Generating {scene_id} ({speaker}): {scene_vc[:80]}...")

        others          = [c for c in all_characters if c != speaker]
        selected_others = random.sample(others, min(2, len(others)))
        scene_chars     = [speaker] + selected_others

        prompt       = build_scene_prompt(
            global_visual_context, scene_vc, char_descriptions,
            speaker, text, selected_others,
        )
        image_inputs = load_character_images(scene_chars, characters_data, assets_dir)
        image_bytes  = generate_image(prompt, image_inputs, openai_model, size)

        with open(output_path, "wb") as f:
            f.write(image_bytes)
        extend_image_vertical(output_path, extend_pad)
        scene["image"] = to_relative(output_path, project_path)

    # ---- SAVE MANIFEST ----
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info("Image generation completed.")


# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Generate images for project (OpenAI)")
    parser.add_argument("project_name")
    parser.add_argument("--format", choices=["shorts", "landscape"], default="shorts")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test-output", default="test_image.png")
    args = parser.parse_args()

    if args.test:
        test_image_generation(args.project_name, args.test_output)
    else:
        generate_images(args.project_name, args.format)

if __name__ == "__main__":
    generate_images("coffee_convo_1")
