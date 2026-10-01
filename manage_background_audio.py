"""
manage_background_audio.py
===========================
CLI and importable functions for background audio asset management.

Commands
--------
  list   [--license YTsafe|Metasafe|TikToksafe]
  add    --name --description --file <path> [--license YTsafe|Metasafe|TikToksafe]
  edit   --name [--description] [--license]
  remove --name

"license" says which platform the track is safe on (see platform_audio):
YTsafe = YouTube Audio Library (blocked on long Instagram videos),
Metasafe = Meta Sound Collection, TikToksafe = reserved for TikTok.

Usage
-----
  python manage_background_audio.py list
  python manage_background_audio.py add \\
      --name "cafe_ambience" \\
      --description "Warm coffeeshop background noise loop" \\
      --file /path/to/cafe_bg.mp3
"""

import argparse
import json
import logging
import shutil
from pathlib import Path

from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _audio_path(assets_dir: Path) -> Path:
    return assets_dir / "background_audio" / "background_audio.json"

def _registry_path(assets_dir: Path) -> Path:
    return assets_dir / "assets.json"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_background_audio(assets_dir: Path) -> dict:
    path = _audio_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_background_audio(assets_dir: Path, data: dict) -> None:
    path = _audio_path(assets_dir)
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
    with open(_registry_path(assets_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core functions (importable by Flask routes)
# ---------------------------------------------------------------------------

LICENSES = ("YTsafe", "Metasafe", "TikToksafe")


def list_background_audio(assets_dir: Path, license: str | None = None) -> list[dict]:
    tracks = load_background_audio(assets_dir).values()
    return [t for t in tracks if not license or t.get("license") == license]


def add_background_audio(
    assets_dir: Path,
    name: str,
    description: str,
    source_file: Path,
    license: str | None = None,
    subdir: str = "",
) -> dict:
    if license and license not in LICENSES:
        raise ValueError(f"license must be one of {LICENSES}")
    audio = load_background_audio(assets_dir)
    if name in audio:
        raise ValueError(f"Background audio '{name}' already exists.")

    audio_dir = assets_dir / "background_audio" / subdir
    audio_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(source_file).suffix
    dest = audio_dir / f"{name}{suffix}"
    shutil.copy2(source_file, dest)

    rel = "/".join(x for x in ("background_audio", subdir, f"{name}{suffix}") if x)
    entry = {
        "name": name,
        "description": description,
        "full_path": rel,
    }
    if license:
        entry["license"] = license
    audio[name] = entry
    save_background_audio(assets_dir, audio)

    registry = load_registry(assets_dir)
    registry.setdefault("background_audio", {})[name] = {
        "config": f"background_audio/background_audio.json#{name}"
    }
    save_registry(assets_dir, registry)

    logger.info(f"Background audio '{name}' added.")
    return entry


def edit_background_audio(assets_dir: Path, name: str, data: dict) -> dict:
    """Update description / license of a registered track. KeyError if unknown."""
    audio = load_background_audio(assets_dir)
    if name not in audio:
        raise KeyError(name)
    entry = audio[name]
    if "description" in data:
        entry["description"] = data["description"]
    if "license" in data:
        lic = (data["license"] or "").strip()
        if lic and lic not in LICENSES:
            raise ValueError(f"license must be one of {LICENSES}")
        if lic:
            entry["license"] = lic
        else:
            entry.pop("license", None)
    save_background_audio(assets_dir, audio)
    return entry


def remove_background_audio(assets_dir: Path, name: str, delete_file: bool = False) -> None:
    audio = load_background_audio(assets_dir)
    if name not in audio:
        raise ValueError(f"Background audio '{name}' not found.")

    if delete_file:
        file_path = assets_dir / audio[name].get("full_path", "")
        if file_path.exists():
            file_path.unlink()

    del audio[name]
    save_background_audio(assets_dir, audio)

    registry = load_registry(assets_dir)
    registry.get("background_audio", {}).pop(name, None)
    save_registry(assets_dir, registry)
    logger.info(f"Background audio '{name}' removed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    assets_dir = cfg["assets_dir"]

    p = argparse.ArgumentParser(description="Manage background audio assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("list", help="List all background audio tracks")
    l.add_argument("--license", choices=LICENSES, default=None)

    a = sub.add_parser("add", help="Add a background audio track")
    a.add_argument("--name",        required=True)
    a.add_argument("--description", required=True)
    a.add_argument("--file",        required=True)
    a.add_argument("--license",     choices=LICENSES, default=None)
    a.add_argument("--subdir",      default="",
                   help="Sub-folder of assets/background_audio, e.g. meta_safe_music")

    e = sub.add_parser("edit", help="Change a track's description / license")
    e.add_argument("--name",        required=True)
    e.add_argument("--description", default=None)
    e.add_argument("--license",     default=None, help="YTsafe | Metasafe | TikToksafe | '' to clear")

    r = sub.add_parser("remove", help="Remove a background audio track")
    r.add_argument("--name",        required=True)
    r.add_argument("--delete-file", action="store_true", dest="delete_file")

    args = p.parse_args()

    if args.cmd == "list":
        for a in list_background_audio(assets_dir, args.license):
            print(f"  {a['name']:20}  {a.get('license') or '-':10}  {a['full_path']}  —  {a['description']}")

    elif args.cmd == "add":
        add_background_audio(assets_dir, args.name, args.description, Path(args.file),
                             license=args.license, subdir=args.subdir)
        print(f"Background audio '{args.name}' added.")

    elif args.cmd == "edit":
        data = {k: v for k, v in (("description", args.description), ("license", args.license))
                if v is not None}
        edit_background_audio(assets_dir, args.name, data)
        print(f"Background audio '{args.name}' updated.")

    elif args.cmd == "remove":
        remove_background_audio(assets_dir, args.name, delete_file=args.delete_file)
        print(f"Background audio '{args.name}' removed.")


if __name__ == "__main__":
    main()
