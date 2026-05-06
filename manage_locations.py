"""
manage_locations.py
===================
CLI and importable functions for location asset CRUD.

Commands
--------
  list
  add   --name --description --creation-prompt [--eligible-chars char1 char2 ...]
  edit  --name [--description] [--creation-prompt]
  remove --name
  generate-art --name   — call fal.ai to generate background image

Usage
-----
  python manage_locations.py list
  python manage_locations.py add \\
      --name "park" \\
      --description "a sunny public park with benches and trees" \\
      --creation-prompt "Bright sunny public park, green grass, wooden benches, no people."
  python manage_locations.py generate-art --name "park"
"""

import argparse
import json
import logging
import urllib.request
from pathlib import Path

import fal_client
from dotenv import load_dotenv

from utils_config import load_config

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ALL_CHARACTERS = ["Amir", "Mario", "Sani", "Olena", "Zahra", "Wiebke"]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _locs_path(assets_dir: Path) -> Path:
    return assets_dir / "locations" / "locations.json"

def _registry_path(assets_dir: Path) -> Path:
    return assets_dir / "assets.json"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_locations(assets_dir: Path) -> dict:
    path = _locs_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_locations(assets_dir: Path, data: dict) -> None:
    path = _locs_path(assets_dir)
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

def list_locations(assets_dir: Path) -> list[dict]:
    return list(load_locations(assets_dir).values())


def add_location(
    assets_dir: Path,
    name: str,
    description: str,
    creation_prompt: str,
    eligible_characters: list[str] | None = None,
    characters_amount: int = 2,
) -> dict:
    locs = load_locations(assets_dir)
    if name in locs:
        raise ValueError(f"Location '{name}' already exists. Use edit to update.")

    entry = {
        "name": name,
        "description": description,
        "creation_prompt": creation_prompt,
        "artwork_file_path": None,
        "characters_amount": characters_amount,
        "eligible_characters": eligible_characters or ALL_CHARACTERS,
        "sub_locations": {},
    }
    locs[name] = entry
    save_locations(assets_dir, locs)

    registry = load_registry(assets_dir)
    registry.setdefault("locations", {})[name] = {
        "config": f"locations/locations.json#{name}"
    }
    save_registry(assets_dir, registry)

    logger.info(f"Location '{name}' added.")
    return entry


def edit_location(assets_dir: Path, name: str, **kwargs) -> dict:
    locs = load_locations(assets_dir)
    if name not in locs:
        raise ValueError(f"Location '{name}' not found.")

    allowed = {"description", "creation_prompt", "artwork_file_path", "eligible_characters", "characters_amount"}
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            locs[name][k] = v

    save_locations(assets_dir, locs)
    logger.info(f"Location '{name}' updated.")
    return locs[name]


def remove_location(assets_dir: Path, name: str) -> None:
    locs = load_locations(assets_dir)
    if name not in locs:
        raise ValueError(f"Location '{name}' not found.")
    del locs[name]
    save_locations(assets_dir, locs)

    registry = load_registry(assets_dir)
    registry.get("locations", {}).pop(name, None)
    save_registry(assets_dir, registry)
    logger.info(f"Location '{name}' removed.")


def generate_location_art(assets_dir: Path, name: str) -> dict:
    """Call fal.ai to generate the location background image."""
    locs = load_locations(assets_dir)
    if name not in locs:
        raise ValueError(f"Location '{name}' not found.")

    loc = locs[name]
    prompt = loc.get("creation_prompt") or loc.get("description", "")
    if not prompt:
        raise ValueError(f"Location '{name}' has no creation_prompt set.")

    loc_dir = assets_dir / "locations"
    loc_dir.mkdir(parents=True, exist_ok=True)
    out_path = loc_dir / f"{name}.png"

    cfg = load_config()
    model = cfg.get("fal_t2i_model", "fal-ai/flux/dev")

    full_prompt = f"{prompt} {cfg['image_location_art_style']}"

    logger.info(f"Generating location art for '{name}' …")
    result = fal_client.subscribe(
        model,
        arguments={"prompt": full_prompt, "image_size": "portrait_16_9"},
    )
    url = result["images"][0]["url"]
    urllib.request.urlretrieve(url, out_path)

    locs[name]["artwork_file_path"] = f"locations/{name}.png"
    save_locations(assets_dir, locs)
    logger.info(f"Location art saved: {out_path}")
    return locs[name]


def get_all_locations_flat(assets_dir: Path) -> dict:
    """Return flat dict including sub_locations, for use in create_script."""
    locs = load_locations(assets_dir)
    flat: dict = {}
    for key, loc in locs.items():
        flat[key] = loc
        for sub_key, sub_loc in loc.get("sub_locations", {}).items():
            flat[sub_key] = sub_loc
    return flat


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    assets_dir = cfg["assets_dir"]

    p = argparse.ArgumentParser(description="Manage location assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all locations")

    a = sub.add_parser("add", help="Add a new location")
    a.add_argument("--name",             required=True)
    a.add_argument("--description",      required=True)
    a.add_argument("--creation-prompt",  required=True, dest="creation_prompt")
    a.add_argument("--eligible-chars",   nargs="+",     dest="eligible_chars")
    a.add_argument("--chars-amount",     type=int,      dest="characters_amount", default=2)

    e = sub.add_parser("edit", help="Edit an existing location")
    e.add_argument("--name",            required=True)
    e.add_argument("--description")
    e.add_argument("--creation-prompt", dest="creation_prompt")

    r = sub.add_parser("remove", help="Remove a location")
    r.add_argument("--name", required=True)

    g = sub.add_parser("generate-art", help="Generate location background via fal.ai")
    g.add_argument("--name", required=True)

    args = p.parse_args()

    if args.cmd == "list":
        for loc in list_locations(assets_dir):
            art = "yes" if loc.get("artwork_file_path") else "no"
            print(f"  {loc['name']:15}  art={art}  chars={loc.get('eligible_characters', [])}")

    elif args.cmd == "add":
        add_location(
            assets_dir,
            name=args.name,
            description=args.description,
            creation_prompt=args.creation_prompt,
            eligible_characters=args.eligible_chars,
            characters_amount=args.characters_amount,
        )
        print(f"Location '{args.name}' added.")

    elif args.cmd == "edit":
        edit_location(
            assets_dir, args.name,
            description=args.description,
            creation_prompt=args.creation_prompt,
        )
        print(f"Location '{args.name}' updated.")

    elif args.cmd == "remove":
        remove_location(assets_dir, args.name)
        print(f"Location '{args.name}' removed.")

    elif args.cmd == "generate-art":
        generate_location_art(assets_dir, args.name)
        print(f"Art generated for '{args.name}'.")


if __name__ == "__main__":
    main()
