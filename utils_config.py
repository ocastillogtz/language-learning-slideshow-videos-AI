"""
utils_config.py
===============
Central config loader for the language-learning video pipeline.

All other modules import from here — no module reads config.ini directly.
"""

import configparser
import logging
from pathlib import Path
from typing import Any

import db
from languages import language

# moviepy 1.0.3 (pinned, see requirements.txt) calls Image.ANTIALIAS, which
# Pillow 10+ removed in favour of Image.LANCZOS (the same filter). Restore the
# alias here since every moviepy-using module imports utils_config.
from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.ini")


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """
    Parse config.ini and return a flat dict of all pipeline parameters.
    Paths are returned as Path objects. Missing optional keys return None.
    """
    # inline_comment_prefixes lets a `key = value  ; note` line drop the trailing
    # note (e.g. the empty `font = ; falls back to …` lines). Only ";" — NOT "#",
    # since hex colours like markup_italic_colors = #FFD700 start with "#". A ";"
    # only counts as a comment when preceded by whitespace, so values that embed
    # ";" without a leading space (e.g. the image style_tokens) are left intact.
    cfg = configparser.RawConfigParser(inline_comment_prefixes=(";",))
    cfg.read(config_path, encoding="utf-8")

    # Layer the active workspace on top of config.ini: its own assets/projects
    # folders and its per-workspace setting overrides (edited in the Settings view).
    ws = _active_workspace()
    ws_settings = {}
    if ws:
        ws_settings = db.get_settings(ws["slug"])
        for section, kv in ws_settings.items():
            if not cfg.has_section(section):
                cfg.add_section(section)
            for key, value in kv.items():
                cfg.set(section, key, value)
        cfg.set("paths", "projects_dir", ws["projects_dir"])
        cfg.set("paths", "assets_dir", ws["assets_dir"])
    lang = language(ws["language_code"] if ws else None)

    def _p(section: str, key: str, fallback=None):
        return cfg.get(section, key, fallback=fallback)

    def _i(section: str, key: str, fallback: int = 0) -> int:
        return cfg.getint(section, key, fallback=fallback)

    def _f(section: str, key: str, fallback: float = 0.0) -> float:
        return cfg.getfloat(section, key, fallback=fallback)

    projects_dir = Path(_p("paths", "projects_dir", "projects"))
    assets_dir   = Path(_p("paths", "assets_dir",   "assets"))
    # Shared by every workspace: background music + SFX.
    library_dir  = Path(_p("paths", "library_dir",  "library"))

    # [fal_models] lists the image (edit) models selectable in the UI dropdown
    # (key = fal endpoint id). [fal] model is the default and may be either a key
    # from that list or a raw endpoint id.
    fal_models    = dict(cfg.items("fal_models")) if cfg.has_section("fal_models") else {}
    raw_fal_model = _p("fal", "model", "fal-ai/bytedance/seedream/v4.5/edit")

    return {
        # Workspace (language / channel) — see db.py
        "workspace":        ws["slug"] if ws else None,
        "workspace_name":   ws["name"] if ws else "",
        "channel_name":     (ws or {}).get("channel_name") or "",
        "language_code":    lang["code"],
        "language_name":    lang["name"],      # English name, used in prompts ({LANGUAGE})
        "language_native":  lang["native"],

        # Directories
        "projects_dir":   projects_dir,
        "assets_dir":     assets_dir,
        "library_dir":    library_dir,

        # Subdirectory shortcuts — see ASSET_LAYOUT below
        "background_audio_dir": library_dir / "music",
        "sfx_dir":              library_dir / "sfx",
        "branding_dir":         assets_dir / "branding",
        "characters_dir":       assets_dir / "characters",
        "locations_dir":        assets_dir / "locations",
        "studios_dir":          assets_dir / "studios",
        "cache_dir":            assets_dir / "cache",

        # Tools
        "imagemagick": _p("tools", "imagemagick"),

        # General
        "log_level": _p("general", "log_level", "INFO"),

        # Video
        "target_w":             _i("video", "target_w",             1080),
        "target_h":             _i("video", "target_h",             1920),
        "fps":                  _i("video", "fps",                  30),
        "inter_pause_ms":       _i("video", "inter_pause_ms",       350),
        "margin_blur_radius":   _i("video", "margin_blur_radius",   30),
        "narrator_blur_radius": _i("video", "narrator_blur_radius", 12),
        "blend_px":             _i("video", "blend_px",             120),

        # Per-orientation render overrides (raw strings; applied at render time by
        # apply_video_format()). Keys use the internal flat names (target_w,
        # sub_fontsize, nar_fontsize, fal_image_size, …) and override the base values
        # above for that orientation. Anything omitted keeps the base value.
        "video_formats": {
            fmt: (dict(cfg.items(fmt)) if cfg.has_section(fmt) else {})
            for fmt in ("vertical", "horizontal")
        },

        # Subtitles
        "sub_font":          _p("subtitles", "font",          "Arial-Bold"),
        "sub_fontsize":      _i("subtitles", "fontsize",       76),
        "sub_color":         _p("subtitles", "color",          "white"),
        "sub_stroke_color":  _p("subtitles", "stroke_color",  "black"),
        "sub_stroke_width":  _i("subtitles", "stroke_width",   4),
        "sub_margin_bottom": _i("subtitles", "margin_bottom",  300),
        "sub_margin_left":   _i("subtitles", "margin_left",    40),
        "sub_margin_right":  _i("subtitles", "margin_right",   170),
        "sub_bg_opacity":    _f("subtitles", "bg_opacity",     0.45),
        "sub_bg_padding_x":  _i("subtitles", "bg_padding_x",   20),
        "sub_bg_padding_y":  _i("subtitles", "bg_padding_y",   12),
        "markup_italic_colors":  [
            c.strip() for c in
            _p("subtitles", "markup_italic_colors",
               "#FFD700,#DBB900,#FFDD24,#B89B00,#FFE247").split(",")
            if c.strip()
        ],
        "markup_bold_color":     _p("subtitles", "markup_bold_color",   "#FFD700"),


        # Narrator subtitles
        "nar_font":          _p("narrator_subtitles", "font",         "Arial-Bold"),
        "nar_fontsize":      _i("narrator_subtitles", "fontsize",      76),
        "nar_color":         _p("narrator_subtitles", "color",         "white"),
        "nar_stroke_color":  _p("narrator_subtitles", "stroke_color", "black"),
        "nar_stroke_width":  _i("narrator_subtitles", "stroke_width",  4),

        # Character icon overlay
        "icon_x":    _i("character_icon", "x",    700),
        "icon_y":    _i("character_icon", "y",    200),
        "icon_size": _i("character_icon", "size", 200),

        # Footnote overlay (optional disclaimer shown below the main subtitle)
        "fn_font":         _p("footnote", "font",         ""),   # empty → falls back to sub_font
        "fn_fontsize":     _i("footnote", "fontsize",     32),
        "fn_color":        _p("footnote", "color",        "white"),
        "fn_stroke_color": _p("footnote", "stroke_color", "white"),
        "fn_stroke_width": _i("footnote", "stroke_width", 0),
        "fn_gap":          _i("footnote", "gap",          50),   # px between sub bg-bottom and footnote
        "fn_bg_opacity":   _f("footnote", "bg_opacity",   0.45),
        # Extra silent hold (ms) after a footnote scene so it can be read. 0 = off.
        "footnote_hold_ms": _i("footnote", "hold_ms",     0),

        # Repeat-prompt overlay (shadowing "intermediate" scene: image + readable
        # subtitle + a centered message such as "Jetzt wiederholen"). Text and font
        # are global; message + font size are also overridable per render.
        "repeat_text":         _p("repeat_prompt", "text",         "Jetzt wiederholen"),
        "repeat_font":         _p("repeat_prompt", "font",         ""),   # empty → nar_font
        "repeat_fontsize":     _i("repeat_prompt", "fontsize",     90),
        "repeat_color":        _p("repeat_prompt", "color",        "PeachPuff"),
        "repeat_stroke_color": _p("repeat_prompt", "stroke_color", "sienna4"),
        "repeat_stroke_width": _i("repeat_prompt", "stroke_width", 3),
        "repeat_bg_opacity":   _f("repeat_prompt", "bg_opacity",   0.45),
        "repeat_duration_ms":  _i("repeat_prompt", "duration_ms",  0),    # 0 = mirror dialog
        "repeat_duration_factor": _f("repeat_prompt", "duration_factor", 1.0),  # × mirrored length

        # Silent 3-2-1 countdown (preposition_quiz): centred digit over the held situation
        # frame; no audio. per_number_ms drives each digit's hold time.
        "countdown_font":          _p("countdown", "font",          ""),   # empty → nar_font
        "countdown_fontsize":      _i("countdown", "fontsize",       220),
        "countdown_color":         _p("countdown", "color",         "white"),
        "countdown_stroke_color":  _p("countdown", "stroke_color",  "black"),
        "countdown_stroke_width":  _i("countdown", "stroke_width",   6),
        "countdown_per_number_ms": _i("countdown", "per_number_ms", 800),

        # Preposition_quiz option chips (row of 3 near the top). Neutral before reveal;
        # the correct chip turns green (color_correct) and the rest dim on the full reveal.
        "quiz_opt_font":          _p("quiz_options", "font",          ""),   # empty → nar_font
        "quiz_opt_fontsize":      _i("quiz_options", "fontsize",       66),
        "quiz_opt_color":         _p("quiz_options", "color_neutral", "white"),
        "quiz_opt_color_correct": _p("quiz_options", "color_correct", "#2ecc40"),
        "quiz_opt_color_dim":     _p("quiz_options", "color_dim",     "#9aa0a6"),
        "quiz_opt_stroke_color":  _p("quiz_options", "stroke_color",  "black"),
        "quiz_opt_stroke_width":  _i("quiz_options", "stroke_width",   4),
        "quiz_opt_margin_top":    _i("quiz_options", "margin_top",     120),
        "quiz_opt_gap":           _i("quiz_options", "gap",            34),
        "quiz_opt_bg_opacity":    _f("quiz_options", "bg_opacity",     0.55),
        "quiz_opt_bg_padding_x":  _i("quiz_options", "bg_padding_x",   26),
        "quiz_opt_bg_padding_y":  _i("quiz_options", "bg_padding_y",   14),

        # Assembly
        "bg_audio_volume":    _f("assembly", "bg_audio_volume",    0.18),
        "crossfade_s":        _f("assembly", "crossfade_s",        0.35),
        "bg_audio_fadein_s":  _f("assembly", "bg_audio_fadein_s",  1.0),
        "bg_audio_fadeout_s": _f("assembly", "bg_audio_fadeout_s", 2.0),
        "speed_factor":       _f("assembly", "speed_factor",       1.0),

        # Reading_together part overlays (vertical part shorts)
        # Default background music for reading_together assembly (parts + long).
        "reading_bg_audio_name":    _p("reading", "bg_audio_name",    "office"),
        "reading_bg_audio_gain_db": _f("reading", "bg_audio_gain_db", 0.0),
        "part_label_word":         _p("reading", "part_label_word",         "Teil"),
        "part_label_fontsize":     _i("reading", "part_label_fontsize",     64),
        "part_label_color":        _p("reading", "part_label_color",        "BlanchedAlmond"),
        "part_label_stroke_color": _p("reading", "part_label_stroke_color", "tan4"),
        "part_label_stroke_width": _i("reading", "part_label_stroke_width", 4),
        "part_label_margin_x":     _i("reading", "part_label_margin_x",     50),
        "part_label_margin_y":     _i("reading", "part_label_margin_y",     50),
        "part_label_bg_opacity":   _f("reading", "part_label_bg_opacity",   0.45),
        "part_label_bg_padding_x": _i("reading", "part_label_bg_padding_x", 22),
        "part_label_bg_padding_y": _i("reading", "part_label_bg_padding_y", 12),
        "continuation_text":         _p("reading", "continuation_text",         "Fortsetzung folgt..."),
        "continuation_seconds":      _f("reading", "continuation_seconds",      2.0),
        "continuation_fontsize":     _i("reading", "continuation_fontsize",     96),
        "continuation_color":        _p("reading", "continuation_color",        "PeachPuff"),
        "continuation_stroke_color": _p("reading", "continuation_stroke_color", "sienna4"),
        "continuation_stroke_width": _i("reading", "continuation_stroke_width", 4),
        # Soft dark backing box behind the centered continuation legend (like the
        # subtitles / part label). Opacity 0 => no box.
        "continuation_bg_opacity":   _f("reading", "continuation_bg_opacity",   0.67),
        "continuation_bg_padding_x": _i("reading", "continuation_bg_padding_x", 20),
        "continuation_bg_padding_y": _i("reading", "continuation_bg_padding_y", 12),
        # Reading "pre-pause": hold the silent frame (image + sentence) before the
        # narration of each reading scene (except the first), so the learner can read
        # first. The book icon (relative to assets_dir) is shown top-left meanwhile.
        "read_pre_pause_ms":         _i("reading", "pre_pause_ms",             2000),
        "pre_pause_icon":            _p("reading", "pre_pause_icon",           "icons/book.png"),
        "pre_pause_icon_size":       _i("reading", "pre_pause_icon_size",      150),
        "pre_pause_icon_margin_x":   _i("reading", "pre_pause_icon_margin_x",  50),
        "pre_pause_icon_margin_y":   _i("reading", "pre_pause_icon_margin_y",  50),

        # Audio / ElevenLabs
        "elevenlabs_model":        _p("audio", "elevenlabs_model", "eleven_multilingual_v2"),
        "audio_format":            _p("audio", "output_format",    "mp3_44100_128"),
        "repetition_pause_factor": _f("repetition", "pause_factor", 1.3),

        # Song video type — sing-along lyric videos from a finished audio file.
        # image_interval drives how often the illustration changes; the STT keys pick
        # the ElevenLabs Scribe model/language used to transcribe the lyrics with
        # word-level timestamps. line_gap / max_line_chars group words into subtitle lines.
        "song_image_interval_ms": int(_f("song", "image_interval_seconds", 5.0) * 1000),
        "song_stt_model":         _p("song", "stt_model",       "scribe_v1"),
        # A workspace that did not override it transcribes in its own language.
        "song_stt_language":      ((ws_settings.get("song") or {}).get("stt_language")
                                   or (lang["stt"] if ws else _p("song", "stt_language", "deu"))),
        "song_line_gap_s":        _f("song", "line_gap_seconds", 0.6),
        "song_max_line_chars":    _i("song", "max_line_chars",   42),

        # Podcast video type — horizontal episode + vertical Shorts of the best moments.
        "podcast_shorts_count":        _i("podcast", "shorts_count",      3),
        "podcast_short_min_lines":     _i("podcast", "short_min_lines",   4),
        "podcast_short_max_lines":     _i("podcast", "short_max_lines",   10),
        "podcast_short_label":         _p("podcast", "short_label",       "Brezel Podcast"),
        "podcast_short_cta_text":      _p("podcast", "short_cta_text",
                                          "Ganze Folge: Link in der Beschreibung"),
        "podcast_short_cta_seconds":   _f("podcast", "short_cta_seconds", 2.5),
        "podcast_short_bg_audio_name": (_p("podcast", "short_bg_audio_name", "") or "").strip(),
        "podcast_short_bg_audio_gain_db": _f("podcast", "short_bg_audio_gain_db", 0.0),
        "podcast_full_episode_url":    (_p("podcast", "full_episode_url", "") or "").strip(),

        # Script / GPT
        "script_model": _p("script", "openai_model", "gpt-4.1-mini"),
        # Manifest review / GPT (review_manifest.py)
        "review_model": _p("review", "openai_model", "gpt-4.1"),
        "level":        _p("script", "level",         "B1"),
        # Max distinct characters composited into one scene image (multi-character types).
        "max_scene_characters": _i("script", "max_scene_characters", 2),
        # Long dialogs are generated/evaluated in chunks of this many lines so a single
        # request never hits the model's output-token ceiling (see create_script.py).
        "dialog_batch_size": _i("script", "dialog_batch_size", 40),

        # fal.ai images
        "fal_models":     fal_models,
        "fal_model":      fal_models.get(raw_fal_model, raw_fal_model),
        "fal_t2i_model":  _p("fal", "t2i_model",  "fal-ai/bytedance/seedream/v5/lite/text-to-image"),
        "fal_image_size": _p("fal", "image_size", "portrait_16_9"),

        # Grammar-annotated subtitle spacing: past `long_text_threshold` characters
        # the renderer uses the tighter `row_gap_compact` between wrapped rows so a
        # long sentence stays short enough to clear the top overlays (Teil / icon).
        "annotated_row_gap":            _i("annotated_subtitles", "annotated_row_gap",            30),
        "annotated_row_gap_compact":    _i("annotated_subtitles", "annotated_row_gap_compact",    12),
        "annotated_long_text_threshold": _i("annotated_subtitles", "annotated_long_text_threshold", 60),
        "annotated_long_text_scale":    _f("annotated_subtitles", "annotated_long_text_scale",    0.8),

        # Image prompt style tokens
        "image_style_tokens": _p(
            "image_prompts", "style_tokens",
            "children's illustration book style, smooth watercolor washes, "
            "thick clean outlines, soft pastel palette.",
        ),
        "image_framing_tokens": _p(
            "image_prompts", "framing_tokens",
            "vertical 9:16 composition. Characters centred in frame.",
        ),
        "image_character_art_style": _p(
            "image_prompts", "character_art_style",
            "children's illustration book style, smooth watercolor washes, "
            "thick clean outlines, soft pastel palette, white background, no text, no watermarks",
        ),
        "image_location_art_style": _p(
            "image_prompts", "location_art_style",
            "children's illustration book style, smooth watercolor washes, "
            "thick clean outlines, soft pastel palette. "
            "No people, no characters, no text, no watermarks. Vertical 9:16 composition.",
        ),

        # ComfyUI (kept for backwards compatibility)
        "comfyui_host": _p("comfyui", "host", "127.0.0.1"),
        "comfyui_port": _i("comfyui", "port", 8000),
    }


def apply_video_format(cfg: dict, video_format: str) -> dict:
    """Override cfg in place with the [vertical] / [horizontal] section for this format.

    Orientation sections in config.ini use the same internal key names as the flat cfg
    dict (e.g. target_w, target_h, sub_fontsize, nar_fontsize, sub_margin_bottom,
    icon_x, icon_y, fal_image_size). Each override is cast to the type of the existing
    base value, so a string stays a string and a number stays a number. Unknown keys
    are stored as strings. Returns cfg for chaining.

    Call this once per render after load_config(), passing the project's video_format.
    """
    # Remember which orientation is active so per-orientation scene assets (e.g. the
    # podcast studio's image.file_path_vertical) can be picked at render time.
    cfg["active_video_format"] = video_format
    overrides = (cfg.get("video_formats") or {}).get(video_format, {})
    for key, raw in overrides.items():
        if raw is None:
            continue
        base = cfg.get(key)
        try:
            if isinstance(base, bool):                    # bool before int (bool ⊂ int)
                cfg[key] = str(raw).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(base, int):
                cfg[key] = int(raw)
            elif isinstance(base, float):
                cfg[key] = float(raw)
            else:
                cfg[key] = raw
        except (TypeError, ValueError):
            logger.warning("Bad [%s] override %s=%r — keeping base %r", video_format, key, raw, base)
    return cfg


# =============================================================================
# Asset catalog loaders (backed by data/pipeline.db — see db.py)
# =============================================================================
# `assets_dir` picks the workspace whose assets folder it is (the active one when
# it matches none), so callers keep passing cfg["assets_dir"] as before.

def _active_workspace() -> dict | None:
    try:
        return db.active_workspace()
    except Exception as e:                      # unreadable DB → plain config.ini
        logger.warning("Workspace DB unavailable (%s) — using config.ini only", e)
        return None


def workspace_for_assets_dir(assets_dir: Path | None) -> str | None:
    if assets_dir is not None:
        target = Path(assets_dir).resolve()
        for ws in db.list_workspaces():
            if Path(ws["assets_dir"]).resolve() == target:
                return ws["slug"]
    return db.active_workspace_slug()


def load_new_characters(assets_dir: Path) -> dict[str, Any]:
    """Characters of the workspace (fixed/variable descriptions, art paths, voice)."""
    return db.load_assets("characters", workspace_for_assets_dir(assets_dir))


def load_new_locations(assets_dir: Path) -> dict[str, Any]:
    """Locations of the workspace (description, creation_prompt, art path)."""
    return db.load_assets("locations", workspace_for_assets_dir(assets_dir))


def load_project_types(assets_dir: Path) -> dict[str, Any]:
    """Project types (prompts + scene builder rules) of the workspace."""
    return db.load_assets("project_types", workspace_for_assets_dir(assets_dir))


def load_video_clips(assets_dir: Path) -> dict[str, Any]:
    """Branding video clips (intros/outros) of the workspace."""
    return db.load_assets("video_clips", workspace_for_assets_dir(assets_dir))


def load_background_audio_index(assets_dir: Path | None = None) -> dict[str, Any]:
    """Shared background-music library; full_path is relative to library_dir."""
    return db.load_assets("background_audio")


def load_sfx_index(assets_dir: Path | None = None) -> dict[str, Any]:
    """Shared SFX library; full_path is relative to library_dir."""
    return db.load_assets("sfx")


def resolve_asset_path(assets_dir: Path, relative_path: str) -> Path:
    """
    Resolve a relative asset path (as stored in the catalog) to a Path.

    Example: resolve_asset_path(assets_dir, "characters/Zahra/art.png")
             → Path("assets/characters/Zahra/art.png")
    """
    return assets_dir / relative_path


def get_new_locations_flat(assets_dir: Path) -> dict[str, Any]:
    """
    Return a flat dict of all location keys including sub_locations.

    Example: {"cafe": {...}, "cafe_single_1": {...}, ...}
    """
    locations = load_new_locations(assets_dir)
    flat: dict[str, Any] = {}
    for key, loc in locations.items():
        flat[key] = loc
        for sub_key, sub_loc in loc.get("sub_locations", {}).items():
            flat[sub_key] = sub_loc
    return flat

def cache_key_for_pair(char_a: str, char_b: str, location_key: str) -> str:
    """
    Return the canonical cache filename stem for a two-character scene.
    Characters are sorted alphabetically to prevent duplicates.

    Example: cache_key_for_pair("Zahra", "Amir", "cafe") -> "Amir_Zahra__cafe"
    """
    a, b = sorted([char_a, char_b])
    return f"{a}_{b}__{location_key}"


def cache_key_for_single(char: str, location_key: str) -> str:
    """
    Return the canonical cache filename stem for a single-character scene.

    Example: cache_key_for_single("Wiebke", "cafe_single_2") -> "Wiebke__cafe_single_2"
    """
    return f"{char}__{location_key}"