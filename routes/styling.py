"""
Subtitle / overlay styling routes.

Backs the top-level "Subtitles" page: read the current style parameters, render a
live preview over a sample frame (reflecting UNSAVED edits), and persist changes
back to config.ini (comments preserved).

STYLE_SCHEMA is the single source of truth. Each field carries:
  key   — the flat cfg key the renderer reads (e.g. "sub_fontsize"); also what the
          preview overrides map uses.
  label — UI label.
  type  — "number" | "color" | "text".
  section / opt — where the value lives in config.ini for saving. section may be the
          literal "@orientation", meaning the [vertical] / [horizontal] section (for
          the handful of per-orientation keys: font size + subtitle bottom margin).
  step  — optional numeric step (floats use 0.01).
"""
import io
import json
import re
from flask import Blueprint, request, send_file, jsonify

from utils_config import load_config, apply_video_format

bp = Blueprint("styling", __name__, url_prefix="/style")

# Named style snapshots ("looks"). Each profile stores the full editor state —
# every schema key for BOTH orientations — so applying one restores an exact look.
_PROFILES_FILE = "subtitle_profiles.json"


def _profiles_path():
    return load_config()["assets_dir"] / _PROFILES_FILE


def _read_profiles() -> dict:
    p = _profiles_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_profiles(data: dict) -> None:
    p = _profiles_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# fmt: off
STYLE_SCHEMA = [
    {"id": "dialogue", "label": "Dialogue subtitles", "fields": [
        {"key": "sub_font",          "label": "Font",              "type": "text",   "section": "subtitles", "opt": "font"},
        {"key": "sub_fontsize",      "label": "Font size (plain)", "type": "number", "section": "@orientation", "opt": "sub_fontsize", "per_orientation": True},
        {"key": "sub_markup_fontsize","label": "Font size (markup, 0 = match)", "type": "number", "section": "@orientation", "opt": "sub_markup_fontsize", "per_orientation": True},
        {"key": "sub_color",         "label": "Text colour",       "type": "color",  "section": "subtitles", "opt": "color"},
        {"key": "sub_stroke_color",  "label": "Outline colour",    "type": "color",  "section": "subtitles", "opt": "stroke_color"},
        {"key": "sub_stroke_width",  "label": "Outline width",     "type": "number", "section": "subtitles", "opt": "stroke_width"},
        {"key": "sub_margin_bottom", "label": "Distance from bottom", "type": "number", "section": "@orientation", "opt": "sub_margin_bottom", "per_orientation": True},
        {"key": "sub_margin_left",   "label": "Left margin",       "type": "number", "section": "subtitles", "opt": "margin_left"},
        {"key": "sub_margin_right",  "label": "Right margin",      "type": "number", "section": "subtitles", "opt": "margin_right"},
        {"key": "sub_bg_opacity",    "label": "Box opacity",       "type": "number", "section": "subtitles", "opt": "bg_opacity", "step": 0.01},
        {"key": "sub_bg_padding_x",  "label": "Box padding X",     "type": "number", "section": "subtitles", "opt": "bg_padding_x"},
        {"key": "sub_bg_padding_y",  "label": "Box padding Y",     "type": "number", "section": "subtitles", "opt": "bg_padding_y"},
    ]},
    {"id": "narrator", "label": "Narrator subtitles", "fields": [
        {"key": "nar_font",         "label": "Font",           "type": "text",   "section": "narrator_subtitles", "opt": "font"},
        {"key": "nar_fontsize",     "label": "Font size",      "type": "number", "section": "@orientation", "opt": "nar_fontsize", "per_orientation": True},
        {"key": "nar_color",        "label": "Text colour",    "type": "color",  "section": "narrator_subtitles", "opt": "color"},
        {"key": "nar_stroke_color", "label": "Outline colour", "type": "color",  "section": "narrator_subtitles", "opt": "stroke_color"},
        {"key": "nar_stroke_width", "label": "Outline width",  "type": "number", "section": "narrator_subtitles", "opt": "stroke_width"},
    ]},
    {"id": "footnote", "label": "Footnote / disclaimer", "fields": [
        {"key": "fn_font",         "label": "Font",           "type": "text",   "section": "footnote", "opt": "font"},
        {"key": "fn_fontsize",     "label": "Font size",      "type": "number", "section": "footnote", "opt": "fontsize"},
        {"key": "fn_color",        "label": "Text colour",    "type": "color",  "section": "footnote", "opt": "color"},
        {"key": "fn_stroke_color", "label": "Outline colour", "type": "color",  "section": "footnote", "opt": "stroke_color"},
        {"key": "fn_stroke_width", "label": "Outline width",  "type": "number", "section": "footnote", "opt": "stroke_width"},
        {"key": "fn_gap",          "label": "Gap below subtitle", "type": "number", "section": "footnote", "opt": "gap"},
        {"key": "fn_bg_opacity",   "label": "Box opacity",    "type": "number", "section": "footnote", "opt": "bg_opacity", "step": 0.01},
    ]},
    {"id": "repeat", "label": "Shadowing “repeat” message", "fields": [
        {"key": "repeat_text",         "label": "Message text",   "type": "text",   "section": "repeat_prompt", "opt": "text"},
        {"key": "repeat_font",         "label": "Font",           "type": "text",   "section": "repeat_prompt", "opt": "font"},
        {"key": "repeat_fontsize",     "label": "Font size",      "type": "number", "section": "repeat_prompt", "opt": "fontsize"},
        {"key": "repeat_color",        "label": "Text colour",    "type": "color",  "section": "repeat_prompt", "opt": "color"},
        {"key": "repeat_stroke_color", "label": "Outline colour", "type": "color",  "section": "repeat_prompt", "opt": "stroke_color"},
        {"key": "repeat_stroke_width", "label": "Outline width",  "type": "number", "section": "repeat_prompt", "opt": "stroke_width"},
        {"key": "repeat_bg_opacity",   "label": "Box opacity",    "type": "number", "section": "repeat_prompt", "opt": "bg_opacity", "step": 0.01},
    ]},
    {"id": "quiz_options", "label": "Quiz option chips", "fields": [
        {"key": "quiz_opt_font",         "label": "Font",             "type": "text",   "section": "quiz_options", "opt": "font"},
        {"key": "quiz_opt_fontsize",     "label": "Font size",        "type": "number", "section": "quiz_options", "opt": "fontsize"},
        {"key": "quiz_opt_color",        "label": "Neutral colour",   "type": "color",  "section": "quiz_options", "opt": "color_neutral"},
        {"key": "quiz_opt_color_correct","label": "Correct colour",   "type": "color",  "section": "quiz_options", "opt": "color_correct"},
        {"key": "quiz_opt_color_dim",    "label": "Dimmed colour",    "type": "color",  "section": "quiz_options", "opt": "color_dim"},
        {"key": "quiz_opt_stroke_color", "label": "Outline colour",   "type": "color",  "section": "quiz_options", "opt": "stroke_color"},
        {"key": "quiz_opt_stroke_width", "label": "Outline width",    "type": "number", "section": "quiz_options", "opt": "stroke_width"},
        {"key": "quiz_opt_margin_top",   "label": "Distance from top", "type": "number", "section": "quiz_options", "opt": "margin_top"},
        {"key": "quiz_opt_gap",          "label": "Gap between chips", "type": "number", "section": "quiz_options", "opt": "gap"},
        {"key": "quiz_opt_bg_opacity",   "label": "Box opacity",      "type": "number", "section": "quiz_options", "opt": "bg_opacity", "step": 0.01},
        {"key": "quiz_opt_bg_padding_x", "label": "Box padding X",    "type": "number", "section": "quiz_options", "opt": "bg_padding_x"},
        {"key": "quiz_opt_bg_padding_y", "label": "Box padding Y",    "type": "number", "section": "quiz_options", "opt": "bg_padding_y"},
    ]},
    {"id": "countdown", "label": "Quiz 3-2-1 countdown", "fields": [
        {"key": "countdown_font",          "label": "Font",         "type": "text",   "section": "countdown", "opt": "font"},
        {"key": "countdown_fontsize",      "label": "Font size",    "type": "number", "section": "countdown", "opt": "fontsize"},
        {"key": "countdown_color",         "label": "Text colour",  "type": "color",  "section": "countdown", "opt": "color"},
        {"key": "countdown_stroke_color",  "label": "Outline colour","type": "color", "section": "countdown", "opt": "stroke_color"},
        {"key": "countdown_stroke_width",  "label": "Outline width", "type": "number","section": "countdown", "opt": "stroke_width"},
        {"key": "countdown_per_number_ms", "label": "Per-digit ms",  "type": "number","section": "countdown", "opt": "per_number_ms"},
    ]},
]
# fmt: on

_KEY_TO_FIELD = {f["key"]: f for g in STYLE_SCHEMA for f in g["fields"]}


def _values_for(video_format: str) -> dict:
    """Current value of every schema key for one orientation, as display strings."""
    cfg = load_config()
    apply_video_format(cfg, video_format)
    out = {}
    for key in _KEY_TO_FIELD:
        v = cfg.get(key)
        out[key] = "" if v is None else str(v)
    return out


@bp.route("/schema", methods=["GET"])
def schema():
    """Return the field schema plus current values for both orientations."""
    try:
        return jsonify({
            "schema": STYLE_SCHEMA,
            "values": {fmt: _values_for(fmt) for fmt in ("vertical", "horizontal")},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/save", methods=["POST"])
def save():
    """Persist changed values. Body: {orientation, changed:{key:value}}.

    Per-orientation keys are written to the [orientation] section; everything else to
    its shared section. Only the keys present in `changed` are touched."""
    try:
        from config_writer import update_config_values
        data        = request.get_json(force=True) or {}
        orientation = data.get("orientation", "vertical")
        if orientation not in ("vertical", "horizontal"):
            orientation = "vertical"
        changed = data.get("changed") or {}

        updates: dict[str, dict[str, object]] = {}
        unknown = []
        for key, value in changed.items():
            field = _KEY_TO_FIELD.get(key)
            if not field:
                unknown.append(key)
                continue
            section = orientation if field["section"] == "@orientation" else field["section"]
            updates.setdefault(section, {})[field["opt"]] = value
        if unknown:
            return jsonify({"error": f"Unknown style keys: {', '.join(unknown)}"}), 400
        if updates:
            update_config_values(updates)
        return jsonify({"ok": True, "saved": sum(len(v) for v in updates.values())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/preview", methods=["POST"])
def preview():
    """Render a preview PNG reflecting the (possibly unsaved) `overrides`.

    Body: {format, style, text, footnote, repeat_message, overrides:{key:val}, quiz:{...}}.
    """
    try:
        from preview_render import render_text_preview
        data = request.get_json(force=True) or {}
        png = render_text_preview(
            data.get("text", ""),
            video_format   = data.get("format", "vertical"),
            style          = data.get("style", "dialog"),
            footnote       = data.get("footnote", ""),
            repeat_message = data.get("repeat_message", ""),
            overrides      = data.get("overrides") or {},
            quiz           = data.get("quiz") or {},
        )
        return send_file(io.BytesIO(png), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Profiles ("looks") ────────────────────────────────────────────────────────

def _updates_for(orientation: str, values: dict) -> dict:
    """Map a flat {key: value} dict (one orientation) to config {section: {opt: val}}.
    Per-orientation keys are routed to the [orientation] section. Unknown keys skipped."""
    updates: dict[str, dict[str, object]] = {}
    for key, value in (values or {}).items():
        field = _KEY_TO_FIELD.get(key)
        if not field:
            continue
        section = orientation if field["section"] == "@orientation" else field["section"]
        updates.setdefault(section, {})[field["opt"]] = value
    return updates


def _clean_profile_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:60]


@bp.route("/profiles", methods=["GET"])
def profiles_list():
    """Return the saved profile names (sorted, case-insensitive)."""
    try:
        return jsonify({"profiles": sorted(_read_profiles().keys(), key=str.lower)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/profiles/save", methods=["POST"])
def profiles_save():
    """Store the current editor state under `name`. Body: {name, values:{vertical,horizontal}}."""
    try:
        data = request.get_json(force=True) or {}
        name = _clean_profile_name(data.get("name", ""))
        if not name:
            return jsonify({"error": "A profile name is required."}), 400
        values = data.get("values") or {}
        # Keep only recognised keys, for both orientations.
        snapshot = {
            fmt: {k: str(v) for k, v in (values.get(fmt) or {}).items() if k in _KEY_TO_FIELD}
            for fmt in ("vertical", "horizontal")
        }
        profiles = _read_profiles()
        existed = name in profiles
        profiles[name] = snapshot
        _write_profiles(profiles)
        return jsonify({"ok": True, "name": name, "overwritten": existed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/profiles/apply", methods=["POST"])
def profiles_apply():
    """Write a profile's values to config.ini (both orientations) and return the
    resulting current values so the editor can refresh. Body: {name}."""
    try:
        from config_writer import update_config_values
        data = request.get_json(force=True) or {}
        name = _clean_profile_name(data.get("name", ""))
        profiles = _read_profiles()
        if name not in profiles:
            return jsonify({"error": f"No profile named {name!r}."}), 404
        snapshot = profiles[name]
        updates: dict[str, dict[str, object]] = {}
        for fmt in ("vertical", "horizontal"):
            for section, kv in _updates_for(fmt, snapshot.get(fmt) or {}).items():
                updates.setdefault(section, {}).update(kv)
        if updates:
            update_config_values(updates)
        return jsonify({
            "ok": True,
            "values": {fmt: _values_for(fmt) for fmt in ("vertical", "horizontal")},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/profiles/delete", methods=["POST"])
def profiles_delete():
    """Delete a saved profile. Body: {name}."""
    try:
        data = request.get_json(force=True) or {}
        name = _clean_profile_name(data.get("name", ""))
        profiles = _read_profiles()
        if name in profiles:
            del profiles[name]
            _write_profiles(profiles)
            return jsonify({"ok": True})
        return jsonify({"error": f"No profile named {name!r}."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
