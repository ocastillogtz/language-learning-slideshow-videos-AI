"""
assemble_video.py

Concatenate per-scene clips into a final video.

Steps:
  1. Load scene order from project_manifest.json
  2. Collect videos/<scene_id>.mp4 in order (sfx clips included)
  3. Concatenate with optional crossfade at branding joints
  4. Mix in background audio at low volume (looped, main content only)
  5. Prepend intro and/or append outro with crossfade (controlled by --branding)
  6. Write final video to projects/<project>/final_<project_name>.mp4

Usage:
    python assemble_video.py <project_name>
    python assemble_video.py <project_name> --branding both
    python assemble_video.py <project_name> --branding intro
    python assemble_video.py <project_name> --branding outro
    python assemble_video.py <project_name> --branding none

Branding assets expected at:
    assets/branding/intro.mp4
    assets/branding/outro.mp4

Background audio expected at:
    assets/bg/<name>.mp3   (default: office.mp3)
"""

import json
import logging
import argparse
import configparser
from pathlib import Path

import numpy as np
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.config import change_settings

# =========================
# CONFIG
# =========================
FPS               = 30
BG_AUDIO_VOLUME   = 0.40    # 8% — audible but never competing with speech
CROSSFADE_S       = 0.35    # crossfade duration at branding joints
BG_AUDIO_FADEIN_S = 1.0
BG_AUDIO_FADEOUT_S = 2.0
LOG_LEVEL         = logging.INFO

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)

    projects_dir  = Path(config["paths"]["projects_dir"])
    assets_dir    = Path(config["paths"]["assets_dir"])

    if config.has_option("tools", "imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": config["tools"]["imagemagick"]})

    return projects_dir, assets_dir

# =========================
# BACKGROUND AUDIO
# =========================
def build_bg_audio(bg_path: Path, target_duration: float):
    """
    Load bg audio, loop it to cover target_duration, apply volume + fade.
    Avoids to_soundarray() which breaks on newer numpy versions.
    Uses concatenate_audioclips to loop instead.
    """
    bg = AudioFileClip(str(bg_path))

    # How many full copies do we need to cover target_duration?
    repeats = int(target_duration / bg.duration) + 2
    looped  = concatenate_audioclips([bg] * repeats)
    looped  = looped.subclip(0, target_duration)
    looped  = looped.volumex(BG_AUDIO_VOLUME)
    looped  = looped.audio_fadein(BG_AUDIO_FADEIN_S)
    looped  = looped.audio_fadeout(BG_AUDIO_FADEOUT_S)

    return looped

# =========================
# CROSSFADE JOIN
# =========================
def crossfade_join(clip_a: VideoFileClip, clip_b: VideoFileClip, duration: float):
    """
    Join two clips with a crossfade of `duration` seconds.
    clip_a fades out, clip_b fades in, they overlap in time.
    moviepy 1.x: use crossfadeout / crossfadein then concatenate with padding.
    """
    a = clip_a.crossfadeout(duration)
    b = clip_b.crossfadein(duration)
    return concatenate_videoclips([a, b], padding=-duration, method="compose")

# =========================
# MAIN
# =========================
def assemble_video(
    project_name: str,
    branding: str = "both",       # "both" | "intro" | "outro" | "none"
    bg_audio_name: str = "office",
    overwrite: bool = False,
):
    projects_dir, assets_dir = load_config()
    project_path  = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    videos_dir    = project_path / "videos"
    branding_dir  = assets_dir / "branding"
    bg_audio_path = assets_dir / "bg" / f"{bg_audio_name}.mp3"

    out_path = project_path / f"final_{project_name}.mp4"

    if out_path.exists() and not overwrite:
        logger.info(f"Output already exists: {out_path} — use --overwrite to replace")
        return

    # ----------------------------------------------------------------
    # COLLECT SCENE CLIPS IN ORDER
    # ----------------------------------------------------------------
    scenes     = manifest["scenes"]
    clip_paths = []

    for scene in scenes:
        scene_id   = scene["id"]
        scene_type = scene["type"]

        # Every scene type now has a video file (sfx included from create_video)
        clip_path = videos_dir / f"{scene_id}.mp4"

        if not clip_path.exists():
            logger.warning(f"Missing clip for {scene_id} ({scene_type}) — skipping")
            continue

        clip_paths.append(clip_path)

    if not clip_paths:
        raise RuntimeError("No scene clips found in videos/ — run create_video first")

    logger.info(f"Assembling {len(clip_paths)} scene clips...")

    # ----------------------------------------------------------------
    # LOAD AND CONCATENATE SCENE CLIPS
    # ----------------------------------------------------------------
    scene_clips = [VideoFileClip(str(p)) for p in clip_paths]
    content     = concatenate_videoclips(scene_clips, method="compose")

    logger.info(f"Content duration: {content.duration:.1f}s")

    # ----------------------------------------------------------------
    # BACKGROUND AUDIO (main content only, not under branding)
    # ----------------------------------------------------------------
    if bg_audio_path.exists():
        logger.info(f"Mixing background audio: {bg_audio_path.name}")
        bg_audio = build_bg_audio(bg_audio_path, content.duration)

        if content.audio is not None:
            mixed = CompositeAudioClip([content.audio, bg_audio])
        else:
            mixed = bg_audio

        content = content.set_audio(mixed)
    else:
        logger.warning(f"Background audio not found: {bg_audio_path} — skipping")

    # ----------------------------------------------------------------
    # BRANDING
    # ----------------------------------------------------------------
    use_intro = branding in ("both", "intro")
    use_outro = branding in ("both", "outro")

    intro_path = branding_dir / "intro.mp4"
    outro_path = branding_dir / "outro.mp4"

    if use_intro and not intro_path.exists():
        logger.warning(f"Intro not found at {intro_path} — skipping intro")
        use_intro = False

    if use_outro and not outro_path.exists():
        logger.warning(f"Outro not found at {outro_path} — skipping outro")
        use_outro = False

    final = content

    if use_intro:
        logger.info("Attaching intro with crossfade...")
        intro = VideoFileClip(str(intro_path))
        final = crossfade_join(intro, final, CROSSFADE_S)

    if use_outro:
        logger.info("Attaching outro with crossfade...")
        outro = VideoFileClip(str(outro_path))
        final = crossfade_join(final, outro, CROSSFADE_S)

    # ----------------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------------
    logger.info(f"Writing final video: {out_path.name} ({final.duration:.1f}s)")

    final.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(project_path / "final_tmp_audio.m4a"),
        remove_temp=True,
        logger=None,
    )

    # Cleanup
    for c in scene_clips:
        c.close()
    final.close()

    logger.info(f"Done: {out_path}")

# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Assemble final video from scene clips")

    parser.add_argument(
        "project_name",
        help="Project name"
    )
    parser.add_argument(
        "--branding",
        choices=["both", "intro", "outro", "none"],
        default="both",
        help="Which branding clips to attach (default: both)"
    )
    parser.add_argument(
        "--bg-audio",
        default="office",
        help="Background audio filename without extension (default: office)"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing final video"
    )

    args = parser.parse_args()

    assemble_video(
        project_name=args.project_name,
        branding=args.branding,
        bg_audio_name=args.bg_audio,
        overwrite=args.overwrite,
    )

# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    assemble_video("coffee_convo_1",bg_audio_name="coffeeshop",branding="intro")
