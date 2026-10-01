"""
platform_audio.py
=================
Per-platform background music.

YouTube Audio Library tracks are fine on YouTube but get long videos blocked on
Instagram/Facebook, so the assemblers can render one variant per platform, each
with its own background track and volume:

    final_<project>_YT.mp4      always (the default / fallback variant)
    final_<project>_Meta.mp4    only when a Meta track is chosen
    final_<project>_TikTok.mp4  prepared — only when a TikTok track is chosen

A "bg_tracks" spec is a dict {platform: {"name": str, "gain_db": float}}; a
platform whose name is blank is skipped. YouTube always renders (its name may be
blank = no music). Tracks are tagged in background_audio.json with
"license": "YTsafe" / "Metasafe" (/ "TikToksafe").
"""

from pathlib import Path

# platform key -> (filename suffix, track license tag, UI label)
PLATFORMS = {
    "yt":     ("_YT",     "YTsafe",     "YouTube"),
    "meta":   ("_Meta",   "Metasafe",   "Meta (Instagram/Facebook)"),
    "tiktok": ("_TikTok", "TikToksafe", "TikTok"),
}
PLATFORM_ORDER = ("yt", "meta", "tiktok")


def normalize_bg_tracks(bg_tracks=None, default_name="", default_gain_db=0.0):
    """Return [(platform, name, gain_db), ...] in render order.

    The YouTube entry is always present; a blank name/gain falls back to
    default_name/default_gain_db (the legacy single bg_audio_name/bg_audio_gain_db
    or the config default). Meta/TikTok are only included when a track name is set."""
    bg_tracks = bg_tracks or {}
    out = []
    for p in PLATFORM_ORDER:
        spec = bg_tracks.get(p) or {}
        name = (spec.get("name") or "").strip()
        gain = spec.get("gain_db")
        if p == "yt":
            if not name:
                name = (default_name or "").strip()
            if gain in (None, ""):
                gain = default_gain_db
        elif not name:
            continue
        out.append((p, name, float(gain or 0.0)))
    return out


def parse_bg_tracks(raw):
    """Clean a bg_tracks dict from a request/CLI. Returns None if nothing usable."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for p in PLATFORM_ORDER:
        spec = raw.get(p)
        if not isinstance(spec, dict):
            continue
        name = (spec.get("name") or "").strip()
        g    = spec.get("gain_db")
        out[p] = {"name": name, "gain_db": float(g) if g not in (None, "") else None}
    return out or None


def platform_path(base_path: Path, platform: str) -> Path:
    """final_x.mp4 -> final_x_YT.mp4 (etc.)."""
    base_path = Path(base_path)
    return base_path.with_name(base_path.stem + PLATFORMS[platform][0] + base_path.suffix)


def find_variant(base_path: Path, prefer=("yt",)) -> Path:
    """Existing file for the first preferred platform, else the legacy un-suffixed
    file, else the first preferred platform's path (for error messages)."""
    base_path = Path(base_path)
    for p in prefer:
        cand = platform_path(base_path, p)
        if cand.exists():
            return cand
    if base_path.exists():
        return base_path
    return platform_path(base_path, prefer[0])


def remove_stale_variants(base_path: Path, keep) -> list[Path]:
    """Delete platform variants of base_path that are not in `keep`. Called when a
    fresh render is written: a leftover _Meta from an earlier run (whose Meta track
    was since dropped) would otherwise be preferred by the Meta uploads even though
    its video is outdated. Returns the removed paths."""
    removed = []
    for p in PLATFORM_ORDER:
        cand = platform_path(base_path, p)
        if p not in keep and cand.exists():
            cand.unlink()
            removed.append(cand)
    return removed


def any_variant_exists(base_path: Path) -> bool:
    return Path(base_path).exists() or any(
        platform_path(base_path, p).exists() for p in PLATFORM_ORDER)


# Upload preferences: Meta uploads use the Meta variant, falling back to YouTube's.
YOUTUBE_PREFER = ("yt",)
META_PREFER    = ("meta", "yt")
TIKTOK_PREFER  = ("tiktok", "yt")
