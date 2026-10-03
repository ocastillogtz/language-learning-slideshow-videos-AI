"""
audio_tools.py
==============
ffmpeg helpers behind the background-music volume tool in the Assets view.

  measure(path)            → duration + mean / peak level (ffmpeg volumedetect)
  preview_segment(...)     → MP3 bytes of a short slice from the MIDDLE of a track
                             with a gain applied, optionally mixed under a voice
                             line at the level the assembler uses — so you can hear
                             whether the new volume works before committing to it
  apply_gain(src, dst, db) → re-encode the whole track with that gain (MP3); a soft
                             limiter stops boosted peaks from clipping

Gains are always applied to the ORIGINAL upload (kept next to the track), so
adjusting several times never stacks re-encoding losses.
"""

import re
import subprocess
from pathlib import Path

FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".mkv"}


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kw)


def duration_s(path: Path) -> float:
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)], text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not read audio from {path.name}: {r.stderr.strip()[-300:]}")


def measure(path: Path) -> dict:
    """{'duration_s', 'mean_db', 'peak_db'} — mean/peak in dBFS (0 = full scale)."""
    r = _run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-vn",
              "-af", "volumedetect", "-f", "null", "-"], text=True, errors="replace")
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    if not mean or not peak:
        raise RuntimeError(f"Could not analyse {path.name}: {r.stderr.strip()[-300:]}")
    return {"duration_s": round(duration_s(path), 2),
            "mean_db": float(mean.group(1)), "peak_db": float(peak.group(1))}


def preview_segment(path: Path, gain_db: float = 0.0, seconds: float = 15.0,
                    voice: Path | None = None, music_volume: float = 1.0) -> bytes:
    """MP3 bytes of `seconds` taken from the middle of `path` with `gain_db` applied.

    With `voice`, the music is scaled by `music_volume` (the assembler's
    bg_audio_volume) and mixed under the voice line, starting 1 s in — roughly what
    a finished video sounds like."""
    total = duration_s(path)
    seconds = max(3.0, min(seconds, total))
    start = max(0.0, total / 2 - seconds / 2)
    gain = 10 ** (gain_db / 20) * (music_volume if voice else 1.0)

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", str(path)]
    if voice:
        cmd += ["-i", str(voice), "-filter_complex",
                f"[0:a]volume={gain:.5f},afade=t=in:d=0.5[m];"
                f"[1:a]adelay=1000|1000[v];[m][v]amix=inputs=2:duration=first:normalize=0[out]",
                "-map", "[out]"]
    else:
        cmd += ["-vn", "-af", f"volume={gain:.5f},afade=t=in:d=0.3"]
    cmd += ["-ac", "2", "-c:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "-"]
    r = _run(cmd)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:] or "ffmpeg failed")
    return r.stdout


def apply_gain(src: Path, dst: Path, gain_db: float) -> None:
    """Write `src` with `gain_db` applied to `dst` (MP3, 192 kbps). Video streams
    (an .mp4 upload) are dropped; a limiter keeps boosted peaks below 0 dBFS."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp.mp3")
    af = f"volume={gain_db:.2f}dB"
    if gain_db > 0:
        af += ",alimiter=limit=0.97:level=false"
    r = _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn",
              "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", str(tmp)])
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:] or "ffmpeg failed")
    tmp.replace(dst)
