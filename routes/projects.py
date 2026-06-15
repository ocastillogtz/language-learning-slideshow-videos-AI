import json
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, abort

from core import PROJECTS_DIR, cfg

bp = Blueprint("projects", __name__, url_prefix="")


@bp.route("/project-files/<path:filepath>")
def serve_project_file(filepath):
    full = PROJECTS_DIR / filepath
    if not full.exists() or not full.is_file():
        abort(404)
    try:
        full.resolve().relative_to(PROJECTS_DIR.resolve())
    except ValueError:
        abort(403)
    return send_file(full)


@bp.route("/projects")
def list_projects():
    try:
        if not PROJECTS_DIR.exists():
            return jsonify([])

        projects = []
        for d in PROJECTS_DIR.iterdir():
            if not d.is_dir():
                continue
            mp = d / "project_manifest.json"
            if not mp.exists():
                continue
            try:
                with open(mp, encoding="utf-8") as f:
                    m = json.load(f)
            except Exception:
                continue  # skip unreadable manifests
            projects.append((d, m))

        # Sort newest first — handle both old ("project.created_at") and new ("project_metadata.creation_date") schemas
        def _sort_key(pair):
            _, m = pair
            return (
                m.get("project_metadata", {}).get("creation_date")
                or m.get("project", {}).get("created_at")
                or ""
            )

        out = []
        for d, m in sorted(projects, key=_sort_key, reverse=True):
            try:
                out.append(_summarise_project(d, m))
            except Exception:
                # Never let one bad manifest break the whole list
                out.append({"name": d.name, "error": "could not parse manifest"})

        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _summarise_project(d: Path, m: dict) -> dict:
    """Build the project summary card from a manifest (new or old schema)."""
    meta   = m.get("project_metadata") or {}
    gen    = m.get("generation_config") or {}
    vi     = m.get("video_info") or {}
    scenes = m.get("scenes") or []

    tts_scenes = [
        s for s in scenes
        if isinstance(s.get("audio"), dict) and s["audio"].get("type") == "tts"
    ]
    img_scenes = [
        s for s in scenes
        if isinstance(s.get("image"), dict) and s["image"].get("file_path")
    ]

    return {
        "name":             d.name,
        "created_at":       meta.get("creation_date") or (m.get("project") or {}).get("created_at"),
        "title":            vi.get("title") or m.get("title"),
        "project_type_key": meta.get("project_type_key") or m.get("style"),
        "location_key":     gen.get("location_key") or m.get("location-key"),
        "characters":       gen.get("characters") or [],
        "scene_count":      len(scenes),
        "has_script":       bool(tts_scenes),
        "has_audio":        any(s["audio"].get("file_path") for s in tts_scenes),
        "has_images":       bool(img_scenes),
        "has_video":        (d / f"final_{d.name}.mp4").exists(),
    }


@bp.route("/projects/<name>")
def get_project(name):
    try:
        mp = PROJECTS_DIR / name / "project_manifest.json"
        if not mp.exists():
            return jsonify({"error": "Not found"}), 404
        # Self-heal: back-fill image/audio paths for files that exist on disk but
        # were never written to the manifest (e.g. an interrupted generation run).
        try:
            from reconcile import reconcile_media_paths
            reconcile_media_paths(name)
        except Exception as _e:
            pass
        with open(mp, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/reconcile", methods=["POST"])
def reconcile_project(name):
    """Scan images/ and audio/ and back-fill any missing file paths into the manifest."""
    try:
        from reconcile import reconcile_media_paths
        return jsonify(reconcile_media_paths(name))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/scenes/<scene_id>", methods=["PATCH"])
def update_scene(name: str, scene_id: str):
    """
    Patch writable fields on a scene by scene_id.

    Accepted JSON fields (all optional):
      tts_text    — override the spoken/subtitle text for a TTS scene
      speaker     — change the speaker character name
      shot_type   — change shot_type (both | over_shoulder_A | over_shoulder_B)
      duration_ms — override the duration of a silent-pause scene (audio: null)
    """
    try:
        data = request.get_json() or {}
        mp   = PROJECTS_DIR / name / "project_manifest.json"
        if not mp.exists():
            return jsonify({"error": "Project not found"}), 404

        with open(mp, encoding="utf-8") as f:
            m = json.load(f)

        scene = next((s for s in m.get("scenes", []) if s["id"] == scene_id), None)
        if not scene:
            return jsonify({"error": f"Scene '{scene_id}' not found"}), 404

        # subtitle_text — update the on-screen subtitle (independent of audio)
        if "subtitle_text" in data:
            scene["subtitle_text"] = data["subtitle_text"].strip()

        # tts_text — update the spoken text on TTS audio scenes
        if "tts_text" in data:
            audio = scene.get("audio") or {}
            if audio.get("type") != "tts":
                return jsonify({"error": "tts_text can only be set on TTS scenes"}), 400
            audio["tts_text"] = data["tts_text"].strip()
            # Also sync subtitle_text if not set independently
            if "subtitle_text" not in data:
                scene["subtitle_text"] = data["tts_text"].strip()
            # Clear audio file so it will be regenerated
            audio["file_path"]   = None
            audio["duration_ms"] = None
            scene["duration_ms"] = None

        # speaker
        if "speaker" in data:
            gen_chars = m.get("generation_config", {}).get("characters", [])
            if data["speaker"] not in gen_chars:
                return jsonify({"error": f"speaker must be one of {gen_chars}"}), 400
            scene["characters"] = [data["speaker"]]
            audio = scene.get("audio") or {}
            if audio.get("type") == "tts":
                from utils_config import load_new_characters
                chars_data = load_new_characters(cfg["assets_dir"])
                if data["speaker"] in chars_data:
                    audio["voice_id"] = chars_data[data["speaker"]].get("voice_id", audio.get("voice_id"))

        # shot_type
        if "shot_type" in data:
            valid = {"both", "over_shoulder_A", "over_shoulder_B"}
            if data["shot_type"] not in valid:
                return jsonify({"error": f"shot_type must be one of {sorted(valid)}"}), 400
            scene["shot_type"] = data["shot_type"]

        # duration_ms — for silent-pause scenes (audio: null)
        if "duration_ms" in data:
            ms = data["duration_ms"]
            try:
                ms = int(ms)
            except (TypeError, ValueError):
                return jsonify({"error": "duration_ms must be an integer"}), 400
            if ms < 0 or ms > 10000:
                return jsonify({"error": "duration_ms must be between 0 and 10000"}), 400
            scene["duration_ms"] = ms

        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)

        return jsonify({"message": "Scene updated", "scene": scene})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/create_project", methods=["POST"])
def create_project():
    try:
        data             = request.get_json() or {}
        name             = data.get("project_name", "").strip().replace(" ", "_")
        project_type_key = data.get("project_type_key", "shadowing").strip()
        context          = data.get("context", data.get("scene", "")).strip()
        learning_points  = data.get("learning_points", data.get("learning", "")).strip()
        level            = data.get("level", "").strip() or None

        if not name or not context:
            return jsonify({"error": "project_name and context are required"}), 400

        from create_project import create_project as _create
        _create(name, project_type_key, context, learning_points, level)
        return jsonify({"message": "Created", "project_name": name})
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


