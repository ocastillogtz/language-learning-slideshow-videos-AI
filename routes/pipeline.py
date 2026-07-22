from flask import Blueprint, request, jsonify
from core import run_job, get_job, PROJECTS_DIR

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
        # Optional extra/full cast for multi-character conversational types.
        raw_chars        = data.get("characters")
        characters       = [c for c in raw_chars if c] if isinstance(raw_chars, list) else None
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
                dialog_count=dialog_count,
                characters=characters)
        return jsonify({"message": "Script generation started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/audio", methods=["POST"])
def run_audio(name):
    try:
        data      = request.get_json(silent=True) or {}
        overwrite = bool(data.get("overwrite", False))
        from create_audio import create_audio
        run_job(name, "audio", create_audio, name, overwrite)
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
        mosaic_mode       = bool(data.get("mosaic_mode", False))
        model_override    = (data.get("model") or "").strip() or None
        from create_images import create_images
        run_job(name, "images", create_images, name, overwrite, ignore_cache,
                use_location_ref=use_location_ref, mosaic_mode=mosaic_mode,
                model_override=model_override)
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
        model_override      = (data.get("model") or "").strip() or None
        cast_override       = data.get("cast")  # list[str] of asset keys (reading_cast scenes) or None
        if isinstance(cast_override, list):
            cast_override = [str(x) for x in cast_override]
        else:
            cast_override = None
        if not scene_id:
            return jsonify({"error": "scene_id required"}), 400
        from create_images import create_image_single
        step_key = "image_" + scene_id
        run_job(name, step_key, create_image_single, name, scene_id,
                prompt_override=prompt_override, use_location_ref=use_location_ref,
                characters_override=characters_override, cast_override=cast_override,
                model_override=model_override)
        return jsonify({"message": "Image regeneration started", "step_key": step_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/config/image_models", methods=["GET"])
def list_image_models():
    """Selectable fal.ai image (edit) models for the UI dropdown, plus the config
    default. Reads config.ini fresh so edits apply without a server restart."""
    try:
        from utils_config import load_config
        c = load_config()
        models = [{"key": k, "endpoint": v} for k, v in c["fal_models"].items()]
        default_key = next((k for k, v in c["fal_models"].items()
                            if v == c["fal_model"]), None)
        return jsonify({"models": models, "default_key": default_key,
                        "default_endpoint": c["fal_model"]})
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
        # Optional format override + output subdir (reading_together horizontal long pass)
        fmt    = (data.get("format_override") or "").strip() or None
        subdir = (data.get("out_subdir") or "").strip()
        step   = "video_h" if subdir else "video"
        # Annotation text size multiplier (1.0 = default). Clamped to a sane range.
        raw_fs           = data.get("annot_font_scale")
        try:
            annot_font_scale = float(raw_fs) if raw_fs not in (None, "") else 1.0
        except (TypeError, ValueError):
            annot_font_scale = 1.0
        annot_font_scale = max(0.5, min(2.5, annot_font_scale))
        regen_annotations = bool(data.get("regen_annotations", False))
        # reading_together pre-pause (ms) before each sentence's narration, except
        # the first. None → use the config default; explicit value (incl. 0) wins.
        raw_pre_pause     = data.get("read_pre_pause_ms")
        read_pre_pause_ms = int(raw_pre_pause) if raw_pre_pause not in (None, "") else None
        # Shadowing repeat overlay: None message → config default; "" hides it.
        repeat_message    = data.get("repeat_message")
        if repeat_message is not None:
            repeat_message = str(repeat_message)
        raw_rfs           = data.get("repeat_fontsize")
        repeat_fontsize   = int(raw_rfs) if raw_rfs not in (None, "") else None
        repeat_font       = (data.get("repeat_font") or "").strip() or None
        # Extra hold (ms) after a footnote scene so it can be read. None → config default.
        raw_fh            = data.get("footnote_hold_ms")
        footnote_hold_ms  = int(raw_fh) if raw_fh not in (None, "") else None
        from create_video import create_videos
        run_job(name, step, create_videos, name, overwrite, annotated_subtitles, footnote,
                inter_pause_ms, fmt, subdir, annot_font_scale, regen_annotations,
                read_pre_pause_ms,
                repeat_message=repeat_message, repeat_fontsize=repeat_fontsize,
                repeat_font=repeat_font, footnote_hold_ms=footnote_hold_ms)
        return jsonify({"message": "Video rendering started", "step_key": step})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/video_scene", methods=["POST"])
def run_video_scene(name):
    """Re-render a single scene's clip (and the silent pause right after it)."""
    try:
        data                = request.get_json() or {}
        scene_id            = (data.get("scene_id") or "").strip()
        if not scene_id:
            return jsonify({"error": "scene_id required"}), 400
        annotated_subtitles = bool(data.get("annotated_subtitles", False))
        footnote            = str(data.get("footnote", "")).strip()
        raw_pause           = data.get("inter_pause_ms")
        inter_pause_ms      = int(raw_pause) if raw_pause not in (None, "") else None
        raw_fs              = data.get("annot_font_scale")
        try:
            annot_font_scale = float(raw_fs) if raw_fs not in (None, "") else 1.0
        except (TypeError, ValueError):
            annot_font_scale = 1.0
        annot_font_scale  = max(0.5, min(2.5, annot_font_scale))
        regen_annotations = bool(data.get("regen_annotations", False))
        repeat_message    = data.get("repeat_message")
        if repeat_message is not None:
            repeat_message = str(repeat_message)
        raw_rfs           = data.get("repeat_fontsize")
        repeat_fontsize   = int(raw_rfs) if raw_rfs not in (None, "") else None
        repeat_font       = (data.get("repeat_font") or "").strip() or None
        raw_fh            = data.get("footnote_hold_ms")
        footnote_hold_ms  = int(raw_fh) if raw_fh not in (None, "") else None
        from create_video import create_video_single
        step_key = "video_" + scene_id
        run_job(name, step_key, create_video_single, name, scene_id,
                annotated_subtitles=annotated_subtitles, footnote=footnote,
                inter_pause_ms=inter_pause_ms, annot_font_scale=annot_font_scale,
                regen_annotations=regen_annotations,
                repeat_message=repeat_message, repeat_fontsize=repeat_fontsize,
                repeat_font=repeat_font, footnote_hold_ms=footnote_hold_ms)
        return jsonify({"message": "Clip re-render started", "step_key": step_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/repeat_scenes", methods=["POST"])
def manage_repeat_scenes(name):
    """Add or remove shadowing "repeat" scenes (image + readable subtitle + centered
    message) after every dialog line. Body: {"action": "add" | "remove"}.

    Synchronous manifest mutation (fast). Render the Video step afterwards to bake the
    new scenes (or re-render the affected dialog clips, which rebuild the repeat too).
    """
    try:
        data   = request.get_json() or {}
        action = (data.get("action") or "add").strip()
        if action not in ("add", "remove"):
            return jsonify({"error": "action must be 'add' or 'remove'"}), 400
        if action == "add":
            raw_factor = data.get("factor")
            try:
                factor = float(raw_factor) if raw_factor not in (None, "") else None
            except (TypeError, ValueError):
                factor = None
            if factor is not None:
                factor = max(0.1, min(10.0, factor))
            from repeat_scenes import add_repeat_scenes
            return jsonify(add_repeat_scenes(name, factor=factor))
        from repeat_scenes import remove_repeat_scenes
        return jsonify(remove_repeat_scenes(name))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/custom_scenes", methods=["POST"])
def manage_custom_scenes(name):
    """Add or remove an empty custom scene at the start or end of the video.

    Body: {"action": "add" | "remove", "position": "start" | "end" ("all" for remove)}

    Synchronous manifest mutation (fast). The scene is created empty; fill in its
    text and image prompt in the Generated Items tab, then generate its audio and
    image per-scene and render the Video step.
    """
    try:
        data     = request.get_json() or {}
        action   = (data.get("action") or "add").strip()
        position = (data.get("position") or "start").strip()
        if action not in ("add", "remove"):
            return jsonify({"error": "action must be 'add' or 'remove'"}), 400
        if action == "add":
            from custom_scenes import add_custom_scene
            return jsonify(add_custom_scene(name, position))
        from custom_scenes import remove_custom_scene
        return jsonify(remove_custom_scene(name, position))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/pauses", methods=["PATCH"])
def update_pauses(name):
    """Bulk-set the duration of silent pause scenes.

    Body: {"duration_ms": int, "scope": "all" | "dialog"}
      all    — every silent pause scene (audio == null, description == "pause")
      dialog — only pauses immediately following a spoken dialog line (a TTS scene
               that is not narration / repetition)
    """
    import json
    try:
        data  = request.get_json() or {}
        scope = (data.get("scope") or "all").strip()
        if scope not in ("all", "dialog"):
            return jsonify({"error": "scope must be 'all' or 'dialog'"}), 400
        try:
            ms = int(data.get("duration_ms"))
        except (TypeError, ValueError):
            return jsonify({"error": "duration_ms must be an integer"}), 400
        if ms < 0 or ms > 10000:
            return jsonify({"error": "duration_ms must be between 0 and 10000"}), 400

        mp = PROJECTS_DIR / name / "project_manifest.json"
        if not mp.exists():
            return jsonify({"error": "Project not found"}), 404
        with open(mp, encoding="utf-8") as f:
            m = json.load(f)

        scenes = m.get("scenes", [])

        def _is_pause(s):
            return s.get("audio") is None and s.get("image") is None \
                   and s.get("description") == "pause"

        def _is_dialog(s):
            a = s.get("audio") or {}
            return a.get("type") == "tts" \
                   and not s.get("_is_narration") and not s.get("_is_repetition")

        updated = 0
        for i, s in enumerate(scenes):
            if not _is_pause(s):
                continue
            if scope == "dialog":
                prev = scenes[i - 1] if i > 0 else None
                # A shadowing repeat scene sits between the dialog line and its pause,
                # so a pause after a repeat scene still belongs to that dialog.
                if prev and prev.get("_is_repeat_prompt"):
                    prev = scenes[i - 2] if i > 1 else None
                if not (prev and _is_dialog(prev)):
                    continue
            s["duration_ms"] = ms
            updated += 1

        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)

        return jsonify({"message": "Pauses updated", "scope": scope,
                        "duration_ms": ms, "updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/annotations/reset", methods=["POST"])
def reset_annotations(name):
    """Clear cached grammar annotation(s) so they re-prompt OpenAI on the next render.

    Body: {"scene_id": "<id>"} resets one scene; omit scene_id to reset all.
    Also deletes the affected rendered clip(s) so a normal re-render (no global
    overwrite needed) rebuilds them with the fresh annotation.
    """
    try:
        data     = request.get_json(silent=True) or {}
        scene_id = (data.get("scene_id") or "").strip()
        videos   = PROJECTS_DIR / name / "videos"
        removed_cache = 0
        removed_clips = 0
        if videos.exists():
            # annotation JSON + PNG live in any videos/**/_annot directory
            for annot_dir in videos.rglob("_annot"):
                if not annot_dir.is_dir():
                    continue
                patterns = ([f"{scene_id}.json", f"{scene_id}.png"]
                            if scene_id else ["*.json", "*.png"])
                for pat in patterns:
                    for f in annot_dir.glob(pat):
                        try:
                            f.unlink(); removed_cache += 1
                        except Exception:
                            pass
            # delete the rendered clip(s) so they rebuild on the next render
            if scene_id:
                for clip in videos.rglob(f"{scene_id}.mp4"):
                    try:
                        clip.unlink(); removed_clips += 1
                    except Exception:
                        pass
        return jsonify({"scene_id": scene_id or None,
                        "removed_cache": removed_cache,
                        "removed_clips": removed_clips})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/annotations/<scene_id>", methods=["GET"])
def get_scene_annotation(name, scene_id):
    """Return the grammar annotation (tokens + spans) for one scene, from cache."""
    try:
        from annotation_store import read_scene_annotation
        return jsonify(read_scene_annotation(name, scene_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/annotations/<scene_id>", methods=["POST"])
def save_scene_annotation_route(name, scene_id):
    """Save an edited annotation, or (with {"regenerate": true}) re-prompt OpenAI.

    Either path rewrites the per-scene cache and deletes the rendered clip(s) so a
    normal re-render applies the change. Editing reuses the cache → no API call.
    """
    try:
        data = request.get_json(silent=True) or {}
        if data.get("regenerate"):
            from annotation_store import regenerate_scene_annotation
            return jsonify(regenerate_scene_annotation(name, scene_id, force=True))
        from annotation_store import save_scene_annotation
        return jsonify(save_scene_annotation(name, scene_id,
                                             data.get("tokens"), data.get("spans")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── promotional pipeline ───────────────────────────────────────────────────────

@bp.route("/projects/<name>/run/promo_build", methods=["POST"])
def run_promo_build(name):
    try:
        data      = request.get_json() or {}
        character = (data.get("character") or "").strip()
        situation = (data.get("situation") or "").strip()
        text      = (data.get("text") or "").strip()
        if not character or not text:
            return jsonify({"error": "character and text are required"}), 400
        from create_promotional import build_promotional_project
        run_job(name, "promo_build", build_promotional_project, name, character, situation, text)
        return jsonify({"message": "Promotional scene build started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── reading_together pipeline ──────────────────────────────────────────────────

@bp.route("/projects/<name>/run/reading_build", methods=["POST"])
def run_reading_build(name):
    try:
        data      = request.get_json() or {}
        raw_pp    = data.get("per_part")
        raw_mw    = data.get("max_words")
        per_part  = int(raw_pp) if raw_pp not in (None, "") else None
        max_words = int(raw_mw) if raw_mw not in (None, "") else None
        from create_reading_source import build_reading_project
        run_job(name, "reading_build", build_reading_project, name, per_part, max_words)
        return jsonify({"message": "Reading source build started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/reading_cast", methods=["POST"])
def run_reading_cast(name):
    try:
        data       = request.get_json() or {}
        regenerate = bool(data.get("regenerate", False))
        reanalyze  = bool(data.get("reanalyze", True))
        # {story_role: existing_character_key} — cast your own characters in roles.
        raw_map      = data.get("cast_mapping")
        cast_mapping = raw_map if isinstance(raw_map, dict) else None
        from create_reading_source import materialize_reading_cast
        run_job(name, "reading_cast", materialize_reading_cast, name, regenerate, reanalyze,
                cast_mapping)
        return jsonify({"message": "Cast materialization started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/reading_assemble", methods=["POST"])
def run_reading_assemble(name):
    try:
        data          = request.get_json() or {}
        # Use (x or "") so an explicit JSON null (e.g. branding_file when mode is
        # "none") doesn't blow up on .strip().
        bg_audio_name = (data.get("bg_audio_name") or "office").strip() or "office"
        overwrite     = bool(data.get("overwrite", False))
        raw_speed     = data.get("speed_factor")
        speed_factor  = float(raw_speed) if raw_speed not in (None, "") else None
        branding_file = (data.get("branding_file") or "").strip() or None
        branding_mode = (data.get("branding_mode") or "none").strip() or "none"
        if branding_mode not in ("none", "intro", "outro", "both"):
            branding_mode = "none"
        make_parts    = bool(data.get("make_parts", True))
        make_long     = bool(data.get("make_long", True))
        raw_pp        = data.get("per_part")
        per_part      = int(raw_pp) if raw_pp not in (None, "") else None
        raw_gain      = data.get("bg_audio_gain_db")
        bg_gain_db    = float(raw_gain) if raw_gain not in (None, "") else 0.0
        from assemble_reading import assemble_reading
        run_job(name, "reading_assemble", assemble_reading, name, bg_audio_name, overwrite,
                speed_factor, branding_file, branding_mode, make_parts, make_long, per_part,
                bg_gain_db)
        return jsonify({"message": "Reading assembly started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/assemble", methods=["POST"])
def run_assemble(name):
    try:
        data          = request.get_json() or {}
        # Use (x or "") so an explicit JSON null (e.g. branding_file when mode is
        # "none") doesn't blow up on .strip().
        bg_audio_name = (data.get("bg_audio_name") or "office").strip() or "office"
        overwrite     = bool(data.get("overwrite", False))
        raw_speed     = data.get("speed_factor")
        speed_factor  = float(raw_speed) if raw_speed not in (None, "") else None
        branding_file = (data.get("branding_file") or "").strip() or None
        branding_mode = (data.get("branding_mode") or "none").strip() or "none"
        if branding_mode not in ("none", "intro", "outro", "both"):
            branding_mode = "none"
        raw_gain      = data.get("bg_audio_gain_db")
        bg_gain_db    = float(raw_gain) if raw_gain not in (None, "") else 0.0
        from assemble_video import assemble_video
        run_job(name, "assemble", assemble_video, name, bg_audio_name, overwrite,
                speed_factor, branding_file, branding_mode, bg_gain_db)
        return jsonify({"message": "Assembly started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/upload_meta", methods=["GET"])
def upload_meta(name):
    """Return the title, description, and tags that would be sent to YouTube,
    so the frontend can preview and edit them before uploading."""
    try:
        from upload_video import _read_manifest, _build_metadata
        manifest = _read_manifest(name)
        title, description, tags = _build_metadata(manifest)
        return jsonify({"title": title, "description": description, "tags": tags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/run/upload", methods=["POST"])
def run_upload(name):
    try:
        data           = request.get_json() or {}
        privacy        = data.get("privacy", "private").strip()
        title_override = data.get("title", "").strip() or None
        desc_override  = data.get("description", "").strip() or None
        category_id    = (data.get("category_id") or "22").strip() or "22"
        made_for_kids  = bool(data.get("made_for_kids", False))
        publish_at     = (data.get("publish_at") or "").strip() or None
        raw_tags       = data.get("tags")
        tags_override  = None
        if isinstance(raw_tags, list):
            tags_override = [str(t).strip().lstrip("#") for t in raw_tags if str(t).strip()]
        elif isinstance(raw_tags, str) and raw_tags.strip():
            tags_override = [t.strip().lstrip("#") for t in raw_tags.split(",") if t.strip()]

        if privacy not in ("public", "private", "unlisted"):
            return jsonify({"error": "Invalid privacy value"}), 400

        # ── Validate the scheduled release time (must parse and be in the future) ──
        if publish_at:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "Invalid publish_at — expected an ISO 8601 / RFC 3339 timestamp"}), 400
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                return jsonify({"error": "Scheduled release time must be in the future"}), 400
            privacy = "private"   # YouTube requires private when publishAt is set

        def _do():
            from upload_video import _read_manifest, _final_video_path, _build_metadata, upload_video
            manifest = _read_manifest(name)
            t, d, tgs = _build_metadata(manifest)
            upload_video(_final_video_path(name, manifest),
                         title_override or t,
                         desc_override or d,
                         tags_override if tags_override else tgs,
                         privacy,
                         category_id=category_id,
                         publish_at=publish_at,
                         made_for_kids=made_for_kids)

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
