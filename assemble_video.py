"""
assemble_video.py
=================
Concatenates per-scene clips into the final video with optional background audio,
speed adjustment, and branding clip (intro/outro).
"""

import json
import logging
import argparse
import subprocess
from pathlib import Path
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeAudioClip,
    concatenate_videoclips, concatenate_audioclips,
)
from moviepy.config import change_settings
from utils_config import load_config, load_background_audio_index

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def assemble_video(
    project_name,
    bg_audio_name="office",
    overwrite=False,
    speed_factor=None,
    branding_file=None,
    branding_mode="none",
):
    cfg          = load_config()
    assets_dir   = cfg["assets_dir"]
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if speed_factor is None:
        speed_factor = cfg.get("speed_factor", 1.0)
    speed_factor = float(speed_factor)

    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    videos_dir = project_path / "videos"
    out_path   = project_path / ("final_" + project_name + ".mp4")

    if out_path.exists() and not overwrite:
        logger.info("Output exists: %s -- use --overwrite to regenerate", out_path)
        return

    # Collect per-scene clips in scene order
    clip_paths = []
    for scene in manifest["scenes"]:
        p = videos_dir / (scene["id"] + ".mp4")
        if p.exists():
            clip_paths.append(p)
        else:
            logger.warning("Missing clip: %s -- skipping", scene["id"])

    if not clip_paths:
        raise RuntimeError("No clips found -- run create_video first")

    logger.info("Assembling %d clips ...", len(clip_paths))
    scene_clips = [VideoFileClip(str(p)) for p in clip_paths]
    content     = concatenate_videoclips(scene_clips, method="compose")

    # Background audio
    bg_audio_path = _resolve_bg_audio(bg_audio_name, assets_dir)

    if bg_audio_path and bg_audio_path.exists():
        logger.info("Background audio: %s", bg_audio_path.name)
        bg_clip   = AudioFileClip(str(bg_audio_path))
        repeats   = int(content.duration / bg_clip.duration) + 2
        bg_looped = concatenate_audioclips([AudioFileClip(str(bg_audio_path))] * repeats)
        bg_looped = bg_looped.subclip(0, content.duration)
        bg_looped = bg_looped.volumex(cfg["bg_audio_volume"])
        bg_looped = bg_looped.audio_fadein(cfg["bg_audio_fadein_s"])
        bg_looped = bg_looped.audio_fadeout(cfg["bg_audio_fadeout_s"])
        mixed     = CompositeAudioClip([content.audio, bg_looped]) if content.audio else bg_looped
        content   = content.set_audio(mixed)
    else:
        logger.warning("Background audio not found for key '%s' -- skipping", bg_audio_name)

    # MoviePy write — to temp file if speed or branding will follow
    apply_speed    = abs(speed_factor - 1.0) > 1e-4
    apply_branding = bool(branding_file) and branding_mode and branding_mode != "none"
    needs_postpass = apply_speed or apply_branding

    moviepy_target = (
        project_path / ("final_" + project_name + "_raw.mp4")
        if needs_postpass else out_path
    )

    logger.info("Writing %s (%.1fs) ...", moviepy_target.name, content.duration)
    content.write_videofile(
        str(moviepy_target), fps=cfg["fps"], codec="libx264", audio_codec="aac",
        temp_audiofile=str(project_path / "final_tmp.m4a"),
        remove_temp=True, logger=None,
    )

    for c in scene_clips:
        c.close()
    content.close()

    # Optional speed pass
    if apply_speed:
        logger.info("Applying speed factor %.4f via FFmpeg ...", speed_factor)
        speed_out = project_path / ("final_" + project_name + "_spd.mp4")
        _ffmpeg_speed(moviepy_target, speed_out, speed_factor)
        moviepy_target.unlink(missing_ok=True)
        moviepy_target = speed_out
        logger.info("Speed pass complete -> %s", moviepy_target.name)

    # Optional branding concat
    if apply_branding:
        branding_path = cfg["branding_dir"] / branding_file
        if branding_path.exists():
            logger.info("Attaching branding (%s) as %s ...", branding_file, branding_mode)
            branded_out = project_path / ("final_" + project_name + "_branded.mp4")
            _ffmpeg_branding_concat(branding_path, moviepy_target, branded_out, branding_mode)
            moviepy_target.unlink(missing_ok=True)
            moviepy_target = branded_out
            logger.info("Branding pass complete -> %s", moviepy_target.name)
        else:
            logger.warning("Branding file not found: %s -- skipping", branding_path)

    # Move to final path if not already there
    if moviepy_target != out_path:
        if out_path.exists():
            out_path.unlink()
        moviepy_target.rename(out_path)

    logger.info("Done: %s", out_path)


def _ffmpeg_branding_concat(branding_path, content_path, out_path, mode):
    """
    Prepend and/or append a branding clip around the main content.

    mode: "intro"  -> branding + content
          "outro"  -> content + branding
          "both"   -> branding + content + branding
    """
    if mode == "intro":
        inputs = [str(branding_path), str(content_path)]
        n = 2
    elif mode == "outro":
        inputs = [str(content_path), str(branding_path)]
        n = 2
    elif mode == "both":
        inputs = [str(branding_path), str(content_path), str(branding_path)]
        n = 3
    else:
        raise ValueError("branding_mode must be intro, outro, or both")

    filter_inputs = "".join("[" + str(i) + ":v][" + str(i) + ":a]" for i in range(n))
    filter_str    = filter_inputs + "concat=n=" + str(n) + ":v=1:a=1[v][a]"

    cmd = (
        ["ffmpeg", "-y"]
        + [part for inp in inputs for part in ["-i", inp]]
        + [
            "-filter_complex", filter_str,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ]
    )
    logger.debug("FFmpeg branding cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg branding concat failed (exit " + str(result.returncode) + "):\n"
            + result.stderr[-1000:]
        )


def _ffmpeg_speed(in_path, out_path, speed_factor):
    """Re-encode with FFmpeg to change playback speed without pitch shift."""
    pts_multiplier = 1.0 / speed_factor
    atempo_chain   = _build_atempo_chain(speed_factor)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-vf", "setpts=" + str(round(pts_multiplier, 6)) + "*PTS",
        "-af", atempo_chain,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg speed pass failed (exit " + str(result.returncode) + "):\n"
            + result.stderr[-1000:]
        )


def _build_atempo_chain(speed_factor):
    filters   = []
    remaining = float(speed_factor)
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    filters.append("atempo=" + str(round(remaining, 6)))
    return ",".join(filters)


def _resolve_bg_audio(key, assets_dir):
    try:
        index = load_background_audio_index(assets_dir)
        if key in index:
            rel = index[key].get("file_path", "")
            if rel:
                return assets_dir / rel
    except Exception as e:
        logger.debug("Could not load background audio index: %s", e)

    fallback = assets_dir / "background_audio" / (key + ".mp3")
    return fallback if fallback.exists() else None


def main():
    p = argparse.ArgumentParser(description="Assemble per-scene clips into a final video.")
    p.add_argument("project_name")
    p.add_argument("--bg-audio", default="office", dest="bg_audio_name")
    p.add_argument("--speed-factor", type=float, default=None, dest="speed_factor",
                   help="Playback speed multiplier (0.95 = 5 percent slower)")
    p.add_argument("--branding-file", dest="branding_file", default=None,
                   help="Branding video filename from assets/branding/ (e.g. intro.mp4)")
    p.add_argument("--branding-mode", dest="branding_mode", default="none",
                   choices=["none", "intro", "outro", "both"])
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    assemble_video(
        a.project_name, a.bg_audio_name, a.overwrite, a.speed_factor,
        branding_file=a.branding_file, branding_mode=a.branding_mode,
    )


if __name__ == "__main__":
    main()
