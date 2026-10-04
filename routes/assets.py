"""
routes/assets.py
================
REST API for the asset catalog (data/pipeline.db) and its files.

Files
  GET  /asset-files/<path>      a file of the ACTIVE workspace's assets folder
  GET  /library-files/<path>    a file of the shared library (music, SFX)

Characters / Locations (per workspace)
  GET/POST /assets/characters, PUT/DELETE /assets/characters/<name>
  POST /assets/characters/<name>/generate-art | upload-reference
  GET/POST /assets/locations,  PUT/DELETE /assets/locations/<key>
  POST /assets/locations/<key>/generate-art

Video clips (branding intros/outros, per workspace)
  GET/POST /assets/video-clips, PUT/DELETE /assets/video-clips/<key>

Background music (shared library)
  GET/POST /assets/background-audio, PUT/DELETE /assets/background-audio/<key>
  GET  /assets/background-audio/<key>/analyze      loudness + library average
  GET  /assets/background-audio/<key>/preview      MP3 slice with a gain (± voice)
  POST /assets/background-audio/<key>/apply-gain   bake the gain into the MP3
  POST /assets/background-audio/analyze-all

SFX (shared library)
  GET/POST /assets/sfx, PUT/DELETE /assets/sfx/<key>

  GET  /assets/usage            {kind: {key: [projects]}}

(Project types live in Settings now — see routes/settings.py.)
"""

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request, send_file

import db
from core import get_cfg, run_job, assets_dir, library_dir

bp = Blueprint("assets", __name__, url_prefix="")

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# =============================================================================
# ASSET FILE SERVING
# =============================================================================

def _serve_under(root: Path, filepath: str):
    full = (root / filepath).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError:
        abort(403)
    if not full.is_file():
        abort(404)
    # conditional=True → Range requests work, so <audio>/<video> can seek.
    return send_file(full, conditional=True)


@bp.route("/asset-files/<path:filepath>")
def serve_asset_file(filepath):
    """A file of the active workspace's assets folder (character art, clips, …)."""
    return _serve_under(assets_dir(), filepath)


@bp.route("/library-files/<path:filepath>")
def serve_library_file(filepath):
    """A file of the shared library (background music, SFX)."""
    return _serve_under(library_dir(), filepath)


# =============================================================================
# CHARACTERS
# =============================================================================

@bp.route("/assets/characters")
def list_characters():
    try:
        from manage_characters import load_characters
        return jsonify(load_characters(assets_dir()))
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
        _add(assets_dir(), name, voice_id, fixed_desc, variable_desc,
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
            assets_dir(), name,
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
        _remove(assets_dir(), name)
        return jsonify({"message": f"Character '{name}' removed"})
    except KeyError:
        return jsonify({"error": f"Character '{name}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/generate-art", methods=["POST"])
def generate_character_art(name: str):
    try:
        from manage_characters import generate_character_art as _gen
        run_job("assets", f"char_art_{name}", _gen, assets_dir(), name)
        return jsonify({"message": f"Art generation started for '{name}'"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Styled character art: drawing + existing cast as style sample → fal edit ──

@bp.route("/assets/characters/<name>/styled-art")
def styled_art_setup(name: str):
    """Everything the 'Generate in series style' panel needs (free, no fal call):
    the default prompt, the characters usable as style sample, the drawing, models."""
    try:
        import character_art as ca
        from manage_characters import load_characters
        c = load_characters(assets_dir()).get(name)
        if c is None:
            return jsonify({"error": f"Character '{name}' not found"}), 404
        drawing = ca.drawing_path(assets_dir(), c)
        return jsonify({
            "style_candidates": ca.style_candidates(assets_dir(), exclude=name),
            "drawing": drawing.relative_to(assets_dir()).as_posix() if drawing else None,
            "prompt": ca.default_prompt(c, bool(drawing)),
            "targets": list(ca.TARGETS),
            "in_use": {t: c.get(f) for t, f in ca.TARGETS.items()},
            "candidates": c.get("art_candidates", []),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/style-sample.png")
def styled_art_sample(name: str):
    """The style-sample image exactly as it would be sent (free preview)."""
    try:
        import io
        import character_art as ca
        names = [n for n in (request.args.get("chars") or "").split(",") if n]
        buf = io.BytesIO()
        ca.build_style_sample(assets_dir(), names).save(buf, format="PNG")
        return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/styled-art", methods=["POST"])
def styled_art_generate(name: str):
    """PAID: run the fal edit model in the background. Body: {model, prompt, chars,
    image_size}. Poll /projects/assets/status/char_art_<name>."""
    try:
        import character_art as ca
        data = request.get_json() or {}
        prompt = (data.get("prompt") or "").strip()
        chars = [n for n in data.get("chars") or [] if n]
        if not prompt or not chars:
            return jsonify({"error": "A prompt and at least one style-sample character are required"}), 400
        step = f"char_art_{name}"
        run_job("assets", step, ca.generate, assets_dir(), name, data.get("model") or None,
                prompt, chars, data.get("image_size") or "portrait_4_3")
        return jsonify({"message": "Generating", "step_key": step})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/characters/<name>/candidates/accept", methods=["POST"])
def styled_art_accept(name: str):
    try:
        import character_art as ca
        data = request.get_json() or {}
        return jsonify({"character": ca.accept(assets_dir(), name, data.get("path", ""), data.get("target", "scene_reference"))})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/assets/characters/<name>/candidates/discard", methods=["POST"])
def styled_art_discard(name: str):
    try:
        import character_art as ca
        return jsonify({"character": ca.discard(assets_dir(), name, (request.get_json() or {}).get("path", ""))})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# Image slots of a character that can be uploaded directly: slot → (field, file stem).
CHARACTER_IMAGE_SLOTS = {
    "scene_reference": ("art_34left_file_path",  "34left"),
    "thumbnail":       ("thumbnail_file_path",   "thumbnail"),
    "turnaround":      ("artwork_file_path",     "art"),
    "reference":       ("ref_image_file_path",   "ref"),
    "drawing":         ("ref_drawing_file_path", "ref_drawing"),
}


@bp.route("/assets/characters/<name>/image/<slot>", methods=["POST"])
def upload_character_image(name: str, slot: str):
    """Set one of a character's images from an uploaded file (multipart "file").
    The file is saved as characters/<name>/<stem>.<ext>; whatever file the slot (or
    that name) held before is moved to characters/<name>/previous/, never deleted."""
    try:
        from datetime import datetime
        from manage_characters import char_folder, load_characters, save_characters
        if slot not in CHARACTER_IMAGE_SLOTS:
            return jsonify({"error": f"slot must be one of {list(CHARACTER_IMAGE_SLOTS)}"}), 400
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "No file"}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            return jsonify({"error": f"Unsupported file type '{ext}'. Use PNG, JPG, WEBP or GIF."}), 400

        adir = assets_dir()
        chars = load_characters(adir)
        if name not in chars:
            return jsonify({"error": f"Character '{name}' not found"}), 404
        field, stem = CHARACTER_IMAGE_SLOTS[slot]
        folder = adir / "characters" / char_folder(name)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{stem}{ext}"

        # Keep anything we'd replace: the slot's current file and a file already at dest.
        still_used = {c.get(k) for n, c in chars.items() for k, _ in CHARACTER_IMAGE_SLOTS.values()
                      if not (n == name and k == field)}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if dest.relative_to(adir).as_posix() in still_used:      # another character uses that file
            dest = folder / f"{stem}_{stamp}{ext}"
        for old in {adir / chars[name][field] if chars[name].get(field) else None, dest} - {None}:
            rel_old = old.relative_to(adir).as_posix()
            if old.exists() and rel_old not in still_used:
                keep = folder / "previous" / f"{old.stem}_{stamp}{old.suffix}"
                keep.parent.mkdir(exist_ok=True)
                shutil.move(str(old), str(keep))

        f.save(dest)
        chars[name][field] = dest.relative_to(adir).as_posix()
        save_characters(adir, chars)
        return jsonify({"message": f"{slot.replace('_', ' ').capitalize()} updated", "file_path": chars[name][field]})
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
        rel_path = save_reference_image(assets_dir(), name, image_bytes, ext)
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
        return jsonify(get_new_locations_flat(assets_dir()))
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
        _add(assets_dir(), key, description, creation_prompt, eligible_chars)
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
            assets_dir(), key,
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
        _remove(assets_dir(), key)
        return jsonify({"message": f"Location '{key}' removed"})
    except KeyError:
        return jsonify({"error": f"Location '{key}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/locations/<key>/generate-art", methods=["POST"])
def generate_location_art(key: str):
    try:
        from manage_locations import generate_location_art as _gen
        run_job("assets", f"loc_art_{key}", _gen, assets_dir(), key)
        return jsonify({"message": f"Art generation started for location '{key}'"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# VIDEO CLIPS (branding intros / outros of the workspace)
# =============================================================================

def _clean_key(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", (raw or "").strip()).strip("_")


def _not_found(kind: str, key: str):
    return jsonify({"error": f"{kind} '{key}' not found"}), 404


@bp.route("/assets/video-clips")
def list_video_clips():
    try:
        from utils_config import load_video_clips
        return jsonify(load_video_clips(assets_dir()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips", methods=["POST"])
def add_video_clip():
    """multipart: key, description, file (video)."""
    try:
        key = _clean_key(request.form.get("key"))
        f   = request.files.get("file")
        if not key or not f:
            return jsonify({"error": "key and file required"}), 400
        from manage_video_clips import add_video_clip as _add
        with _upload_tmp(f) as src:
            entry = _add(assets_dir(), key, (request.form.get("description") or "").strip(), src)
        return jsonify({"message": f"Video clip '{key}' added", "clip": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips/<key>", methods=["PUT"])
def edit_video_clip(key: str):
    try:
        from manage_video_clips import load_video_clips, save_video_clips
        clips = load_video_clips(assets_dir())
        if key not in clips:
            return _not_found("Video clip", key)
        data = request.get_json() or {}
        if "description" in data:
            clips[key]["description"] = data["description"]
        save_video_clips(assets_dir(), clips)
        return jsonify({"message": f"Video clip '{key}' updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/video-clips/<key>", methods=["DELETE"])
def remove_video_clip(key: str):
    try:
        from manage_video_clips import remove_video_clip as _remove
        _remove(assets_dir(), key, delete_file=request.args.get("delete_file") == "1")
        return jsonify({"message": f"Video clip '{key}' removed"})
    except ValueError:
        return _not_found("Video clip", key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# BACKGROUND MUSIC (shared library — files under library/music)
# =============================================================================

@contextmanager
def _upload_tmp(file_storage):
    """Save an uploaded file to a temp path (keeping its extension) for the managers."""
    suffix = Path(file_storage.filename or "").suffix.lower()
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        file_storage.save(tmp)
        yield Path(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)


@bp.route("/assets/background-audio")
def list_background_audio():
    try:
        from utils_config import load_background_audio_index
        return jsonify(load_background_audio_index())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio", methods=["POST"])
def add_background_audio():
    """multipart: key, description, license, file (mp3 / mp4 / wav / m4a …).
    Non-MP3 uploads are kept as the original and transcoded to MP3."""
    try:
        import audio_tools
        from manage_background_audio import LICENSES, load_background_audio, save_background_audio
        key = _clean_key(request.form.get("key"))
        f   = request.files.get("file")
        if not key or not f:
            return jsonify({"error": "Name and file required"}), 400
        ext = Path(f.filename or "").suffix.lower()
        if ext not in audio_tools.AUDIO_EXTS:
            return jsonify({"error": f"Unsupported file type '{ext}'"}), 400
        lic = (request.form.get("license") or "").strip()
        if lic and lic not in LICENSES:
            return jsonify({"error": f"license must be one of {LICENSES}"}), 400
        music = load_background_audio()
        if key in music:
            return jsonify({"error": f"A track named '{key}' already exists"}), 409

        lib = library_dir()
        entry = {"name": key, "description": (request.form.get("description") or "").strip()}
        if ext == ".mp3":
            dest = lib / "music" / f"{key}.mp3"
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.save(dest)
        else:
            orig = lib / "music" / "originals" / f"{key}{ext}"
            orig.parent.mkdir(parents=True, exist_ok=True)
            f.save(orig)
            dest = lib / "music" / f"{key}.mp3"
            audio_tools.apply_gain(orig, dest, 0.0)
            entry["original_path"] = orig.relative_to(lib).as_posix()
        entry["full_path"] = dest.relative_to(lib).as_posix()
        entry["gain_db"] = 0.0
        if lic:
            entry["license"] = lic
        entry["loudness"] = audio_tools.measure(dest)
        music[key] = entry
        save_background_audio(None, music)
        return jsonify({"message": f"Track '{key}' added", "track": entry})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>", methods=["PUT"])
def edit_background_audio(key: str):
    try:
        from manage_background_audio import edit_background_audio as _edit
        return jsonify({"message": f"Track '{key}' updated",
                        "track": _edit(library_dir(), key, request.get_json() or {})})
    except KeyError:
        return _not_found("Track", key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>", methods=["DELETE"])
def remove_background_audio(key: str):
    try:
        from manage_background_audio import load_background_audio, remove_background_audio as _remove
        entry = load_background_audio().get(key)
        if not entry:
            return _not_found("Track", key)
        delete = request.args.get("delete_file") == "1"
        _remove(library_dir(), key, delete_file=delete)
        if delete and entry.get("original_path"):
            (library_dir() / entry["original_path"]).unlink(missing_ok=True)
        return jsonify({"message": f"Track '{key}' removed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _track(key: str) -> tuple[dict, Path, Path]:
    """(entry, current file, source the gain is applied to = the original upload)."""
    from manage_background_audio import load_background_audio
    entry = load_background_audio().get(key)
    if not entry:
        raise KeyError(key)
    lib = library_dir()
    current = lib / entry["full_path"]
    original = lib / entry["original_path"] if entry.get("original_path") else current
    return entry, current, original


def _voice_sample() -> Path | None:
    """A spoken line from the most recently changed project of this workspace."""
    pdir = Path(get_cfg()["projects_dir"])
    if not pdir.exists():
        return None
    manifests = sorted(pdir.glob("*/project_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for mp in manifests[:15]:
        for clip in sorted((mp.parent / "audio").glob("scene_*.mp3"))[:12]:
            if clip.stat().st_size > 30_000:          # a real sentence, not a blip
                return clip
    return None


@bp.route("/assets/background-audio/<key>/analyze")
def analyze_background_audio(key: str):
    """Loudness of the track (cached in its catalog entry) + the library average."""
    try:
        import audio_tools
        from manage_background_audio import load_background_audio, save_background_audio
        from music_level import library_suggestion
        entry, current, original = _track(key)
        music = load_background_audio()
        if request.args.get("refresh") == "1" or not entry.get("loudness"):
            music[key]["loudness"] = audio_tools.measure(current)
        if original != current and (request.args.get("refresh") == "1" or not entry.get("original_loudness")):
            music[key]["original_loudness"] = audio_tools.measure(original)
        save_background_audio(None, music)
        means = sorted(t["loudness"]["mean_db"] for t in music.values() if t.get("loudness"))
        return jsonify({
            "track": music[key],
            "library_median_mean_db": means[len(means) // 2] if means else None,
            "measured_tracks": len(means),
            "voice_sample": bool(_voice_sample()),
            "typical_video_gain_db": library_suggestion(key),
            "music_below_voice_db": get_cfg()["music_below_voice_db"],
            "bg_audio_volume": get_cfg()["bg_audio_volume"],
        })
    except KeyError:
        return _not_found("Track", key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/analyze-all", methods=["POST"])
def analyze_all_background_audio():
    """Measure every track that has no cached loudness yet (≈0.3 s per track)."""
    try:
        import audio_tools
        from manage_background_audio import load_background_audio, save_background_audio
        music, done, failed = load_background_audio(), 0, []
        for key, entry in music.items():
            if entry.get("loudness"):
                continue
            try:
                entry["loudness"] = audio_tools.measure(library_dir() / entry["full_path"])
                done += 1
            except Exception:
                failed.append(key)
        save_background_audio(None, music)
        return jsonify({"measured": done, "failed": failed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>/preview")
def preview_background_audio(key: str):
    """MP3 of a slice from the middle of the track. gain_db is relative to the
    ORIGINAL upload (the same scale the catalog's gain_db uses); voice=1 mixes it
    under a spoken line at the assembler's background volume."""
    try:
        import audio_tools
        _entry, _current, original = _track(key)
        gain = float(request.args.get("gain_db", 0) or 0)
        seconds = float(request.args.get("seconds", 15) or 15)
        voice = _voice_sample() if request.args.get("voice") == "1" else None
        data = audio_tools.preview_segment(original, gain, seconds, voice=voice,
                                           music_volume=get_cfg()["bg_audio_volume"])
        return Response(data, mimetype="audio/mpeg", headers={"Cache-Control": "no-store"})
    except KeyError:
        return _not_found("Track", key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/background-audio/<key>/apply-gain", methods=["POST"])
def apply_background_audio_gain(key: str):
    """Bake a gain (dB, relative to the original upload) into the track's MP3.
    The first time, the untouched file is moved to music/originals/ so the gain can
    be changed again later without stacking losses."""
    try:
        import audio_tools
        from manage_background_audio import load_background_audio, save_background_audio
        gain = float((request.get_json() or {}).get("gain_db", 0))
        if not -40 <= gain <= 40:
            return jsonify({"error": "gain_db must be between -40 and 40"}), 400
        entry, current, original = _track(key)
        lib = library_dir()
        if not entry.get("original_path"):
            keep = lib / "music" / "originals" / current.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(keep))
            original = keep
        dest = lib / "music" / f"{key}.mp3"
        audio_tools.apply_gain(original, dest, gain)
        music = load_background_audio()
        music[key].update({
            "original_path": original.relative_to(lib).as_posix(),
            "full_path": dest.relative_to(lib).as_posix(),
            "gain_db": round(gain, 1),
            "loudness": audio_tools.measure(dest),
        })
        save_background_audio(None, music)
        return jsonify({"message": f"Saved '{key}' at {gain:+.1f} dB", "track": music[key]})
    except KeyError:
        return _not_found("Track", key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SFX (shared library — files under library/sfx)
# =============================================================================

@bp.route("/assets/sfx")
def list_sfx():
    try:
        from utils_config import load_sfx_index
        return jsonify(load_sfx_index())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx", methods=["POST"])
def add_sfx():
    """multipart: key, description, file."""
    try:
        key = _clean_key(request.form.get("key"))
        f   = request.files.get("file")
        if not key or not f:
            return jsonify({"error": "Name and file required"}), 400
        from manage_sfx import add_sfx as _add
        with _upload_tmp(f) as src:
            entry = _add(library_dir(), key, (request.form.get("description") or "").strip(), src)
        return jsonify({"message": f"SFX '{key}' added", "sfx": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx/<key>", methods=["PUT"])
def edit_sfx(key: str):
    try:
        from manage_sfx import load_sfx, save_sfx
        sfx = load_sfx()
        if key not in sfx:
            return _not_found("SFX", key)
        data = request.get_json() or {}
        if "description" in data:
            sfx[key]["description"] = data["description"]
        save_sfx(None, sfx)
        return jsonify({"message": f"SFX '{key}' updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/assets/sfx/<key>", methods=["DELETE"])
def remove_sfx(key: str):
    try:
        from manage_sfx import remove_sfx as _remove
        _remove(library_dir(), key, delete_file=request.args.get("delete_file") == "1")
        return jsonify({"message": f"SFX '{key}' removed"})
    except ValueError:
        return _not_found("SFX", key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# USAGE (which projects use which asset — from the project index, see db.py)
# =============================================================================

@bp.route("/assets/usage")
def asset_usage():
    try:
        return jsonify({kind: db.asset_usage(kind)
                        for kind in ("characters", "locations", "project_types",
                                     "background_audio", "branding_files")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
