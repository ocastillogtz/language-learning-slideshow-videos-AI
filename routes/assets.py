"""
routes/assets.py
================
REST API endpoints for all asset types.

Characters
  GET  /assets/characters                  → list all characters (full data)
  POST /assets/characters                  → add character
  PUT  /assets/characters/<name>           → edit character
  DELETE /assets/characters/<name>         → remove character
  POST /assets/characters/<name>/generate-art → generate artwork via fal.ai

Locations
  GET  /assets/locations                   → list all locations (flat, includes sub_locations)
  POST /assets/locations                   → add location
  PUT  /assets/locations/<key>             → edit location
  DELETE /assets/locations/<key>           → remove location
  POST /assets/locations/<key>/generate-art → generate background art via fal.ai

Project Types
  GET  /assets/project-types               → list all project types
  POST /assets/project-types               → add project type
  PUT  /assets/project-types/<key>         → edit project type
  DELETE /assets/project-types/<key>       → remove project type

Video Clips
  GET  /assets/video-clips                 → list all video clips
  POST /assets/video-clips                 → add video clip
  PUT  /assets/video-clips/<key>           → edit video clip
  DELETE /assets/video-clips/<key>         → remove video clip

Background Audio
  GET  /assets/background-audio            → list all background audio tracks
  POST /assets/background-audio            → add track
  PUT  /assets/background-audio/<key>      → edit track
  DELETE /assets/background-audio/<key>   → remove track

SFX
  GET  /assets/sfx                         → list all SFX
  POST /assets/sfx                         → add SFX
  PUT  /assets/sfx/<key>                   → edit SFX
  DELETE /assets/sfx/<key>                 → remove SFX
"""

import os
from flask import Blueprint, jsonify, request, send_file, abort
from core import cfg, run_job

bp = Blueprint("assets", __name__, url_prefix="")

ASSETS_DIR = cfg["assets_dir"]

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# =============================================================================
# ASSET FILE SERVING
# =============================================================================

@bp.route("/asset-files/<path:filepath>")
def serve_asset_file(filepath):
    """Serve a file from the assets directory (used for character reference images, etc.)."""
    full = ASSETS_DIR / filepath
    try:
        full.resolve().relative_to(ASSETS_DIR.resolve())
    except ValueError:
        abort(403)
    if not full.exists() or not full.is_file():
        abort(404)
    return send_file(full)


# =============================================================================
# CHARACTERS
# =============================================================================

@bp.route("/assets/characters")
def list_characters():
    try:
        from manage_characters import load_characters
        return jsonify(load_characters(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters", methods=["POST"])
def add_character():
    try:
        data = request.get_json() or {}
        name            = (data.get("name") or "").strip()
        voice_id        = (data.get("voice_id") or "").strip()
        fixed_desc      = (data.get("fixed_description") or "").strip()
        variable_desc   = (data.get("variable_description") or "").strip()
        height          = data.get("height_cm")
        ref_desc        = (data.get("ref_desc") or "").strip() or None

        if not name or not voice_id or not fixed_desc or not variable_desc:
            return jsonify({"error": "name, voice_id, fixed_description, variable_description required"}), 400

        from manage_characters import add_character as _add
        _add(ASSETS_DIR, name, voice_id, fixed_desc, variable_desc,
             height_cm=int(height) if height else None,
             ref_desc=ref_desc)
        return jsonify({"message": f"Character '{name}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>", methods=["PUT"])
def edit_character(name: str):
    try:
        data = request.get_json() or {}
        from manage_characters import edit_character as _edit
        _edit(
            ASSETS_DIR, name,
            voice_id        = data.get("voice_id"),
            fixed_description  = data.get("fixed_description"),
            variable_description = data.get("variable_description"),
            height_cm       = data.get("height_cm"),
            ref_desc        = data.get("ref_desc"),
        )
        return jsonify({"message": f"Character '{name}' updated"})
    except KeyError:
        return jsonify({"error": f"Character '{name}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>", methods=["DELETE"])
def remove_character(name: str):
    try:
        from manage_characters import remove_character as _remove
        _remove(ASSETS_DIR, name)
        return jsonify({"message": f"Character '{name}' removed"})
    except KeyError:
        return jsonify({"error": f"Character '{name}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/generate-art", methods=["POST"])
def generate_character_art(name: str):
    try:
        from manage_characters import generate_character_art as _gen
        run_job("assets", f"char_art_{name}", _gen, ASSETS_DIR, name)
        return jsonify({"message": f"Art generation started for '{name}'"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/upload-reference", methods=["POST"])
def upload_character_reference(name: str):
    """
    Upload a reference drawing for a character.
    Accepts multipart/form-data with a 'file' field (PNG, JPG, WEBP).
    Saves to assets/characters/<name>/ref_drawing.<ext> and updates characters.json.
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file field in request"}), 400

        f    = request.files["file"]
        ext  = os.path.splitext(f.filename or "")[1].lower() or ".png"
        if ext not in ALLOWED_IMAGE_EXTS:
            return jsonify({"error": f"Unsupported file type '{ext}'. Use PNG, JPG or WEBP."}), 400

        image_bytes = f.read()
        if not image_bytes:
            return jsonify({"error": "Uploaded file is empty"}), 400

        from manage_characters import save_reference_image
        rel_path = save_reference_image(ASSETS_DIR, name, image_bytes, ext)
        return jsonify({"message": "Reference drawing saved", "file_path": rel_path})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# LOCATIONS
# =============================================================================

@bp.route("/assets/locations")
def list_locations():
    try:
        from utils_config import get_new_locations_flat
        return jsonify(get_new_locations_flat(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/locations", methods=["POST"])
def add_location():
    try:
        data             = request.get_json() or {}
        key              = (data.get("key") or "").strip()
        description      = (data.get("description") or "").strip()
        creation_prompt  = (data.get("creation_prompt") or "").strip()
        eligible_chars   = data.get("eligible_characters") or []

        if not key or not description or not creation_prompt:
            return jsonify({"error": "key, description, creation_prompt required"}), 400

        from manage_locations import add_location as _add
        _add(ASSETS_DIR, key, description, creation_prompt, eligible_chars)
        return jsonify({"message": f"Location '{key}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/locations/<key>", methods=["PUT"])
def edit_location(key: str):
    try:
        data = request.get_json() or {}
        from manage_locations import edit_location as _edit
        _edit(
            ASSETS_DIR, key,
            description     = data.get("description"),
            creation_prompt = data.get("creation_prompt"),
        )
        return jsonify({"message": f"Location '{key}' updated"})
    except KeyError:
        return jsonify({"error": f"Location '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/locations/<key>", methods=["DELETE"])
def remove_location(key: str):
    try:
        from manage_locations import remove_location as _remove
        _remove(ASSETS_DIR, key)
        return jsonify({"message": f"Location '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"Location '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/locations/<key>/generate-art", methods=["POST"])
def generate_location_art(key: str):
    try:
        from manage_locations import generate_location_art as _gen
        run_job("assets", f"loc_art_{key}", _gen, ASSETS_DIR, key)
        return jsonify({"message": f"Art generation started for location '{key}'"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# PROJECT TYPES
# =============================================================================

@bp.route("/assets/project-types")
def list_project_types():
    try:
        from utils_config import load_project_types
        return jsonify(load_project_types(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/project-types", methods=["POST"])
def add_project_type():
    try:
        data = request.get_json() or {}
        key  = (data.get("key") or "").strip()
        if not key:
            return jsonify({"error": "key required"}), 400

        from manage_project_types import add_project_type as _add
        _add(ASSETS_DIR, key, data)
        return jsonify({"message": f"Project type '{key}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/project-types/<key>", methods=["PUT"])
def edit_project_type(key: str):
    try:
        data = request.get_json() or {}
        from manage_project_types import edit_project_type as _edit
        _edit(ASSETS_DIR, key, data)
        return jsonify({"message": f"Project type '{key}' updated"})
    except KeyError:
        return jsonify({"error": f"Project type '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/project-types/<key>", methods=["DELETE"])
def remove_project_type(key: str):
    try:
        from manage_project_types import remove_project_type as _remove
        _remove(ASSETS_DIR, key)
        return jsonify({"message": f"Project type '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"Project type '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# VIDEO CLIPS
# =============================================================================

@bp.route("/assets/video-clips")
def list_video_clips():
    try:
        from utils_config import load_video_clips
        return jsonify(load_video_clips(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips", methods=["POST"])
def add_video_clip():
    try:
        data = request.get_json() or {}
        key  = (data.get("key") or "").strip()
        if not key:
            return jsonify({"error": "key required"}), 400
        from manage_video_clips import add_video_clip as _add
        _add(ASSETS_DIR, key, data)
        return jsonify({"message": f"Video clip '{key}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips/<key>", methods=["PUT"])
def edit_video_clip(key: str):
    try:
        data = request.get_json() or {}
        from manage_video_clips import edit_video_clip as _edit
        _edit(ASSETS_DIR, key, data)
        return jsonify({"message": f"Video clip '{key}' updated"})
    except KeyError:
        return jsonify({"error": f"Video clip '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips/<key>", methods=["DELETE"])
def remove_video_clip(key: str):
    try:
        from manage_video_clips import remove_video_clip as _remove
        _remove(ASSETS_DIR, key)
        return jsonify({"message": f"Video clip '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"Video clip '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# BACKGROUND AUDIO
# =============================================================================

@bp.route("/assets/background-audio")
def list_background_audio():
    try:
        from utils_config import load_background_audio_index
        return jsonify(load_background_audio_index(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio", methods=["POST"])
def add_background_audio():
    try:
        data = request.get_json() or {}
        key  = (data.get("key") or "").strip()
        if not key:
            return jsonify({"error": "key required"}), 400
        from manage_background_audio import add_background_audio as _add
        _add(ASSETS_DIR, key, data)
        return jsonify({"message": f"Background audio '{key}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>", methods=["PUT"])
def edit_background_audio(key: str):
    try:
        data = request.get_json() or {}
        from manage_background_audio import edit_background_audio as _edit
        _edit(ASSETS_DIR, key, data)
        return jsonify({"message": f"Background audio '{key}' updated"})
    except KeyError:
        return jsonify({"error": f"Background audio '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>", methods=["DELETE"])
def remove_background_audio(key: str):
    try:
        from manage_background_audio import remove_background_audio as _remove
        _remove(ASSETS_DIR, key)
        return jsonify({"message": f"Background audio '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"Background audio '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SFX
# =============================================================================

@bp.route("/assets/sfx")
def list_sfx():
    try:
        from utils_config import load_sfx_index
        return jsonify(load_sfx_index(ASSETS_DIR))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx", methods=["POST"])
def add_sfx():
    try:
        data = request.get_json() or {}
        key  = (data.get("key") or "").strip()
        if not key:
            return jsonify({"error": "key required"}), 400
        from manage_sfx import add_sfx as _add
        _add(ASSETS_DIR, key, data)
        return jsonify({"message": f"SFX '{key}' added"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx/<key>", methods=["PUT"])
def edit_sfx(key: str):
    try:
        data = request.get_json() or {}
        from manage_sfx import edit_sfx as _edit
        _edit(ASSETS_DIR, key, data)
        return jsonify({"message": f"SFX '{key}' updated"})
    except KeyError:
        return jsonify({"error": f"SFX '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx/<key>", methods=["DELETE"])
def remove_sfx(key: str):
    try:
        from manage_sfx import remove_sfx as _remove
        _remove(ASSETS_DIR, key)
        return jsonify({"message": f"SFX '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"SFX '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
