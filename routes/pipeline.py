from flask import Blueprint, request, jsonify
from core import run_job, get_job

bp = Blueprint("pipeline", __name__, url_prefix="")


@bp.route("/projects/<name>/status/<step>")
def job_status(name, step):
    return jsonify(get_job(name, step))


@bp.route("/projects/<name>/run/script", methods=["POST"])
def run_script(name):
    try:
        data             = request.get_json() or {}
        char_a           = (data.get("char_a") or "").strip()
        char_b           = (data.get("char_b") or "").strip()
        location_key     = (data.get("location_key") or "").strip() or None
        project_type_key = (data.get("project_type_key") or "story").strip()
        prompt_override  = (data.get("prompt_override") or "").strip() or None
        words            = data.get("words") or None   # list[str] for word_learning type
        raw_count        = data.get("dialog_count")
        dialog_count     = int(raw_count) if raw_count not in (None, "") else None
        if not char_a or not char_b:
            return jsonify({"error": "char_a and char_b are required"}), 400
        from create_script import create_script
        run_job(name, "script", create_script, name,
                char_a, char_b, location_key,
                project_type_key=project_type_key,
                prompt_override=prompt_override,
                words=words,
                dialog_count=dialog_count)
        return jsonify({"message": "Script generation started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/audio", methods=["POST"])
def run_audio(name):
    try:
        from create_audio import create_audio
        run_job(name, "audio", create_audio, name)
        return jsonify({"message": "Audio generation started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/images", methods=["POST"])
def run_images(name):
    try:
        data = request.get_json() or {}
        overwrite         = bool(data.get("overwrite", False))
        ignore_cache      = bool(data.get("ignore_cache", False))
        use_location_ref  = bool(data.get("use_location_ref", True))
        from create_images import create_images
        run_job(name, "images", create_images, name, overwrite, ignore_cache,
                use_location_ref=use_location_ref)
        return jsonify({"message": "Image generation started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/audio_scene", methods=["POST"])
def run_audio_scene(name):
    try:
        data     = request.get_json() or {}
        scene_id = data.get("scene_id", "").strip()
        if not scene_id:
            return jsonify({"error": "scene_id required"}), 400
        from create_audio import create_audio_single
        step_key = "audio_" + scene_id
        run_job(name, step_key, create_audio_single, name, scene_id)
        return jsonify({"message": "Audio regeneration started", "step_key": step_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/image_scene", methods=["POST"])
def run_image_scene(name):
    try:
        data                = request.get_json() or {}
        scene_id            = data.get("scene_id", "").strip()
        prompt_override     = data.get("prompt_override", "").strip() or None
        use_location_ref    = bool(data.get("use_location_ref", True))
        characters_override = data.get("characters_override") or None  # "none"|"single_speaker"|"both"
        if not scene_id:
            return jsonify({"error": "scene_id required"}), 400
        from create_images import create_image_single
        step_key = "image_" + scene_id
        run_job(name, step_key, create_image_single, name, scene_id,
                prompt_override=prompt_override, use_location_ref=use_location_ref,
                characters_override=characters_override)
        return jsonify({"message": "Image regeneration started", "step_key": step_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/video", methods=["POST"])
def run_video(name):
    try:
        data = request.get_json() or {}
        overwrite           = bool(data.get("overwrite", False))
        annotated_subtitles = bool(data.get("annotated_subtitles", False))
        footnote            = str(data.get("footnote", "")).strip()
        raw_pause           = data.get("inter_pause_ms")
        inter_pause_ms      = int(raw_pause) if raw_pause not in (None, "") else None
        from create_video import create_videos
        run_job(name, "video", create_videos, name, overwrite, annotated_subtitles, footnote,
                inter_pause_ms)
        return jsonify({"message": "Video rendering started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/assemble", methods=["POST"])
def run_assemble(name):
    try:
        data          = request.get_json() or {}
        bg_audio_name = data.get("bg_audio_name", "office").strip()
        overwrite     = bool(data.get("overwrite", False))
        raw_speed     = data.get("speed_factor")
        speed_factor  = float(raw_speed) if raw_speed not in (None, "") else None
        branding_file = data.get("branding_file", "").strip() or None
        branding_mode = data.get("branding_mode", "none").strip() or "none"
        if branding_mode not in ("none", "intro", "outro", "both"):
            branding_mode = "none"
        from assemble_video import assemble_video
        run_job(name, "assemble", assemble_video, name, bg_audio_name, overwrite,
                speed_factor, branding_file, branding_mode)
        return jsonify({"message": "Assembly started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/upload", methods=["POST"])
def run_upload(name):
    try:
        data           = request.get_json() or {}
        privacy        = data.get("privacy", "private").strip()
        title_override = data.get("title", "").strip() or None
        desc_override  = data.get("description", "").strip() or None
        if privacy not in ("public", "private", "unlisted"):
            return jsonify({"error": "Invalid privacy value"}), 400

        def _do():
            from upload_video import _read_manifest, _final_video_path, _build_metadata, upload_video
            manifest = _read_manifest(name)
            t, d, tgs = _build_metadata(manifest)
            upload_video(_final_video_path(name, manifest),
                         title_override or t, desc_override or d, tgs, privacy)

        run_job(name, "upload", _do)
        return jsonify({"message": "Upload started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── YouTube auth ───────────────────────────────────────────────────────────────

@bp.route("/auth/youtube/reset", methods=["POST"])
def reset_youtube_auth():
    try:
        from upload_video import reset_auth
        reset_auth()
        return jsonify({"message": "YouTube token cleared. Next upload will re-authenticate."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/auth/youtube/status", methods=["GET"])
def youtube_auth_status():
    from pathlib import Path
    token_exists = Path("token.json").exists()
    return jsonify({"token_exists": token_exists})


# ── Instagram upload ───────────────────────────────────────────────────────────

@bp.route("/projects/<name>/run/upload_instagram", methods=["POST"])
def run_upload_instagram(name):
    try:
        data             = request.get_json() or {}
        caption_override = data.get("caption", "").strip() or None
        share_to_feed    = bool(data.get("share_to_feed", True))

        def _do():
            from upload_instagram import upload_instagram, _read_manifest, _build_caption
            from pathlib import Path
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read("config.ini")
            projects_dir = Path(cfg.get("paths", "projects_dir", fallback="projects"))
            file_path = projects_dir / name / ("final_" + name + ".mp4")
            manifest  = _read_manifest(name)
            caption   = caption_override or _build_caption(manifest)
            upload_instagram(file_path, caption=caption, share_to_feed=share_to_feed)

        run_job(name, "upload_instagram", _do)
        return jsonify({"message": "Instagram upload started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/auth/instagram/setup", methods=["POST"])
def instagram_auth_setup():
    try:
        data        = request.get_json() or {}
        app_id      = data.get("app_id", "").strip()
        app_secret  = data.get("app_secret", "").strip()
        short_token = data.get("short_token", "").strip()
        ig_user_id  = data.get("ig_user_id", "").strip() or None
        if not app_id or not app_secret or not short_token:
            return jsonify({"error": "app_id, app_secret, short_token required"}), 400
        from upload_instagram import setup
        setup(app_id, app_secret, short_token, ig_user_id=ig_user_id)
        return jsonify({"message": "Instagram credentials saved successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/auth/instagram/reset", methods=["POST"])
def instagram_auth_reset():
    try:
        from upload_instagram import reset_auth
        reset_auth()
        return jsonify({"message": "Instagram credentials cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/auth/instagram/status", methods=["GET"])
def instagram_auth_status():
    try:
        import json, time
        from pathlib import Path
        creds_path = Path("instagram_creds.json")
        if not creds_path.exists():
            return jsonify({"configured": False, "days_left": 0})
        creds     = json.loads(creds_path.read_text())
        expiry    = creds.get("expiry_ts", 0)
        days_left = max(0, int((expiry - time.time()) / 86400))
        return jsonify({"configured": True, "days_left": days_left})
    except Exception as e:
        return jsonify({"configured": False, "days_left": 0, "error": str(e)})


@bp.route("/auth/instagram/debug", methods=["POST"])
def instagram_auth_debug():
    try:
        import requests as req
        data  = request.get_json() or {}
        token = data.get("access_token", "").strip()
        if not token:
            return jsonify({"error": "access_token required"}), 400
        base  = "https://graph.facebook.com/v25.0"
        me    = req.get(base + "/me",
                        params={"access_token": token, "fields": "id,name"},
                        timeout=15)
        pages = req.get(base + "/me/accounts",
                        params={"access_token": token,
                                "fields": "id,name,instagram_business_account"},
                        timeout=15)
        return jsonify({"me": me.json(), "pages": pages.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Assets: branding list ─────────────────────────────────────────────────────

@bp.route("/assets/branding/list", methods=["GET"])
def list_branding_files():
    try:
        import configparser
        from pathlib import Path
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        assets_dir   = Path(cfg.get("paths", "assets_dir", fallback="assets"))
        branding_dir = assets_dir / "branding"
        if not branding_dir.exists():
            return jsonify({"files": []})
        files = sorted(
            f.name for f in branding_dir.iterdir()
            if f.suffix.lower() in (".mp4", ".mov", ".webm")
        )
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
