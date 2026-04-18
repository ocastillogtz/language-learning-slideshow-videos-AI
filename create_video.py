"""
create_video.py
===============
Renders one .mp4 clip per scene in manifest["scenes"].

Scene types:
  narration        → narrator image + audio + subtitle (narrator style)
  dialog           → dialog image + audio + subtitle + character icon
  inter-pause      → freeze last frame, silent
  repetition-intro → freeze last frame + bitte_wiederholen audio
  bell             → freeze last frame + bell sfx
  repetition       → freeze last frame + repetition audio + subtitle
  after-pause      → freeze last frame, silent, duration from after-pause-ms

Style awareness:
  If manifest["style"] == "story", repetition/bell/after-pause scenes are
  already absent from manifest["scenes"] (built by create_script), so no
  special handling is needed here.

Annotated subtitles:
  Pass annotated_subtitles=True to create_videos() to render grammar-coloured
  annotated subtitles (via subtitle_renderer + generate_annotations) on dialog
  scenes instead of the plain TextClip subtitles.  Narrator subtitles are
  always rendered in plain style regardless of this flag.
  Default is False — existing behaviour is fully preserved.
"""

import json
import logging
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageFilter
from moviepy.editor import (
    ImageClip, TextClip, CompositeVideoClip,
    ColorClip, AudioFileClip,
)
from moviepy.config import change_settings
from utils_config import load_config, load_characters
from utils_image import pad_image_to_frame, blur_image, pil_to_numpy, make_icon_clip
from generate_annotations import generate_annotations
from subtitle_renderer import create_annotated_subtitle

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_videos(project_name: str, overwrite: bool = False, annotated_subtitles: bool = False) -> None:
    cfg          = load_config()
    chars_data   = load_characters(cfg["assets_dir"])
    assets_dir   = cfg["assets_dir"]
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    videos_dir = project_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    fps           = cfg["fps"]
    last_frame_np = None

    # Fixed audio assets — using sfx/ folder per file system overview
    sfx_dir   = assets_dir / "sfx"
    bell_path = sfx_dir / "bell.mp3"
    bw_path   = sfx_dir / "bitte_wiederholen.mp3"

    for scene in manifest["scenes"]:
        sid   = scene["id"]
        stype = scene["type"]
        out   = videos_dir / f"{sid}.mp4"

        if out.exists() and not overwrite:
            logger.info(f"Skipping {sid} (exists)")
            last_frame_np = _peek_last_frame(out, last_frame_np)
            continue

        logger.info(f"Rendering {sid} | {stype}")

        try:
            clip, last_frame_np = _build_clip(
                scene, stype, manifest, project_path, assets_dir,
                cfg, chars_data, last_frame_np, bell_path, bw_path,
                annotated_subtitles=annotated_subtitles,
            )
        except Exception as e:
            logger.error(f"Failed to build {sid}: {e}")
            continue

        if clip is None:
            logger.warning(f"No clip built for {sid}")
            continue

        try:
            clip.write_videofile(
                str(out), fps=fps, codec="libx264", audio_codec="aac",
                temp_audiofile=str(videos_dir / f"{sid}_tmp.m4a"),
                remove_temp=True, logger=None,
            )
            logger.info(f"  Saved: {out.name}")
        except Exception as e:
            logger.error(f"Failed to write {sid}: {e}")
        finally:
            clip.close()

    logger.info("create_video complete.")


def _build_clip(scene, stype, manifest, project_path, assets_dir,
                cfg, chars_data, last_frame_np, bell_path, bw_path,
                annotated_subtitles: bool = False):
    W, H = cfg["target_w"], cfg["target_h"]
    fps  = cfg["fps"]

    def freeze(duration_s: float, text: str = "", is_narrator: bool = False):
        if last_frame_np is not None:
            bg = ImageClip(last_frame_np).set_duration(duration_s)
        else:
            bg = ColorClip((W, H), (0, 0, 0)).set_duration(duration_s)
        layers = [bg]
        if text:
            sub  = _subtitle(text, duration_s, is_narrator, cfg)
            y    = H - cfg["sub_margin_bottom"] - sub.h
            layers += _sub_layers(sub, cfg["sub_margin_left"], y, duration_s, cfg)
        return CompositeVideoClip(layers, size=(W, H)).set_duration(duration_s)

    # ── narration ──────────────────────────────────────────────────────────
    if stype == "narration":
        narration = manifest["conversation"]["narration"]
        img_path  = project_path / narration["image"]
        dur_s     = (narration.get("duration-ms") or 3000) / 1000.0
        img       = Image.open(img_path).convert("RGB")
        frame     = pad_image_to_frame(img, cfg)
        frame_np  = pil_to_numpy(frame)
        bg        = ImageClip(frame_np).set_duration(dur_s)
        text      = narration.get("text", "").strip()
        layers    = [bg]
        if text:
            sub = _subtitle(text, dur_s, True, cfg)
            layers += _sub_layers(sub, cfg["sub_margin_left"], "center", dur_s, cfg)
        clip = CompositeVideoClip(layers, size=(W, H)).set_duration(dur_s)
        if narration.get("audio-file"):
            clip = _attach_audio(clip, project_path / narration["audio-file"], fps)
        return clip, frame_np

    # ── dialog ────────────────────────────────────────────────────────────
    if stype == "dialog":
        idx   = scene["index"]
        item  = manifest["conversation"]["dialog"][idx]
        img_p = project_path / item["image"]
        dur_s = (item.get("duration-ms") or 2000) / 1000.0
        img   = Image.open(img_p).convert("RGB")
        frame = pad_image_to_frame(img, cfg)
        fnp   = pil_to_numpy(frame)
        bg    = ImageClip(fnp).set_duration(dur_s)
        layers = [bg]
        icon = make_icon_clip(item["speaker"], chars_data, assets_dir, dur_s, cfg)
        if icon:
            layers.append(icon)
        text = item.get("text", "").strip()
        if text:
            if annotated_subtitles:
                layers += _annotated_sub_layers(text, dur_s, cfg, W, H)
            else:
                sub   = _subtitle(text, dur_s, False, cfg)
                sub_y = H - cfg["sub_margin_bottom"] - sub.h
                layers += _sub_layers(sub, cfg["sub_margin_left"], sub_y, dur_s, cfg)
        clip = CompositeVideoClip(layers, size=(W, H)).set_duration(dur_s)
        if item.get("audio-file"):
            clip = _attach_audio(clip, project_path / item["audio-file"], fps)
        return clip, fnp

    # ── inter-pause ───────────────────────────────────────────────────────
    if stype == "inter-pause":
        dur_s = scene.get("duration-ms", cfg["inter_pause_ms"]) / 1000.0
        clip  = freeze(dur_s)
        clip  = clip.set_audio(_silent(dur_s))
        return clip, last_frame_np

    # ── repetition-intro ──────────────────────────────────────────────────
    if stype == "repetition-intro":
        if not bw_path.exists():
            logger.warning(f"bitte_wiederholen not found: {bw_path}")
            return None, last_frame_np
        bw_audio = AudioFileClip(str(bw_path))
        clip = freeze(bw_audio.duration, text="Bitte wiederholen", is_narrator=True)
        clip = clip.set_audio(bw_audio)
        return clip, last_frame_np

    # ── bell ──────────────────────────────────────────────────────────────
    if stype == "bell":
        if not bell_path.exists():
            logger.warning(f"Bell audio not found: {bell_path}")
            return None, last_frame_np
        bell_audio = AudioFileClip(str(bell_path))
        clip = freeze(bell_audio.duration)
        clip = clip.set_audio(bell_audio)
        return clip, last_frame_np

    # ── repetition ────────────────────────────────────────────────────────
    if stype == "repetition":
        idx   = scene["index"]
        rep   = manifest["repetitions"][idx]
        dur_s = (rep.get("duration-ms") or 2000) / 1000.0
        clip  = freeze(dur_s, text=rep.get("text", ""), is_narrator=True)
        if rep.get("audio-file"):
            clip = _attach_audio(clip, project_path / rep["audio-file"], fps)
        return clip, last_frame_np

    # ── after-pause ───────────────────────────────────────────────────────
    if stype == "after-pause":
        idx   = scene["index"]
        rep   = manifest["repetitions"][idx]
        dur_s = (rep.get("after-pause-ms") or 2000) / 1000.0
        clip  = freeze(dur_s, text=rep.get("text", ""), is_narrator=True)
        clip  = clip.set_audio(_silent(dur_s))
        return clip, last_frame_np

    logger.warning(f"Unknown scene type: {stype}")
    return None, last_frame_np


def _peek_last_frame(video_path: Path, fallback):
    """
    Read the last frame of a completed clip to use as background for freeze frames.
    Reads 1 second before the end to avoid the EOF boundary that triggers the
    moviepy "bytes wanted but 0 bytes read" UserWarning.
    """
    import warnings
    try:
        from moviepy.editor import VideoFileClip
        v = VideoFileClip(str(video_path))
        # Stay well away from the very last frame — the EOF boundary causes
        # ffmpeg to emit a benign "0 bytes read" warning that moviepy surfaces.
        safe_t = max(0.0, v.duration - max(1.0 / v.fps, 0.05))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = v.get_frame(safe_t)
        v.close()
        return frame
    except Exception:
        return fallback


def _annotated_sub_layers(text: str, duration: float, cfg: dict, W: int, H: int) -> list:
    """
    Build grammar-annotated subtitle layers for a dialog line.

    Sizing mirrors the plain subtitle:
      - width  = target_w - margin_left - margin_right  (same usable text band)
      - x      = sub_margin_left                        (same left anchor)
      - bottom = sub_margin_bottom                      (same bottom anchor)

    The image height is fixed at 200 px — enough for one note line above the
    word line.  If annotations fail (API error, etc.) we fall back silently to
    a plain subtitle so the render is never broken.
    """
    margin_left   = cfg["sub_margin_left"]
    margin_right  = cfg["sub_margin_right"]
    margin_bottom = cfg["sub_margin_bottom"]

    sub_w  = W - margin_left - margin_right
    sub_h  = 200   # fixed canvas height: note row (~60 px) + word row (~80 px) + padding

    font_path      = cfg.get("annotated_font_path",      "fonts/NotoSans-Regular.ttf")
    bold_font_path = cfg.get("annotated_bold_font_path", "fonts/NotoSans-Bold.ttf")
    font_size      = cfg.get("annotated_font_size",      cfg["sub_fontsize"])
    note_size      = cfg.get("annotated_note_size",      max(24, cfg["sub_fontsize"] // 2))

    try:
        tokens = generate_annotations(text)
    except Exception as exc:
        logger.warning("Annotation failed for %r — falling back to plain subtitle: %s", text, exc)
        sub   = _subtitle(text, duration, False, cfg)
        sub_y = H - margin_bottom - sub.h
        return _sub_layers(sub, margin_left, sub_y, duration, cfg)

    try:
        img = create_annotated_subtitle(
            tokens,
            width=sub_w,
            height=sub_h,
            font_path=font_path,
            bold_font_path=bold_font_path,
            font_size=font_size,
            note_size=note_size,
        )
    except Exception as exc:
        logger.warning("Annotated render failed for %r — falling back to plain subtitle: %s", text, exc)
        sub   = _subtitle(text, duration, False, cfg)
        sub_y = H - margin_bottom - sub.h
        return _sub_layers(sub, margin_left, sub_y, duration, cfg)

    sub_y = H - margin_bottom - sub_h

    # Semi-transparent background — same opacity/padding as regular subtitles
    px = cfg["sub_bg_padding_x"]
    py = cfg["sub_bg_padding_y"]
    bg_clip = (
        ColorClip(size=(sub_w + px * 2, sub_h + py * 2), color=(0, 0, 0))
        .set_duration(duration)
        .set_opacity(cfg["sub_bg_opacity"])
    )

    ann_clip = ImageClip(np.array(img)).set_duration(duration)

    return [
        bg_clip.set_position((margin_left - px, sub_y - py)),
        ann_clip.set_position((margin_left, sub_y)),
    ]


def _subtitle(text: str, duration: float, is_narrator: bool, cfg: dict) -> TextClip:
    w = cfg["target_w"] - cfg["sub_margin_left"] - cfg["sub_margin_right"]
    if is_narrator:
        font, sz, col, scol, sw = (
            cfg["nar_font"], cfg["nar_fontsize"], cfg["nar_color"],
            cfg["nar_stroke_color"], cfg["nar_stroke_width"],
        )
    else:
        font, sz, col, scol, sw = (
            cfg["sub_font"], cfg["sub_fontsize"], cfg["sub_color"],
            cfg["sub_stroke_color"], cfg["sub_stroke_width"],
        )
    return TextClip(
        text.rstrip("."), font=font, fontsize=sz, color=col,
        stroke_color=scol, stroke_width=sw,
        method="caption", size=(w, None), align="center",
    ).set_duration(duration)


def _sub_layers(sub: TextClip, x: int, y, duration: float, cfg: dict) -> list:
    px, py = cfg["sub_bg_padding_x"], cfg["sub_bg_padding_y"]
    bg = (
        ColorClip(size=(sub.w + px * 2, sub.h + py * 2), color=(0, 0, 0))
        .set_duration(duration)
        .set_opacity(cfg["sub_bg_opacity"])
    )
    if y == "center":
        return [bg.set_position((x - px, "center")), sub.set_position((x, "center"))]
    return [bg.set_position((x - px, y - py)), sub.set_position((x, y))]


def _attach_audio(clip, audio_path: Path, fps: int):
    """
    Attach audio to a clip.

    Two fixes applied:
    1. Subclip to clip.duration - 2 frames to avoid the ffmpeg EOF boundary
       that causes moviepy to repeat the last audio buffer chunk (the "argentinana"
       stutter artifact).
    2. Apply a short fade-out (80 ms) to prevent abrupt cutoff at the clip boundary.
       This is inaudible in normal listening but removes the hard edge.
    """
    if not Path(audio_path).exists():
        logger.warning(f"Audio not found: {audio_path}")
        return clip

    fade_s  = 0.08                          # 80 ms — inaudible, removes hard cut
    safe    = max(clip.duration - 2 / fps, 0)
    audio   = (
        AudioFileClip(str(audio_path))
        .subclip(0, min(safe, AudioFileClip(str(audio_path)).duration))
        .set_duration(clip.duration)
        .audio_fadeout(fade_s)
    )
    return clip.set_audio(audio)


def _silent(duration: float):
    from moviepy.audio.AudioClip import AudioArrayClip
    samples = int(duration * 44100)
    return AudioArrayClip(np.zeros((samples, 2), dtype=np.float32), fps=44100).set_duration(duration)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project_name")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--annotated-subtitles",
        action="store_true",
        default=False,
        help="Render grammar-annotated subtitles on dialog scenes instead of plain subtitles.",
    )
    a = p.parse_args()
    create_videos(a.project_name, a.overwrite, annotated_subtitles=a.annotated_subtitles)


if __name__ == "__main__":
    create_videos("kitchen_talk_new_2", annotated_subtitles=False)  # set True to use annotated subtitles
