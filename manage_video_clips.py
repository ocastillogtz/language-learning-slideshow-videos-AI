"""
manage_video_clips.py
=====================
CLI and importable functions for video clip asset management.

Commands
--------
  list
  add    --name --description --file <path>
  remove --name

Usage
-----
  python manage_video_clips.py list
  python manage_video_clips.py add \\
      --name "intro_v2" \\
      --description "Updated channel intro, 4 seconds" \\
      --file /path/to/intro_v2.mp4
  python manage_video_clips.py remove --name "intro_v2"
"""

import argparse
import json
import logging
import shutil
from pathlib import Path

from dotenv import load_dotenv

from utils_config import load_config

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _clips_path(assets_dir: Path) -> Path:
    return assets_dir / "video_clips" / "video_clips.json"

def _registry_path(assets_dir: Path) -> Path:
    return assets_dir / "assets.json"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_video_clips(assets_dir: Path) -> dict:
    path = _clips_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_video_clips(assets_dir: Path, data: dict) -> None:
    path = _clips_path(assets_dir)
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
# Duration helper
# ---------------------------------------------------------------------------

def _get_duration_ms(video_path: Path) -> int | None:
    """Try to read video duration via moviepy. Returns None on failure."""
    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(str(video_path)) as clip:
            return int(clip.duration * 1000)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core functions (importable by Flask routes)
# ---------------------------------------------------------------------------

def list_video_clips(assets_dir: Path) -> list[dict]:
    return list(load_video_clips(assets_dir).values())


def add_video_clip(
    assets_dir: Path,
    name: str,
    description: str,
    source_file: Path,
) -> dict:
    clips = load_video_clips(assets_dir)
    if name in clips:
        raise ValueError(f"Video clip '{name}' already exists. Remove it first.")

    clips_dir = assets_dir / "video_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    dest = clips_dir / f"{name}.mp4"
    shutil.copy2(source_file, dest)
    rel_path = f"video_clips/{name}.mp4"

    duration_ms = _get_duration_ms(dest)

    entry = {
        "name": name,
        "description": description,
        "video_file_path": rel_path,
        "duration_ms": duration_ms,
    }
    clips[name] = entry
    save_video_clips(assets_dir, clips)

    registry = load_registry(assets_dir)
    registry.setdefault("video_clips", {})[name] = {
        "config": f"video_clips/video_clips.json#{name}"
    }
    save_registry(assets_dir, registry)

    logger.info(f"Video clip '{name}' added: {dest} ({duration_ms} ms)")
    return entry


def remove_video_clip(assets_dir: Path, name: str, delete_file: bool = False) -> None:
    clips = load_video_clips(assets_dir)
    if name not in clips:
        raise ValueError(f"Video clip '{name}' not found.")

    if delete_file:
        file_path = assets_dir / clips[name].get("video_file_path", "")
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted file: {file_path}")

    del clips[name]
    save_video_clips(assets_dir, clips)

    registry = load_registry(assets_dir)
    registry.get("video_clips", {}).pop(name, None)
    save_registry(assets_dir, registry)
    logger.info(f"Video clip '{name}' removed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    assets_dir = cfg["assets_dir"]

    p = argparse.ArgumentParser(description="Manage video clip assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all video clips")

    a = sub.add_parser("add", help="Add a video clip")
    a.add_argument("--name",        required=True)
    a.add_argument("--description", required=True)
    a.add_argument("--file",        required=True, help="Source video file path")

    r = sub.add_parser("remove", help="Remove a video clip")
    r.add_argument("--name",        required=True)
    r.add_argument("--delete-file", action="store_true", dest="delete_file",
                   help="Also delete the video file from assets/")

    args = p.parse_args()

    if args.cmd == "list":
        for c in list_video_clips(assets_dir):
            print(f"  {c['name']:20}  {c['video_file_path']}  ({c.get('duration_ms', '?')} ms)  {c['description']}")

    elif args.cmd == "add":
        add_video_clip(assets_dir, args.name, args.description, Path(args.file))
        print(f"Video clip '{args.name}' added.")

    elif args.cmd == "remove":
        remove_video_clip(assets_dir, args.name, delete_file=args.delete_file)
        print(f"Video clip '{args.name}' removed.")


if __name__ == "__main__":
    main()
