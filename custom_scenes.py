"""
custom_scenes.py
================
Insert (or remove) an empty custom scene at the very beginning or the very end
of the video.

The scene is created EMPTY but with the full shape of a normal TTS scene, so the
existing per-scene tools work on it directly from the Generated Items tab:

  * "Edit" — fill in the German text (tts_text) and the visual description.
  * "Re-generate Image" — the image prompt starts as a copy of the neighboring
    scene's prompt (same art style); edit the Action part, then generate.
  * The per-scene audio button synthesizes the line once text has been added.
  * The Video step renders it like any other scene once audio/image exist.

Scene shape:

    {
      "id": "custom_start" | "custom_end",
      "description": "custom_start" | "custom_end",
      "_is_custom": true,
      "characters": [],
      "scene_visual": "",
      "image":  {"file_path": null, "prompt_to_create": "<copied template>",
                 "reference_type": "none"},
      "audio":  {"type": "tts", "file_path": null, "tts_text": "",
                 "voice_id": "<default voice>", "duration_ms": null},
      "subtitle_text": "",
      "duration_ms": null
    }

While the scene is still empty the pipeline steps skip it (empty tts_text /
empty prompt), so a full Audio or Images run never chokes on it.

Both functions are idempotent and safe to re-run.
"""

import json
import uuid
import logging
import argparse
from pathlib import Path

from utils_config import load_config, load_new_characters

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _custom_id(position: str) -> str:
    return f"custom_{position}"


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomic manifest write (temp file + rename) so an interrupted run can't corrupt it."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)


def _load_manifest(project_name: str):
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return cfg, project_path, manifest_path, manifest


def _default_voice(manifest: dict, chars_data: dict) -> str:
    """Voice for the new scene: first project character with a voice, else the
    Narrator asset, else whatever the nearest TTS scene uses."""
    gen = manifest.get("generation_config", {})
    for nm in (gen.get("characters") or []):
        v = (chars_data.get(nm) or {}).get("voice_id")
        if v:
            return v
    v = (chars_data.get("Narrator") or {}).get("voice_id")
    if v:
        return v
    for s in manifest.get("scenes", []):
        a = s.get("audio") or {}
        if a.get("type") == "tts" and a.get("voice_id"):
            return a["voice_id"]
    return ""


def _template_prompt(manifest: dict, position: str) -> str:
    """Start the image prompt as a copy of the neighboring scene's prompt so the
    art style tokens carry over; the user edits the Action part before generating."""
    scenes = manifest.get("scenes", [])
    ordered = scenes if position == "start" else list(reversed(scenes))
    for s in ordered:
        p = ((s.get("image") or {}).get("prompt_to_create") or "").strip()
        if p:
            return p
    return ""


def _new_custom_id(scenes: list) -> str:
    """A unique custom-scene id that doesn't collide with any existing scene."""
    existing = {s.get("id") for s in scenes}
    while True:
        sid = f"custom_{uuid.uuid4().hex[:8]}"
        if sid not in existing:
            return sid


def _make_custom_scene(cfg, manifest: dict, sid: str, prompt_seed: str) -> dict:
    """Build the empty-custom-scene dict shared by the start/end and the
    insert-anywhere paths. Shape matches a normal TTS scene so the existing
    per-scene tools (Edit / Re-generate Image / Audio) work on it directly."""
    chars_data = load_new_characters(cfg["assets_dir"])
    return {
        "id":            sid,
        "description":   sid,
        "_is_custom":    True,
        "characters":    [],
        "scene_visual":  "",
        "image": {
            "file_path":        None,
            "prompt_to_create": prompt_seed,
            "reference_type":   "none",
        },
        "audio": {
            "type":        "tts",
            "file_path":   None,
            "tts_text":    "",
            "voice_id":    _default_voice(manifest, chars_data),
            "duration_ms": None,
        },
        "subtitle_text": "",
        "duration_ms":   None,
    }


def add_custom_scene(project_name: str, position: str) -> dict:
    """Insert an empty custom scene at `position` ("start" | "end").

    Returns {"id": str, "created": bool}. Idempotent: if the scene already
    exists nothing changes.
    """
    if position not in ("start", "end"):
        raise ValueError("position must be 'start' or 'end'")

    cfg, project_path, manifest_path, manifest = _load_manifest(project_name)
    scenes = manifest.get("scenes", [])
    sid    = _custom_id(position)

    if any(s.get("id") == sid for s in scenes):
        logger.info("Custom scene '%s' already exists in project '%s'.", sid, project_name)
        return {"id": sid, "created": False}

    scene = _make_custom_scene(cfg, manifest, sid, _template_prompt(manifest, position))
    if position == "start":
        scenes.insert(0, scene)
    else:
        scenes.append(scene)

    manifest["scenes"] = scenes
    _write_manifest(manifest_path, manifest)
    logger.info("Custom scene '%s' added to project '%s'.", sid, project_name)
    return {"id": sid, "created": True}


def insert_custom_scene(project_name: str, before_id: str = None) -> dict:
    """Insert an empty custom scene anywhere in the timeline.

    `before_id` — insert immediately BEFORE the scene with this id. When None
    (or the id isn't found) the scene is appended at the very end.

    The image prompt is seeded from the nearest neighbouring scene's prompt
    (searching backward first, then forward) so the art-style tokens carry over.

    Returns {"id": str, "created": True, "index": int}.
    """
    cfg, project_path, manifest_path, manifest = _load_manifest(project_name)
    scenes = manifest.get("scenes", [])

    if before_id:
        idx = next((i for i, s in enumerate(scenes) if s.get("id") == before_id), len(scenes))
    else:
        idx = len(scenes)

    # Seed the image prompt from the closest neighbour that has one.
    seed = ""
    for s in list(reversed(scenes[:idx])) + scenes[idx:]:
        p = ((s.get("image") or {}).get("prompt_to_create") or "").strip()
        if p:
            seed = p
            break

    sid   = _new_custom_id(scenes)
    scene = _make_custom_scene(cfg, manifest, sid, seed)
    scenes.insert(idx, scene)

    manifest["scenes"] = scenes
    _write_manifest(manifest_path, manifest)
    logger.info("Custom scene '%s' inserted at index %d in project '%s'.", sid, idx, project_name)
    return {"id": sid, "created": True, "index": idx}


def delete_scene(project_name: str, scene_id: str) -> dict:
    """Remove ANY scene by id and delete its generated image, audio and clips.

    Returns {"removed": int, "id": str}. Idempotent: removing a missing id is a
    no-op that returns removed=0.
    """
    cfg, project_path, manifest_path, manifest = _load_manifest(project_name)
    scenes = manifest.get("scenes", [])

    if not any(s.get("id") == scene_id for s in scenes):
        logger.info("Scene '%s' not found in project '%s'.", scene_id, project_name)
        return {"removed": 0, "id": scene_id}

    manifest["scenes"] = [s for s in scenes if s.get("id") != scene_id]
    _write_manifest(manifest_path, manifest)
    _delete_artifacts(project_path, scene_id)

    logger.info("Deleted scene '%s' from project '%s'.", scene_id, project_name)
    return {"removed": 1, "id": scene_id}


def remove_custom_scene(project_name: str, position: str) -> dict:
    """Remove the custom scene at `position` ("start" | "end" | "all").

    Returns {"removed": int}. Also deletes the scene's generated image, audio
    and any rendered clips so they don't linger in the project.
    """
    if position not in ("start", "end", "all"):
        raise ValueError("position must be 'start', 'end' or 'all'")
    ids = [_custom_id("start"), _custom_id("end")] if position == "all" else [_custom_id(position)]

    cfg, project_path, manifest_path, manifest = _load_manifest(project_name)
    scenes  = manifest.get("scenes", [])
    removed = [s["id"] for s in scenes if s.get("_is_custom") and s.get("id") in ids]
    manifest["scenes"] = [s for s in scenes if not (s.get("_is_custom") and s.get("id") in ids)]
    _write_manifest(manifest_path, manifest)

    for sid in removed:
        _delete_artifacts(project_path, sid)

    logger.info("Removed %d custom scene(s) from project '%s'.", len(removed), project_name)
    return {"removed": len(removed)}


def _delete_artifacts(project_path: Path, scene_id: str) -> None:
    """Best-effort: drop the scene's generated image, audio and rendered clips."""
    for p in (project_path / "images" / f"{scene_id}.png",
              project_path / "audio" / f"{scene_id}.mp3"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    videos_dir = project_path / "videos"
    if videos_dir.exists():
        for clip in videos_dir.rglob(f"{scene_id}.mp4"):
            try:
                clip.unlink()
            except Exception:
                pass


def main() -> None:
    p = argparse.ArgumentParser(description="Add or remove an empty custom scene "
                                            "at the start or end of the video.")
    p.add_argument("project_name")
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("position", choices=["start", "end", "all"],
                   help="'all' is only valid with the remove action.")
    a = p.parse_args()
    if a.action == "add":
        if a.position == "all":
            p.error("position 'all' is only valid with the remove action")
        print(add_custom_scene(a.project_name, a.position))
    else:
        print(remove_custom_scene(a.project_name, a.position))


if __name__ == "__main__":
    main()
