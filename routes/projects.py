import json
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, abort

import db
from core import projects_dir, get_cfg
from platform_audio import any_variant_exists

bp = Blueprint("projects", __name__, url_prefix="")


@bp.route("/project-files/<path:filepath>")
def serve_project_file(filepath):
    full = projects_dir() / filepath
    if not full.exists() or not full.is_file():
        abort(404)
    try:
        full.resolve().relative_to(projects_dir().resolve())
    except ValueError:
        abort(403)
    return send_file(full)


@bp.route("/projects")
def list_projects():
    """Project cards for the sidebar. Summaries are cached in the workspace's project
    index (data/pipeline.db) and only re-read when a manifest's mtime changes; the
    same pass records which assets each project uses ("used by" in the Assets view)."""
    try:
        pdir = projects_dir()
        if not pdir.exists():
            return jsonify([])
        ws    = get_cfg()["workspace"]
        index = db.get_project_index(ws) if ws else {}

        out, seen = [], set()
        for d in pdir.iterdir():
            mp = d / "project_manifest.json"
            if not d.is_dir() or not mp.exists():
                continue
            seen.add(d.name)
            mtime  = mp.stat().st_mtime
            cached = index.get(d.name)
            if cached and cached["mtime"] == mtime:
                summary = cached["summary"]
            else:
                try:
                    with open(mp, encoding="utf-8") as f:
                        m = json.load(f)
                    summary = _summarise_project(d, m)
                except Exception:
                    # Never let one bad manifest break the whole list
                    out.append({"name": d.name, "error": "could not parse manifest"})
                    continue
                if ws:
                    db.upsert_project_index(ws, d.name, mtime, summary, _asset_usage(m))
            # The final video can appear without the manifest changing — check live.
            summary = {**summary, "has_video": any_variant_exists(d / f"final_{d.name}.mp4")}
            out.append(summary)
        if ws:
            db.prune_project_index(ws, seen)

        # Newest first
        out.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _asset_usage(m: dict) -> list[tuple[str, str]]:
    """(kind, key) of every catalog asset a manifest references."""
    gen   = m.get("generation_config") or {}
    meta  = m.get("project_metadata") or {}
    usage = [("characters", c) for c in gen.get("characters") or [] if isinstance(c, str)]
    usage.append(("locations", gen.get("location_key") or m.get("location-key")))
    usage.append(("project_types", meta.get("project_type_key") or m.get("style")))
    # Music / branding chosen at assembly time (render_settings.<step>.*)
    for rs in (m.get("render_settings") or {}).values():
        if not isinstance(rs, dict):
            continue
        usage.append(("background_audio", rs.get("bg_audio_name")))
        for spec in (rs.get("bg_tracks") or {}).values():
            if isinstance(spec, dict):
                usage.append(("background_audio", spec.get("name")))
        usage.append(("branding_files", rs.get("branding_file")))
    return [(k, v) for k, v in usage if isinstance(v, str) and v]


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
        "visual_guidelines": gen.get("visual_guidelines") or "",
        "characters":       gen.get("characters") or [],
        "scene_count":      len(scenes),
        "has_script":       bool(tts_scenes),
        "has_audio":        any(s["audio"].get("file_path") for s in tts_scenes),
        "has_images":       bool(img_scenes),
    }


@bp.route("/projects/<name>")
def get_project(name):
    try:
        mp = projects_dir() / name / "project_manifest.json"
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
      tts_text     — override the spoken/subtitle text for a TTS scene
      subtitle_text — override the on-screen subtitle (independent of audio)
      scene_visual — English description used to (re)generate the scene image
      speaker      — change the speaker character name
      shot_type    — change shot_type (both | over_shoulder_A | over_shoulder_B)
      duration_ms  — override the duration of a silent-pause scene (audio: null)
    """
    try:
        data = request.get_json() or {}
        mp   = projects_dir() / name / "project_manifest.json"
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

        # subtitle_segments — timed lyric lines for a song slice. Each entry is
        # {text, start_ms, end_ms} with timings RELATIVE to the scene start. The
        # transcription can mis-hear words under the music, so this is the manual fix.
        if "subtitle_segments" in data:
            segs = data["subtitle_segments"]
            if not isinstance(segs, list):
                return jsonify({"error": "subtitle_segments must be a list"}), 400
            dur = scene.get("duration_ms")
            clean = []
            for seg in segs:
                if not isinstance(seg, dict):
                    return jsonify({"error": "each subtitle segment must be an object"}), 400
                try:
                    st = int(seg.get("start_ms"))
                    en = int(seg.get("end_ms"))
                except (TypeError, ValueError):
                    return jsonify({"error": "segment start_ms/end_ms must be integers"}), 400
                if en < st:
                    return jsonify({"error": "segment end_ms must be >= start_ms"}), 400
                if dur:
                    st = max(0, min(st, dur))
                    en = max(0, min(en, dur))
                clean.append({"text": (seg.get("text") or "").strip(),
                              "start_ms": st, "end_ms": en})
            scene["subtitle_segments"] = clean
            # Keep subtitle_text (reference/editing) in sync with the edited lines.
            scene["subtitle_text"] = " ".join(s["text"] for s in clean if s["text"]).strip() or None
            # Drop the stale rendered clip so a re-render picks up the new lyrics even
            # without the "overwrite" toggle (the per-scene video regen also works).
            clip = projects_dir() / name / "videos" / f"{scene_id}.mp4"
            if clip.exists():
                clip.unlink()

        # scene_visual — English action description used for image (re)generation.
        # The image prompt embeds the visual at script time, so rewrite the stored
        # prompt too — otherwise a later image regen still uses the old visual.
        if "scene_visual" in data:
            scene["scene_visual"] = (data["scene_visual"] or "").strip()
            img = scene.get("image")
            # The shared podcast studio prompt has no per-line action to swap.
            if scene["scene_visual"] and img and img.get("prompt_to_create") \
                    and img.get("reference_type") != "podcast_studio":
                from create_script import update_prompt_scene_visual
                img["prompt_to_create"] = update_prompt_scene_visual(
                    img["prompt_to_create"], scene["scene_visual"])

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
                chars_data = load_new_characters(get_cfg()["assets_dir"])
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


@bp.route("/projects/<name>/scenes/insert", methods=["POST"])
def insert_scene(name: str):
    """Insert an empty custom scene anywhere in the timeline.

    Body: {"before_id": "<scene_id>"} — insert immediately before that scene;
    omit / null to append at the very end. The scene is created empty (same shape
    as a normal TTS scene) so the per-scene Edit / Image / Audio tools work on it.
    """
    try:
        data      = request.get_json(silent=True) or {}
        before_id = (data.get("before_id") or "").strip() or None
        from custom_scenes import insert_custom_scene
        return jsonify(insert_custom_scene(name, before_id=before_id))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/scenes/<scene_id>", methods=["DELETE"])
def delete_scene_route(name: str, scene_id: str):
    """Delete a scene by id, along with its generated image, audio and clips."""
    try:
        from custom_scenes import delete_scene
        return jsonify(delete_scene(name, scene_id))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
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
        visual_guidelines = data.get("visual_guidelines", "").strip()

        # Song and promotional projects gather their real inputs in the Build step
        # (the song's audio file, the promo character/line), so the scene description
        # here is optional for them.
        context_optional = project_type_key in ("song", "promotional")
        if not name:
            return jsonify({"error": "project_name is required"}), 400
        if not context and not context_optional:
            return jsonify({"error": "project_name and context are required"}), 400

        from create_project import create_project as _create
        _create(name, project_type_key, context, learning_points, level, visual_guidelines)
        return jsonify({"message": "Created", "project_name": name})
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


