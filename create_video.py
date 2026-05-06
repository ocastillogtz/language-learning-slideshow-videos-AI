"""
create_video.py
===============
Renders one .mp4 clip per scene in manifest["scenes"].

Dispatch on scene["audio"]["type"] (or null):
  "tts"        → scene image + TTS audio + subtitle
  "sfx"        → freeze last frame + SFX audio (+ optional subtitle_text)
  "video_clip" → insert VideoFileClip directly
  null         → freeze last frame, silent, duration from scene.duration_ms

Subtitle style:
  Narrator-style (centered, narrator font) when scene._is_narration or
  scene._is_repetition is True.  Dialog-style (bottom, regular font) otherwise.

Annotated subtitles:
  Pass annotated_subtitles=True to render grammar-coloured subtitles on dialog
  TTS scenes.  Narrator scenes always use plain style regardless of this flag.
"""

import json
import logging
import argparse
import numpy as np
from pathlib import Path
from PIL import Image
from moviepy.editor import (
    ImageClip, TextClip, CompositeVideoClip,
    ColorClip, AudioFileClip, VideoFileClip,
)
from moviepy.config import change_settings
from utils_config import load_config, load_new_characters
from utils_image import pad_image_to_frame, pil_to_numpy, make_icon_clip
from utils_markup import has_markup, to_pango, strip_markup
from generate_annotations import generate_annotations
from subtitle_renderer import create_annotated_subtitle

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_videos(
    project_name: str,
    overwrite: bool = False,
    annotated_subtitles: bool = False,
) -> None:
    cfg           = load_config()
    chars_data    = load_new_characters(cfg["assets_dir"])
    assets_dir    = cfg["assets_dir"]
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    videos_dir = project_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    fps           = cfg["fps"]
    last_frame_np = None

    for scene in manifest["scenes"]:
        sid   = scene["id"]
        out   = videos_dir / f"{sid}.mp4"
        audio = scene.get("audio")
        atype = audio.get("type") if audio else None

        if out.exists() and not overwrite:
            logger.info(f"Skipping {sid} (exists)")
            last_frame_np = _peek_last_frame(out, last_frame_np)
            continue

        logger.info(f"Rendering {sid} | audio.type={atype}")

        try:
            clip, last_frame_np = _build_clip(
                scene, project_path, assets_dir,
                cfg, chars_data, last_frame_np,
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


# =============================================================================
# CLIP BUILDER
# =============================================================================

def _build_clip(
    scene: dict,
    project_path: Path,
    assets_dir: Path,
    cfg: dict,
    chars_data: dict,
    last_frame_np,
    annotated_subtitles: bool = False,
):
    """
    Returns (clip, new_last_frame_np).
    Dispatches on scene["audio"]["type"] (or null).
    """
    W, H  = cfg["target_w"], cfg["target_h"]
    fps   = cfg["fps"]

    audio = scene.get("audio")
    atype = audio.get("type") if audio else None
    img   = scene.get("image")

    is_narrator = scene.get("_is_narration", False) or scene.get("_is_repetition", False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _freeze(duration_s: float, text: str = "", narrator_style: bool = False):
        """Freeze-frame clip, optionally with a subtitle."""
        if last_frame_np is not None:
            bg = ImageClip(last_frame_np).set_duration(duration_s)
        else:
            bg = ColorClip((W, H), (0, 0, 0)).set_duration(duration_s)
        layers = [bg]
        if text:
            sub   = _subtitle(text, duration_s, narrator_style, cfg)
            sub_y = H - cfg["sub_margin_bottom"] - sub.h
            layers += _sub_layers(sub, cfg["sub_margin_left"], sub_y, duration_s, cfg)
        return CompositeVideoClip(layers, size=(W, H)).set_duration(duration_s)

    # ------------------------------------------------------------------
    # null → silent pause
    # ------------------------------------------------------------------
    if atype is None:
        dur_s = scene.get("duration_ms", cfg["inter_pause_ms"]) / 1000.0
        clip  = _freeze(dur_s)
        clip  = clip.set_audio(_silent(dur_s))
        return clip, last_frame_np

    # ------------------------------------------------------------------
    # video_clip → insert VideoFileClip directly
    # ------------------------------------------------------------------
    if atype == "video_clip":
        clip_rel  = audio.get("file_path", "")
        clip_path = project_path / clip_rel
        if not clip_path.exists():
            # Try resolving relative to repo root (assets_dir.parent)
            clip_path = assets_dir.parent / clip_rel
        if not clip_path.exists():
            logger.error(f"Video clip not found: {clip_rel}")
            return None, last_frame_np
        vclip    = VideoFileClip(str(clip_path))
        last_np  = vclip.get_frame(max(0.0, vclip.duration - 0.1))
        return vclip, last_np

    # ------------------------------------------------------------------
    # sfx → freeze last frame + SFX audio
    # ------------------------------------------------------------------
    if atype == "sfx":
        sfx_rel  = audio.get("file_path", "")
        sfx_path = project_path / sfx_rel
        if not sfx_path.exists():
            sfx_path = assets_dir.parent / sfx_rel
        if not sfx_path.exists():
            logger.error(f"SFX file not found: {sfx_rel}")
            return None, last_frame_np
        sfx_audio     = AudioFileClip(str(sfx_path))
        subtitle_text = scene.get("subtitle_text", "")
        clip = _freeze(sfx_audio.duration, text=subtitle_text, narrator_style=True)
        clip = clip.set_audio(sfx_audio)
        return clip, last_frame_np

    # ------------------------------------------------------------------
    # tts → image + TTS audio + subtitle
    # ------------------------------------------------------------------
    if atype == "tts":
        dur_ms = scene.get("duration_ms") or (audio.get("duration_ms") if audio else None) or 3000
        dur_s  = dur_ms / 1000.0
        text   = (audio.get("tts_text") or "").strip()

        # Background image
        if img and img.get("file_path"):
            img_path = project_path / img["file_path"]
            pil_img  = Image.open(img_path).convert("RGB")
            frame    = pad_image_to_frame(pil_img, cfg)
            frame_np = pil_to_numpy(frame)
        elif last_frame_np is not None:
            frame_np = last_frame_np
        else:
            frame_np = pil_to_numpy(Image.new("RGB", (W, H), (0, 0, 0)))

        bg     = ImageClip(frame_np).set_duration(dur_s)
        layers = [bg]

        # Character icon — only for single-speaker dialog scenes
        characters = scene.get("characters", [])
        if not is_narrator and len(characters) == 1:
            icon = make_icon_clip(characters[0], chars_data, assets_dir, dur_s, cfg)
            if icon:
                layers.append(icon)

        # Subtitle
        if text:
            if annotated_subtitles and not is_narrator:
                layers += _annotated_sub_layers(text, dur_s, cfg, W, H)
            else:
                sub = _subtitle(text, dur_s, is_narrator, cfg)
                if is_narrator:
                    # Narrator text centered vertically
                    layers += _sub_layers(sub, cfg["sub_margin_left"], "center", dur_s, cfg)
                else:
                    sub_y = H - cfg["sub_margin_bottom"] - sub.h
                    layers += _sub_layers(sub, cfg["sub_margin_left"], sub_y, dur_s, cfg)

        clip = CompositeVideoClip(layers, size=(W, H)).set_duration(dur_s)

        # Attach TTS audio
        if audio and audio.get("file_path"):
            clip = _attach_audio(clip, project_path / audio["file_path"], fps)

        return clip, frame_np

    logger.warning(f"Unknown audio.type: {atype!r}")
    return None, last_frame_np


# =============================================================================
# SUBTITLE HELPERS
# =============================================================================

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

    clean = text.rstrip(".")

    # --- Try Pango markup rendering when markers are present ---
    if not is_narrator and has_markup(clean):
        try:
            pango_text = to_pango(
                clean,
                italic_attrs=cfg.get("markup_italic_attrs", 'font_style="italic"'),
                bold_attrs=cfg.get("markup_bold_attrs", 'weight="bold"'),
                italic_colors=cfg.get("markup_italic_colors", []),
            )
            return TextClip(
                pango_text, font=font, fontsize=sz, color=col,
                stroke_color=scol, stroke_width=sw,
                method="pango", size=(w, None), align="center",
            ).set_duration(duration)
        except Exception as exc:
            logger.warning(
                "Pango markup render failed for %r — falling back to plain text: %s",
                clean, exc,
            )
            clean = strip_markup(clean)

    return TextClip(
        clean, font=font, fontsize=sz, color=col,
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


def _annotated_sub_layers(text: str, duration: float, cfg: dict, W: int, H: int) -> list:
    """
    Grammar-annotated subtitle layers for dialog scenes.
    Falls back silently to plain subtitle on any error.
    """
    margin_left   = cfg["sub_margin_left"]
    margin_right  = cfg["sub_margin_right"]
    margin_bottom = cfg["sub_margin_bottom"]

    sub_w = W - margin_left - margin_right
    sub_h = 200  # note row (~60 px) + word row (~80 px) + padding

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
    px    = cfg["sub_bg_padding_x"]
    py    = cfg["sub_bg_padding_y"]
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


# =============================================================================
# AUDIO HELPERS
# =============================================================================

def _attach_audio(clip, audio_path: Path, fps: int):
    """
    Attach audio to a clip with two fixes:
    1. Subclip to clip.duration - 2 frames to avoid the ffmpeg EOF boundary
       that causes the last audio buffer to repeat (the "stutter" artifact).
    2. 80 ms fade-out to remove hard edge at clip boundary.
    """
    if not Path(audio_path).exists():
        logger.warning(f"Audio not found: {audio_path}")
        return clip
    fade_s = 0.08
    safe   = max(clip.duration - 2 / fps, 0)
    audio  = (
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


# =============================================================================
# FRAME HELPERS
# =============================================================================

def _peek_last_frame(video_path: Path, fallback):
    """
    Read a frame near the end of a completed clip to use as the freeze-frame
    background.  Reads slightly before the end to avoid the ffmpeg EOF boundary
    that triggers a benign "0 bytes read" warning from moviepy.
    """
    import warnings
    try:
        v      = VideoFileClip(str(video_path))
        safe_t = max(0.0, v.duration - max(1.0 / v.fps, 0.05))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = v.get_frame(safe_t)
        v.close()
        return frame
    except Exception:
        return fallback


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project_name")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--annotated-subtitles",
        action="store_true",
        default=False,
        help="Render grammar-annotated subtitles on dialog scenes.",
    )
    a = p.parse_args()
    create_videos(a.project_name, a.overwrite, annotated_subtitles=a.annotated_subtitles)


if __name__ == "__main__":
    main()
