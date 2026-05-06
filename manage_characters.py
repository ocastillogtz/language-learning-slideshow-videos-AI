"""
manage_characters.py
====================
CLI and importable functions for character asset CRUD.

Commands
--------
  list                          — print all characters
  add   --name --voice-id --fixed --variable [--height] [--ref-desc]
  edit  --name [--voice-id] [--fixed] [--variable] [--height] [--ref-desc]
  remove --name
  generate-art --name           — call fal.ai to generate artwork (art.png, 34left.png)

Usage
-----
  python manage_characters.py list
  python manage_characters.py add --name "Kai" --voice-id "abc123" \\
      --fixed "from Japan, male, 22 years old, slim build, black hair" \\
      --variable "wearing a grey hoodie and jeans" --height 175
  python manage_characters.py generate-art --name "Kai"
"""

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import fal_client
from dotenv import load_dotenv

from utils_config import load_config

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _chars_path(assets_dir: Path) -> Path:
    return assets_dir / "characters" / "characters.json"

def _registry_path(assets_dir: Path) -> Path:
    return assets_dir / "assets.json"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_characters(assets_dir: Path) -> dict:
    path = _chars_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_characters(assets_dir: Path, data: dict) -> None:
    path = _chars_path(assets_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_registry(assets_dir: Path) -> dict:
    path = _registry_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_registry(assets_dir: Path, data: dict) -> None:
    path = _registry_path(assets_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core functions (importable by Flask routes)
# ---------------------------------------------------------------------------

def list_characters(assets_dir: Path) -> list[dict]:
    return list(load_characters(assets_dir).values())


def add_character(
    assets_dir: Path,
    name: str,
    voice_id: str,
    fixed_description: str,
    variable_description: str,
    height_cm: int | None = None,
    ref_desc: str | None = None,
) -> dict:
    chars = load_characters(assets_dir)
    if name in chars:
        raise ValueError(f"Character '{name}' already exists. Use edit to update.")

    entry = {
        "name": name,
        "voice_id": voice_id,
        "fixed_description": fixed_description,
        "variable_description": variable_description,
        "height_cm": height_cm,
        "ref_desc": ref_desc,
        "ref_drawing_file_path": None,   # user-uploaded reference drawing
        "artwork_file_path": None,
        "art_34left_file_path": None,
        "thumbnail_file_path": None,
        "concept_art_file_path": None,
    }
    chars[name] = entry
    save_characters(assets_dir, chars)

    # Update master registry
    registry = load_registry(assets_dir)
    registry.setdefault("characters", {})[name] = {
        "config": f"characters/characters.json#{name}"
    }
    save_registry(assets_dir, registry)

    logger.info(f"Character '{name}' added.")
    return entry


def edit_character(assets_dir: Path, name: str, **kwargs) -> dict:
    chars = load_characters(assets_dir)
    if name not in chars:
        raise ValueError(f"Character '{name}' not found.")

    allowed = {
        "voice_id", "fixed_description", "variable_description",
        "height_cm", "ref_desc", "ref_drawing_file_path",
        "artwork_file_path", "art_34left_file_path",
        "thumbnail_file_path", "concept_art_file_path",
    }
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            chars[name][k] = v

    save_characters(assets_dir, chars)
    logger.info(f"Character '{name}' updated.")
    return chars[name]


def remove_character(assets_dir: Path, name: str) -> None:
    chars = load_characters(assets_dir)
    if name not in chars:
        raise ValueError(f"Character '{name}' not found.")
    del chars[name]
    save_characters(assets_dir, chars)

    registry = load_registry(assets_dir)
    registry.get("characters", {}).pop(name, None)
    save_registry(assets_dir, registry)
    logger.info(f"Character '{name}' removed.")


def save_reference_image(assets_dir: Path, name: str, image_bytes: bytes, ext: str = ".png") -> str:
    """
    Save a user-uploaded reference drawing for a character.
    Returns the relative path stored in characters.json.
    """
    chars = load_characters(assets_dir)
    if name not in chars:
        raise KeyError(f"Character '{name}' not found.")

    char_dir = assets_dir / "characters" / name
    char_dir.mkdir(parents=True, exist_ok=True)

    filename  = f"ref_drawing{ext}"
    dest      = char_dir / filename
    dest.write_bytes(image_bytes)

    rel_path = f"characters/{name}/{filename}"
    chars[name]["ref_drawing_file_path"] = rel_path
    save_characters(assets_dir, chars)
    logger.info(f"Reference drawing saved: {dest}")
    return rel_path


def generate_character_art(assets_dir: Path, name: str) -> dict:
    """
    Call fal.ai to generate a character art turnaround sheet and a 3/4-left image.

    If the character has a ref_drawing_file_path, the drawing is uploaded to fal.ai
    and used as a visual reference (img2img mode with the edit model).
    Otherwise, pure text-to-image is used.

    Saves results to assets/characters/<name>/ and updates the character entry.
    """
    chars = load_characters(assets_dir)
    if name not in chars:
        raise ValueError(f"Character '{name}' not found.")

    char     = chars[name]
    fixed    = char.get("fixed_description", "")
    variable = char.get("variable_description", "")
    full_desc = f"{fixed}, {variable}".strip(", ")

    char_dir = assets_dir / "characters" / name
    char_dir.mkdir(parents=True, exist_ok=True)

    cfg        = load_config()
    edit_model = cfg.get("fal_model", "fal-ai/bytedance/seedream/v4.5/edit")
    t2i_model  = "fal-ai/flux/dev"   # fallback for pure text-to-image

    # Upload reference drawing if one exists
    ref_url: str | None = None
    ref_rel = char.get("ref_drawing_file_path")
    if ref_rel:
        ref_path = assets_dir / ref_rel
        if ref_path.exists():
            logger.info(f"Uploading reference drawing for '{name}' …")
            ref_url = fal_client.upload(ref_path.read_bytes(), content_type="image/png")
            logger.info(f"  Reference uploaded → {ref_url}")

    def _call(prompt: str, image_size: str) -> str:
        """Call fal.ai and return the result image URL."""
        if ref_url:
            result = fal_client.subscribe(
                edit_model,
                arguments={"prompt": prompt, "image_size": image_size, "image_urls": [ref_url]},
                with_logs=False,
            )
        else:
            result = fal_client.subscribe(
                t2i_model,
                arguments={"prompt": prompt, "image_size": image_size},
            )
        return result["images"][0]["url"]

    style_suffix = cfg["image_character_art_style"]

    # --- Art turnaround sheet ---
    art_prompt = (
        f"Character turnaround sheet showing 4 views (front, 3/4 left, side, back) of: {full_desc}. "
        + style_suffix
    )
    logger.info(f"Generating turnaround art for '{name}' …")
    art_url  = _call(art_prompt, "landscape_16_9")
    art_path = char_dir / "art.png"
    _download(art_url, art_path)
    chars[name]["artwork_file_path"] = f"characters/{name}/art.png"

    # --- 3/4 left view (used as scene composite reference) ---
    left_prompt = (
        f"3/4 left full body view of: {full_desc}. " + style_suffix
    )
    logger.info(f"Generating 3/4-left view for '{name}' …")
    left_url  = _call(left_prompt, "portrait_4_3")
    left_path = char_dir / "34left.png"
    _download(left_url, left_path)
    chars[name]["art_34left_file_path"] = f"characters/{name}/34left.png"

    save_characters(assets_dir, chars)
    logger.info(f"Art generated for '{name}': {art_path}, {left_path}")
    return chars[name]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path) -> None:
    import urllib.request
    urllib.request.urlretrieve(url, dest)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    assets_dir = cfg["assets_dir"]

    p = argparse.ArgumentParser(description="Manage character assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all characters")

    a = sub.add_parser("add", help="Add a new character")
    a.add_argument("--name",     required=True)
    a.add_argument("--voice-id", required=True)
    a.add_argument("--fixed",    required=True, dest="fixed_description")
    a.add_argument("--variable", required=True, dest="variable_description")
    a.add_argument("--height",   type=int,      dest="height_cm")
    a.add_argument("--ref-desc", dest="ref_desc")

    e = sub.add_parser("edit", help="Edit an existing character")
    e.add_argument("--name",     required=True)
    e.add_argument("--voice-id", dest="voice_id")
    e.add_argument("--fixed",    dest="fixed_description")
    e.add_argument("--variable", dest="variable_description")
    e.add_argument("--height",   type=int, dest="height_cm")
    e.add_argument("--ref-desc", dest="ref_desc")

    r = sub.add_parser("remove", help="Remove a character")
    r.add_argument("--name", required=True)

    g = sub.add_parser("generate-art", help="Generate character artwork via fal.ai")
    g.add_argument("--name", required=True)

    args = p.parse_args()

    if args.cmd == "list":
        chars = list_characters(assets_dir)
        for c in chars:
            print(f"  {c['name']:12}  voice={c['voice_id']}  art={'yes' if c.get('artwork_file_path') else 'no'}")

    elif args.cmd == "add":
        add_character(
            assets_dir,
            name=args.name,
            voice_id=args.voice_id,
            fixed_description=args.fixed_description,
            variable_description=args.variable_description,
            height_cm=args.height_cm,
            ref_desc=args.ref_desc,
        )
        print(f"Character '{args.name}' added.")

    elif args.cmd == "edit":
        edit_character(
            assets_dir, args.name,
            voice_id=args.voice_id,
            fixed_description=args.fixed_description,
            variable_description=args.variable_description,
            height_cm=args.height_cm,
            ref_desc=args.ref_desc,
        )
        print(f"Character '{args.name}' updated.")

    elif args.cmd == "remove":
        remove_character(assets_dir, args.name)
        print(f"Character '{args.name}' removed.")

    elif args.cmd == "generate-art":
        generate_character_art(assets_dir, args.name)
        print(f"Art generated for '{args.name}'.")


if __name__ == "__main__":
    main()
