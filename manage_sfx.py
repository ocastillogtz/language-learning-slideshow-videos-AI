"""
manage_sfx.py
=============
CLI and importable functions for SFX asset management.

Commands
--------
  list
  add    --name --description --file <path>
  remove --name

Usage
-----
  python manage_sfx.py list
  python manage_sfx.py add \\
      --name "chime" \\
      --description "Soft chime for transitions" \\
      --file /path/to/chime.mp3
"""

import argparse
import json
import logging
import shutil
from pathlib import Path

import db
from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load / Save — the catalog lives in data/pipeline.db (see db.py). This library is
# SHARED by every workspace; file paths are relative to cfg["library_dir"].
# ---------------------------------------------------------------------------

def load_sfx(library_dir: Path | None = None) -> dict:
    return db.load_assets("sfx")

def save_sfx(library_dir: Path | None, data: dict) -> None:
    db.save_assets("sfx", data)


# ---------------------------------------------------------------------------
# Core functions (importable by Flask routes)
# ---------------------------------------------------------------------------

def list_sfx(library_dir: Path) -> list[dict]:
    return list(load_sfx(library_dir).values())


def add_sfx(
    library_dir: Path,
    name: str,
    description: str,
    source_file: Path,
) -> dict:
    sfx = load_sfx(library_dir)
    if name in sfx:
        raise ValueError(f"SFX '{name}' already exists.")

    sfx_dir = library_dir / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(source_file).suffix
    dest = sfx_dir / f"{name}{suffix}"
    shutil.copy2(source_file, dest)

    entry = {
        "name": name,
        "description": description,
        "full_path": f"sfx/{name}{suffix}",
    }
    sfx[name] = entry
    save_sfx(library_dir, sfx)


    logger.info(f"SFX '{name}' added.")
    return entry


def remove_sfx(library_dir: Path, name: str, delete_file: bool = False) -> None:
    sfx = load_sfx(library_dir)
    if name not in sfx:
        raise ValueError(f"SFX '{name}' not found.")

    if delete_file:
        file_path = library_dir / sfx[name].get("full_path", "")
        if file_path.exists():
            file_path.unlink()

    del sfx[name]
    save_sfx(library_dir, sfx)

    logger.info(f"SFX '{name}' removed.")


def resolve_sfx_path(library_dir: Path, asset_key: str) -> Path:
    """Return the absolute path for an SFX asset_key. Used by create_video."""
    sfx = load_sfx(library_dir)
    if asset_key not in sfx:
        raise ValueError(f"SFX '{asset_key}' not found in sfx.json.")
    return library_dir / sfx[asset_key]["full_path"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    library_dir = cfg["library_dir"]

    p = argparse.ArgumentParser(description="Manage SFX assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all SFX")

    a = sub.add_parser("add", help="Add an SFX file")
    a.add_argument("--name",        required=True)
    a.add_argument("--description", required=True)
    a.add_argument("--file",        required=True)

    r = sub.add_parser("remove", help="Remove an SFX file")
    r.add_argument("--name",        required=True)
    r.add_argument("--delete-file", action="store_true", dest="delete_file")

    args = p.parse_args()

    if args.cmd == "list":
        for s in list_sfx(library_dir):
            print(f"  {s['name']:25}  {s['full_path']}  —  {s['description']}")

    elif args.cmd == "add":
        add_sfx(library_dir, args.name, args.description, Path(args.file))
        print(f"SFX '{args.name}' added.")

    elif args.cmd == "remove":
        remove_sfx(library_dir, args.name, delete_file=args.delete_file)
        print(f"SFX '{args.name}' removed.")


if __name__ == "__main__":
    main()
