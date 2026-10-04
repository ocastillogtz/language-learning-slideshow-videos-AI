"""
music_level.py
==============
Suggested background-music gain for a project, so the per-video "Volume (dB)"
doesn't have to be guessed.

How loud the music ends up in a finished video:

    music_in_mix = track_mean + 20·log10(bg_audio_volume) + gain_db

The suggestion picks gain_db so the music sits `music_below_voice_db` under the
project's own voices (median level of its spoken clips):

    gain_db = voice − music_below_voice_db − (track_mean + 20·log10(bg_audio_volume))

Defaults come from the projects you mixed by ear (2026-10-03, 40 assembled
videos): music ended up a median of 20 dB under the voices for dialog/story
videos and ~11 dB under for quizzes. config.ini [assembly] music_below_voice_db
holds the default; a project type can override it with "music_below_voice_db".
"""

import json
import math
import statistics
from pathlib import Path

import audio_tools
from utils_config import load_config, load_project_types

TYPICAL_VOICE_DB = -22.0      # median of ElevenLabs lines across the existing projects


def spoken_clips(project_dir: Path, limit: int = 8) -> list[Path]:
    """A project's voiced scene clips that hold a real sentence (not a short blip)."""
    clips = [c for c in sorted((project_dir / "audio").glob("scene_*.mp3")) if c.stat().st_size > 30_000]
    return clips[:limit]


def latest_voice_clip(projects_dir: Path) -> Path | None:
    """A spoken line from the most recently changed project (volume-tool previews)."""
    if not projects_dir.exists():
        return None
    manifests = sorted(projects_dir.glob("*/project_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for mp in manifests[:15]:
        clips = spoken_clips(mp.parent, 1)
        if clips:
            return clips[0]
    return None


_voice_cache: dict[tuple[str, float], float | None] = {}


def voice_level(project_dir: Path, max_clips: int = 8) -> float | None:
    """Median level (dB) of a project's spoken clips; None before audio exists.
    Cached per project until its audio folder changes (re-voiced lines)."""
    audio = project_dir / "audio"
    stamp = audio.stat().st_mtime if audio.exists() else 0.0
    ck = (str(project_dir.resolve()), stamp)
    if ck in _voice_cache:
        return _voice_cache[ck]
    levels = []
    for c in spoken_clips(project_dir, max_clips):
        try:
            levels.append(audio_tools.measure(c)["mean_db"])
        except Exception:
            pass
    _voice_cache[ck] = round(statistics.median(levels), 1) if levels else None
    return _voice_cache[ck]


def target_gap(project_type_key: str | None) -> float:
    cfg = load_config()
    gap = cfg["music_below_voice_db"]
    if project_type_key:
        types = load_project_types(cfg["assets_dir"])
        t = types.get(project_type_key) or {}
        base = types.get(t.get("base_type") or "") or {}
        gap = t.get("music_below_voice_db", base.get("music_below_voice_db", gap))
    return float(gap)


def track_mean(name: str) -> float | None:
    """Average level of a library track (measured once, cached in its catalog entry)."""
    import db
    t = db.load_assets("background_audio").get(name)
    if not t:
        return None
    if not t.get("loudness"):
        loud = audio_tools.measure(load_config()["library_dir"] / t["full_path"])

        def _store(music):
            if name in music:
                music[name]["loudness"] = loud
        db.update_assets("background_audio", _store)
        return loud["mean_db"]
    return t["loudness"]["mean_db"]


def suggest(voice_db: float, gap_db: float, track_db: float) -> float:
    bg = 20 * math.log10(load_config()["bg_audio_volume"])
    return round((voice_db - gap_db - (track_db + bg)) * 2) / 2      # 0.5 dB steps


def project_suggestion(project_name: str, tracks: list[str]) -> dict:
    cfg = load_config()
    pdir = Path(cfg["projects_dir"]) / project_name
    meta = (json.loads((pdir / "project_manifest.json").read_text(encoding="utf-8"))
            .get("project_metadata") or {})
    measured = voice_level(pdir)
    voice = measured if measured is not None else TYPICAL_VOICE_DB
    gap = target_gap(meta.get("project_type_key"))
    out = {}
    for name in tracks:
        m = track_mean(name) if name else None
        if m is not None:
            out[name] = {"track_mean_db": m, "suggested_gain_db": suggest(voice, gap, m)}
    return {
        "voice_db": voice,
        "voice_measured": measured is not None,
        "music_below_voice_db": gap,
        "bg_audio_volume_db": round(20 * math.log10(cfg["bg_audio_volume"]), 1),
        "tracks": out,
    }


def library_suggestion(name: str, gap_db: float | None = None) -> float | None:
    """Gain a track typically needs in a video (typical voice, default gap)."""
    m = track_mean(name)
    if m is None:
        return None
    return suggest(TYPICAL_VOICE_DB, load_config()["music_below_voice_db"] if gap_db is None else gap_db, m)
