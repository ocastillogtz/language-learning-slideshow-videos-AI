"""
reconcile.py
============
Repair a project manifest after an interrupted run.

create_images / create_audio fill scene.image.file_path / scene.audio.file_path
and save the manifest. If the process dies mid-run, files may exist on disk while
the manifest still shows them as missing. reconcile_media_paths() scans the
project's images/ and audio/ folders and back-fills any file_path that points to
a file which actually exists, so the UI shows what was already produced.

It also back-fills a missing audio duration_ms (measured from the file), because
a recovered TTS scene with no duration makes create_video fall back to a 3 s
default that is usually longer than the real clip — which then crashes the writer
with "Accessing time t=… with clip duration=…".

Only fills in missing data (never deletes), and only writes the manifest if
something changed. Cheap (pure filesystem checks; durations are only measured for
scenes that are actually missing one) — safe to call on every load.
"""

import json
import logging
from pathlib import Path

from utils_config import load_config

logger = logging.getLogger(__name__)


def _measure_audio_ms(path: Path) -> int | None:
    """Best-effort duration of an audio file in ms (matches create_audio's pydub
    measurement). Returns None if it can't be read, so reconcile never crashes."""
    try:
        from pydub import AudioSegment
        return len(AudioSegment.from_file(str(path)))
    except Exception as e:
        logger.warning("Could not measure %s: %s", path, e)
        return None


def reconcile_media_paths(project_name: str) -> dict:
    cfg = load_config()
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        return {"images_added": 0, "audio_added": 0, "durations_added": 0, "changed": False}

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    images_added = 0
    audio_added = 0
    durations_added = 0

    for scene in manifest.get("scenes", []):
        sid = scene.get("id")
        if not sid:
            continue

        img = scene.get("image")
        if isinstance(img, dict) and not img.get("file_path"):
            cand = project_path / "images" / f"{sid}.png"
            if cand.exists() and cand.stat().st_size > 0:
                img["file_path"] = f"images/{sid}.png"
                images_added += 1

        au = scene.get("audio")
        if isinstance(au, dict) and au.get("type") == "tts":
            cand = project_path / "audio" / f"{sid}.mp3"
            if not au.get("file_path") and cand.exists() and cand.stat().st_size > 0:
                au["file_path"] = f"audio/{sid}.mp3"
                audio_added += 1

            # Back-fill a missing duration so create_video doesn't fall back to its
            # 3 s default (longer than the real clip -> writer crash).
            if au.get("file_path") and not au.get("duration_ms"):
                fp = project_path / au["file_path"]
                if fp.exists() and fp.stat().st_size > 0:
                    dur = _measure_audio_ms(fp)
                    if dur:
                        au["duration_ms"] = dur
                        scene["duration_ms"] = dur
                        durations_added += 1

    changed = bool(images_added or audio_added or durations_added)
    if changed:
        tmp = manifest_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        tmp.replace(manifest_path)
        logger.info("reconcile %s: +%d images, +%d audio, +%d durations",
                    project_name, images_added, audio_added, durations_added)

    return {"images_added": images_added, "audio_added": audio_added,
            "durations_added": durations_added, "changed": changed}


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else None
    if not name:
        print("usage: python reconcile.py <project_name>")
    else:
        print(json.dumps(reconcile_media_paths(name), indent=2))
