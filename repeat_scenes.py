"""
repeat_scenes.py
================
Shadowing helper: insert (or remove) an "intermediate" repeat scene after each
dialog line.

A repeat scene is a silent display scene that holds the dialog's image with the
subtitle STILL readable, plus a centered message (the "now repeat" cue, e.g.
"Jetzt wiederholen"). It sits between the dialog scene and the silent pause that
follows it, giving the learner a window to repeat the line out loud while they can
still see (and read) it.

The scene itself carries no message text or image of its own:

  * The message is GLOBAL — taken from config (`[repeat_prompt] text`) or a per-render
    override — and applied to every repeat scene at render time (see create_video.py).
  * The image is the previous (dialog) scene's frame, reused as the freeze-frame
    background, so no extra image is generated and create_images never touches it.

Scene shape (audio == null, image == null so the image/audio steps skip it):

    {
      "id": "<dialog_id>__repeat",
      "description": "repeat_prompt",
      "_is_repeat_prompt": true,
      "_source_scene_id": "<dialog_id>",
      "characters": [...],
      "image": null,
      "audio": null,
      "subtitle_text": "<dialog text>",
      "duration_ms": <held duration>
    }

Both functions are idempotent and safe to re-run.
"""

import json
import logging
import argparse
from pathlib import Path

from utils_config import load_config, load_project_types

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomic manifest write (temp file + rename) so an interrupted run can't corrupt it."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)


def _is_dialog(scene: dict) -> bool:
    """A spoken dialog line: TTS audio, not narration/repetition, not a reading
    sentence, not a custom intro/outro scene."""
    audio = scene.get("audio") or {}
    return (
        audio.get("type") == "tts"
        and not scene.get("_is_narration")
        and not scene.get("_is_repetition")
        and not scene.get("_reading")
        and not scene.get("_is_custom")
    )


def _repeat_duration_ms(dialog: dict, cfg: dict, factor: float = None) -> int:
    """Resolve how long the repeat scene is held.

    config `duration_ms` > 0 forces a fixed hold; 0 mirrors the dialog line's own
    duration (the natural shadowing window), multiplied by `factor` so the learner can
    get more time than the line took to speak (e.g. 1.5 = 50% longer). Falls back to
    2500 ms when the dialog has no measured duration yet (audio not generated)."""
    fixed = cfg.get("repeat_duration_ms") or 0
    if fixed > 0:
        return int(fixed)
    if factor is None:
        factor = cfg.get("repeat_duration_factor") or 1.0
    return int((dialog.get("duration_ms") or 2500) * factor)


def _type_hold_factor(manifest: dict, cfg: dict) -> float | None:
    """Per-type default hold factor (project_types.json `repeat_hold_factor`), resolving
    base_type inheritance. Returns None when the project's type doesn't define one."""
    key = (manifest.get("project_metadata") or {}).get("project_type_key")
    if not key:
        return None
    types = load_project_types(cfg["assets_dir"])
    pt = types.get(key)
    if not pt:
        return None
    base = pt.get("base_type")
    merged = {**types.get(base, {}), **pt} if base and base in types else pt
    val = merged.get("repeat_hold_factor")
    return float(val) if val is not None else None


def add_repeat_scenes(project_name: str, factor: float = None) -> dict:
    """Insert a repeat scene after every dialog line that doesn't already have one.

    `factor` multiplies the mirrored dialog length (None → config default) to set how
    long each repeat scene is held — re-running re-syncs every repeat scene to the
    current dialog duration × factor.

    Returns {"added": int, "total_repeat": int}. Idempotent: a dialog that is already
    followed by its repeat scene is left untouched apart from refreshing its hold.
    """
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # No explicit factor → use the project type's default (e.g. song_quiz = 0.7) before
    # the config-wide fallback in _repeat_duration_ms.
    if factor is None:
        factor = _type_hold_factor(manifest, cfg)

    scenes = manifest.get("scenes", [])
    out: list[dict] = []
    added = 0
    for i, scene in enumerate(scenes):
        out.append(scene)
        if not _is_dialog(scene):
            continue
        nxt = scenes[i + 1] if i + 1 < len(scenes) else None
        if nxt and nxt.get("_is_repeat_prompt") and nxt.get("_source_scene_id") == scene["id"]:
            # Already present — keep it but refresh its hold from the current dialog.
            nxt["duration_ms"] = _repeat_duration_ms(scene, cfg, factor)
            nxt["subtitle_text"] = scene.get("subtitle_text") or (scene.get("audio") or {}).get("tts_text")
            continue
        out.append({
            "id":               f"{scene['id']}__repeat",
            "description":       "repeat_prompt",
            "_is_repeat_prompt": True,
            "_source_scene_id":  scene["id"],
            "characters":        list(scene.get("characters") or []),
            "image":             None,
            "audio":             None,
            "subtitle_text":     scene.get("subtitle_text") or (scene.get("audio") or {}).get("tts_text"),
            "duration_ms":       _repeat_duration_ms(scene, cfg, factor),
        })
        added += 1

    manifest["scenes"] = out
    _write_manifest(manifest_path, manifest)
    total = sum(1 for s in out if s.get("_is_repeat_prompt"))
    logger.info("Added %d repeat scene(s); %d total in project '%s'.", added, total, project_name)
    return {"added": added, "total_repeat": total}


def remove_repeat_scenes(project_name: str) -> dict:
    """Remove every repeat scene from the manifest. Returns {"removed": int}.

    Also deletes any rendered repeat clips so they don't linger in the videos dir.
    """
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenes  = manifest.get("scenes", [])
    removed_ids = [s["id"] for s in scenes if s.get("_is_repeat_prompt")]
    manifest["scenes"] = [s for s in scenes if not s.get("_is_repeat_prompt")]
    _write_manifest(manifest_path, manifest)

    # Best-effort: drop any rendered clips for the removed scenes.
    videos_dir = project_path / "videos"
    if videos_dir.exists():
        for sid in removed_ids:
            for clip in videos_dir.rglob(f"{sid}.mp4"):
                try:
                    clip.unlink()
                except Exception:
                    pass

    logger.info("Removed %d repeat scene(s) from project '%s'.", len(removed_ids), project_name)
    return {"removed": len(removed_ids)}


def main() -> None:
    p = argparse.ArgumentParser(description="Add or remove shadowing repeat scenes.")
    p.add_argument("project_name")
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("--factor", type=float, default=None,
                   help="Multiply the mirrored dialog length for the repeat hold "
                        "(e.g. 1.5 = 50%% longer). Default: config duration_factor.")
    a = p.parse_args()
    if a.action == "add":
        print(add_repeat_scenes(a.project_name, factor=a.factor))
    else:
        print(remove_repeat_scenes(a.project_name))


if __name__ == "__main__":
    main()
