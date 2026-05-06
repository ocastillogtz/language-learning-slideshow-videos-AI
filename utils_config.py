"""
utils_config.py
===============
Central config loader for the language-learning video pipeline.

All other modules import from here — no module reads config.ini directly.
"""

import configparser
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.ini")


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """
    Parse config.ini and return a flat dict of all pipeline parameters.
    Paths are returned as Path objects. Missing optional keys return None.
    """
    cfg = configparser.RawConfigParser()
    cfg.read(config_path)

    def _p(section: str, key: str, fallback=None):
        return cfg.get(section, key, fallback=fallback)

    def _i(section: str, key: str, fallback: int = 0) -> int:
        return cfg.getint(section, key, fallback=fallback)

    def _f(section: str, key: str, fallback: float = 0.0) -> float:
        return cfg.getfloat(section, key, fallback=fallback)

    projects_dir = Path(_p("paths", "projects_dir", "projects"))
    assets_dir   = Path(_p("paths", "assets_dir",   "assets"))

    return {
        # Directories
        "projects_dir":   projects_dir,
        "assets_dir":     assets_dir,

        # Subdirectory shortcuts — all derived from assets_dir
        "background_audio_dir": assets_dir / "background_audio",
        "branding_dir":         assets_dir / "branding",
        "character_art_dir":    assets_dir / "character_art",
        "character_art_cache_dir": assets_dir / "character_art_cache",
        "location_dir":         assets_dir / "location",
        "sfx_dir":              assets_dir / "sfx",
        "audio_cache_dir":      assets_dir / "audio_cache",

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
        "markup_italic_attrs":   _p("subtitles", "markup_italic_attrs",  'font_style="italic"'),
        "markup_italic_colors":  [
            c.strip() for c in
            _p("subtitles", "markup_italic_colors",
               "#FFD700,#DBB900,#FFDD24,#B89B00,#FFE247").split(",")
            if c.strip()
        ],
        "markup_bold_attrs":     _p("subtitles", "markup_bold_attrs",   'weight="bold"'),


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

        # Assembly
        "bg_audio_volume":    _f("assembly", "bg_audio_volume",    0.18),
        "crossfade_s":        _f("assembly", "crossfade_s",        0.35),
        "bg_audio_fadein_s":  _f("assembly", "bg_audio_fadein_s",  1.0),
        "bg_audio_fadeout_s": _f("assembly", "bg_audio_fadeout_s", 2.0),
        "speed_factor":       _f("assembly", "speed_factor",       1.0),

        # Audio / ElevenLabs
        "elevenlabs_model":        _p("audio", "elevenlabs_model", "eleven_multilingual_v2"),
        "audio_format":            _p("audio", "output_format",    "mp3_44100_128"),
        "repetition_pause_factor": _f("repetition", "pause_factor", 1.3),

        # Script / GPT
        "script_model": _p("script", "openai_model", "gpt-4.1-mini"),
        "level":        _p("script", "level",         "B1"),

        # fal.ai images
        "fal_model":      _p("fal", "model",      "fal-ai/bytedance/seedream/v4.5/edit"),
        "fal_t2i_model":  _p("fal", "t2i_model",  "fal-ai/bytedance/seedream/v5/lite/text-to-image"),
        "fal_image_size": _p("fal", "image_size", "portrait_16_9"),

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


def load_characters(assets_dir: Path) -> dict[str, Any]:
    """Load and return the characters.json dict."""
    path = assets_dir / "characters.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_locations(assets_dir: Path) -> dict[str, Any]:
    """Load and return the locations.json dict (top-level locations only)."""
    path = assets_dir / "locations.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_locations_flat(locations: dict[str, Any]) -> dict[str, Any]:
    """
    Return a flat dict of all location keys including sub_locations,
    so callers can look up any key without knowing the nesting level.

    Example: {"cafe": {...}, "cafe_single_1": {...}, "cafe_single_2": {...}, ...}
    """
    flat: dict[str, Any] = {}
    for key, loc in locations.items():
        flat[key] = loc
        for sub_key, sub_loc in loc.get("sub_locations", {}).items():
            flat[sub_key] = sub_loc
    return flat


# =============================================================================
# New asset loaders (new architecture)
# =============================================================================

def load_assets_registry(assets_dir: Path) -> dict[str, Any]:
    """Load and return assets/assets.json — the master asset registry."""
    path = assets_dir / "assets.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_new_characters(assets_dir: Path) -> dict[str, Any]:
    """Load assets/characters/characters.json (new schema with fixed/variable descriptions)."""
    path = assets_dir / "characters" / "characters.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_new_locations(assets_dir: Path) -> dict[str, Any]:
    """Load assets/locations/locations.json (new schema with creation_prompt)."""
    path = assets_dir / "locations" / "locations.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_project_types(assets_dir: Path) -> dict[str, Any]:
    """Load assets/project_types/project_types.json."""
    path = assets_dir / "project_types" / "project_types.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_video_clips(assets_dir: Path) -> dict[str, Any]:
    """Load assets/video_clips/video_clips.json."""
    path = assets_dir / "video_clips" / "video_clips.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_background_audio_index(assets_dir: Path) -> dict[str, Any]:
    """Load assets/background_audio/background_audio.json."""
    path = assets_dir / "background_audio" / "background_audio.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sfx_index(assets_dir: Path) -> dict[str, Any]:
    """Load assets/sfx/sfx.json."""
    path = assets_dir / "sfx" / "sfx.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_asset_path(assets_dir: Path, relative_path: str) -> Path:
    """
    Resolve a relative asset path (as stored in JSON) to an absolute Path.

    Example: resolve_asset_path(assets_dir, "sfx/bell.mp3")
             → Path("assets/sfx/bell.mp3")
    """
    return assets_dir / relative_path


def get_new_locations_flat(assets_dir: Path) -> dict[str, Any]:
    """
    Return a flat dict of all location keys including sub_locations.
    Uses the new locations.json schema.

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