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
    concatenate_videoclips,
)
from moviepy.config import change_settings
from utils_config import load_config, load_new_characters
from utils_image import pad_image_to_frame, pil_to_numpy, make_icon_clip, make_corner_icon_clip
from utils_markup import has_markup, to_pango, strip_markup
from generate_annotations import generate_annotations
from html_annotation_renderer import AnnotationBatchRenderer
from utils_markup import strip_markup as _strip_markup_for_annot

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_videos(
    project_name: str,
    overwrite: bool = False,
    annotated_subtitles: bool = False,
    footnote: str = "",
    inter_pause_ms: int = None,
    format_override: str = None,
    out_subdir: str = "",
    annot_font_scale: float = 1.0,
    regen_annotations: bool = False,
    read_pre_pause_ms: int = None,
) -> None:
    cfg           = load_config()
    chars_data    = load_new_characters(cfg["assets_dir"])
    assets_dir    = cfg["assets_dir"]
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    # Regenerating annotations only matters if the clips are also rebuilt, so force
    # an overwrite — otherwise existing clips would be skipped and you'd see no change.
    if regen_annotations:
        overwrite = True

    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Apply format-specific config overrides for horizontal (Full HD 16:9) projects.
    # format_override lets reading_together render a horizontal pass for the long video.
    video_format = format_override or manifest.get("video_info", {}).get("video_format", "vertical")
    if video_format == "horizontal":
        cfg.update({
            "target_w":         1920,
            "target_h":         1080,
            "sub_fontsize":     54,
            "nar_fontsize":     54,
            "sub_margin_bottom": 70,
            "icon_x":           1650,
            "icon_y":           50,
        })
        logger.info("Horizontal format — canvas set to 1920×1080, subtitle/icon positions adjusted")

    videos_dir = (project_path / "videos" / out_subdir) if out_subdir else (project_path / "videos")
    videos_dir.mkdir(parents=True, exist_ok=True)

    fps           = cfg["fps"]
    last_frame_np = None

    # Reading "pre-pause": hold the silent frame (image + sentence) before the
    # narration of each reading scene EXCEPT the first, so the learner can try to
    # read first. UI override wins over the config value; 0 disables it.
    pre_pause_ms = read_pre_pause_ms if read_pre_pause_ms is not None \
                   else cfg.get("read_pre_pause_ms", 0)
    seen_reading = False   # becomes True once the first reading scene is rendered

    # Pre-render grammar-annotated subtitle PNGs up-front, in a single Chromium
    # session, so the per-scene loop just loads images.  Maps scene_id -> png path.
    annot_paths: dict[str, str] = {}
    if annotated_subtitles:
        annot_paths = _prerender_annotations(manifest, videos_dir, cfg,
                                             font_scale=annot_font_scale,
                                             force=regen_annotations)

    for scene in manifest["scenes"]:
        sid   = scene["id"]
        out   = videos_dir / f"{sid}.mp4"
        audio = scene.get("audio")
        atype = audio.get("type") if audio else None

        # Pre-pause applies to reading sentences only, and never to the FIRST one.
        # Track "seen_reading" even for skipped/existing clips so the exemption of
        # the first sentence stays correct on partial re-renders.
        scene_pre_pause = 0
        if scene.get("_reading") and atype == "tts":
            if seen_reading and pre_pause_ms and pre_pause_ms > 0:
                scene_pre_pause = pre_pause_ms
            seen_reading = True

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
                global_footnote=footnote,
                pause_override_ms=inter_pause_ms,
                annot_paths=annot_paths,
                pre_pause_ms=scene_pre_pause,
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
    global_footnote: str = "",
    pause_override_ms: int = None,
    annot_paths: dict | None = None,
    pre_pause_ms: int = 0,
):
    """
    Returns (clip, new_last_frame_np).
    Dispatches on scene["audio"]["type"] (or null).

    pre_pause_ms > 0 (reading_together only) prepends a silent "read it yourself"
    moment to a TTS scene: the same frame (image + sentence) held with a book icon
    top-left, BEFORE the narration audio begins.
    """
    annot_paths = annot_paths or {}
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
        # pause_override_ms (from UI) takes priority over the baked-in scene value
        raw_ms = pause_override_ms if pause_override_ms is not None \
                 else scene.get("duration_ms", cfg["inter_pause_ms"])
        dur_s = raw_ms / 1000.0
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
        sub_bg_bottom = None  # tracks bottom edge of subtitle bg for footnote placement
        if text:
            ann_png = annot_paths.get(scene["id"]) if annotated_subtitles and not is_narrator else None
            if ann_png:
                ann_layers, sub_bg_bottom = _annotated_sub_layers(ann_png, dur_s, cfg, W, H)
                layers += ann_layers
            elif annotated_subtitles and not is_narrator:
                # Annotation unavailable for this scene -- fall back to a plain subtitle
                sub = _subtitle(text, dur_s, False, cfg)
                sub_y = H - cfg["sub_margin_bottom"] - sub.h
                layers += _sub_layers(sub, cfg["sub_margin_left"], sub_y, dur_s, cfg)
                sub_bg_bottom = sub_y + sub.h + cfg["sub_bg_padding_y"]
            else:
                sub = _subtitle(text, dur_s, is_narrator, cfg)
                if is_narrator:
                    # Narrator text centered vertically
                    layers += _sub_layers(sub, cfg["sub_margin_left"], "center", dur_s, cfg)
                    # bg center = H/2 → bg bottom = H/2 + (sub.h/2 + padding_y)
                    sub_bg_bottom = H // 2 + sub.h // 2 + cfg["sub_bg_padding_y"]
                else:
                    sub_y = H - cfg["sub_margin_bottom"] - sub.h
                    layers += _sub_layers(sub, cfg["sub_margin_left"], sub_y, dur_s, cfg)
                    sub_bg_bottom = sub_y + sub.h + cfg["sub_bg_padding_y"]

        # Footnote / disclaimer — rendered just below the subtitle background.
        # Scene-level "footnote" field takes priority; the global_footnote (passed
        # at render-time from the UI) is used as a fallback for narration scenes only.
        footnote = scene.get("footnote", "").strip()
        if not footnote and is_narrator:
            footnote = global_footnote.strip()
        if footnote:
            if sub_bg_bottom is None:
                # No subtitle text — anchor footnote to vertical center as fallback
                sub_bg_bottom = H // 2 + cfg["sub_bg_padding_y"]
            layers += _footnote_layers(footnote, sub_bg_bottom, dur_s, cfg, W)

        clip = CompositeVideoClip(layers, size=(W, H)).set_duration(dur_s)

        # Attach TTS audio
        if audio and audio.get("file_path"):
            clip = _attach_audio(clip, project_path / audio["file_path"], fps)

        # Reading "pre-pause": show the frame (image + sentence) SILENTLY for a
        # moment before the narration starts, with a book icon top-left as the
        # "your turn to read" cue. Prepended so the audio is unchanged afterwards.
        if pre_pause_ms and pre_pause_ms > 0:
            clip = _prepend_pre_pause(clip, pre_pause_ms, assets_dir, cfg, W, H)

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


def _footnote_layers(text: str, sub_bg_bottom: int, duration: float, cfg: dict, W: int) -> list:
    """
    Render a small footnote/disclaimer text just below the main subtitle background.

    sub_bg_bottom: y-coordinate of the bottom edge of the main subtitle's background box.
    The footnote is placed cfg["fn_gap"] pixels below that point.
    """
    gap   = cfg.get("fn_gap", 16)
    fn_y  = sub_bg_bottom + gap
    fn_w  = W - cfg["sub_margin_left"] - cfg["sub_margin_right"]
    font  = cfg.get("fn_font") or cfg["sub_font"]
    sz    = cfg.get("fn_fontsize", 36)
    col   = cfg.get("fn_color", "white")
    scol  = cfg.get("fn_stroke_color", "black")
    sw    = cfg.get("fn_stroke_width", 2)

    fn_clip = TextClip(
        text, font=font, fontsize=sz, color=col,
        stroke_color=scol, stroke_width=sw,
        method="caption", size=(fn_w, None), align="center",
    ).set_duration(duration)

    px, py  = cfg["sub_bg_padding_x"], cfg["sub_bg_padding_y"]
    opacity = cfg.get("fn_bg_opacity", cfg["sub_bg_opacity"])
    fn_bg   = (
        ColorClip(size=(fn_clip.w + px * 2, fn_clip.h + py * 2), color=(0, 0, 0))
        .set_duration(duration)
        .set_opacity(opacity)
    )
    x = cfg["sub_margin_left"]
    return [
        fn_bg.set_position((x - px, fn_y - py)),
        fn_clip.set_position((x, fn_y)),
    ]


def _annotated_sub_layers(png_path: str, duration: float, cfg: dict, W: int, H: int):
    """
    Build the bottom subtitle layer from a pre-rendered grammar-annotation PNG.

    The PNG already contains its own rounded semi-transparent dark backing (baked
    in by the HTML renderer), so no separate ColorClip is needed.  The image is
    rendered at 2x device scale; we down-scale by 0.5 to its true pixel size, then
    left-align it at sub_margin_left near the bottom of the frame (so it shares the
    same short left margin as the plain subtitles, instead of being centred).

    Returns (layers, sub_bg_bottom).
    """
    margin_bottom = cfg["sub_margin_bottom"]

    clip = ImageClip(png_path).set_duration(duration)
    # Undo the 2x supersampling used during rasterization -> crisp 1:1 pixels.
    clip = clip.resize(0.5)

    # Never let it exceed the usable width (keeps the right edge inside sub_margin_right).
    max_w = W - cfg["sub_margin_left"] - cfg["sub_margin_right"]
    if clip.w > max_w:
        clip = clip.resize(width=max_w)

    x = cfg["sub_margin_left"]
    y = H - margin_bottom - clip.h
    clip = clip.set_position((x, y))
    sub_bg_bottom = y + clip.h
    return [clip], sub_bg_bottom


def _prerender_annotations(manifest: dict, videos_dir: Path, cfg: dict,
                           font_scale: float = 1.0, force: bool = False) -> dict:
    """
    Generate grammar annotations and rasterize them to PNGs for every dialog
    (non-narrator) TTS scene, using a single Chromium session.

    font_scale multiplies the whole annotation text (word + tense/case/infinitive
    labels) so the on-screen size can be tuned from the UI.

    Returns {scene_id: png_path}.  Scenes that fail are simply omitted, so the
    caller falls back to a plain subtitle for those.
    """
    horizontal = manifest.get("video_info", {}).get("video_format", "vertical") == "horizontal"
    sub_w      = cfg["target_w"] - cfg["sub_margin_left"] - cfg["sub_margin_right"]
    word_size  = cfg.get("annotated_font_size", cfg["sub_fontsize"])
    note_size  = cfg.get("annotated_note_size", max(20, cfg["sub_fontsize"] // 2))
    opacity    = cfg.get("sub_bg_opacity", 0.55)

    # CSS max width is the final (1x) usable width; the renderer supersamples at 2x.
    style = {"max_width_px": sub_w, "word_size_px": word_size, "note_size_px": note_size}

    targets = []
    for scene in manifest.get("scenes", []):
        if scene.get("_is_narration") or scene.get("_is_repetition"):
            continue
        audio = scene.get("audio") or {}
        if audio.get("type") != "tts":
            continue
        text = (audio.get("tts_text") or "").strip()
        if not text:
            continue
        targets.append((scene["id"], _strip_markup_for_annot(text)))

    if not targets:
        return {}

    out_dir = videos_dir / "_annot"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _run_batch() -> dict[str, str]:
        paths: dict[str, str] = {}
        with AnnotationBatchRenderer(style=style, horizontal=horizontal,
                                     backing=True, backing_opacity=opacity, scale=2,
                                     font_scale=font_scale) as r:
            for sid, text in targets:
                try:
                    # Reuse a cached annotation for unchanged text (no OpenAI call);
                    # an edited sentence has different text and re-prompts automatically.
                    # force=True ("redo annotations") bypasses the cache and re-prompts.
                    annotation = generate_annotations(text, cache_path=out_dir / f"{sid}.json",
                                                      force=force)
                    dest = out_dir / f"{sid}.png"
                    r.render_to(annotation, dest)
                    paths[sid] = str(dest)
                except Exception as exc:
                    logger.warning("Annotation prerender failed for %s (%r): %s", sid, text, exc)
        return paths

    try:
        paths = _run_batch()
    except Exception as exc:
        # The whole batch could not start — almost always headless Chromium is not
        # installed for Playwright. Try to install it once, then retry. If it still
        # fails, raise a clear, actionable error instead of silently degrading to
        # plain subtitles (which is what the user just told us they DON'T want).
        msg = str(exc)
        looks_like_browser = (
            isinstance(exc, ImportError)
            or "playwright" in msg.lower()
            or "executable" in msg.lower()
            or "chromium" in msg.lower()
        )
        if looks_like_browser and _try_install_chromium():
            logger.info("Installed Chromium — retrying annotated subtitle render…")
            paths = _run_batch()   # if this raises, it propagates -> job reports error
        else:
            raise RuntimeError(
                "Grammar-annotated subtitles were requested but the HTML renderer could "
                "not start (headless Chromium unavailable). Install it once with:\n"
                "    pip install playwright\n"
                "    python -m playwright install chromium\n"
                f"Original error: {msg}"
            ) from exc

    logger.info("Pre-rendered %d/%d annotated subtitles", len(paths), len(targets))
    return paths


def _try_install_chromium() -> bool:
    """Best-effort `playwright install chromium`. Returns True on success."""
    import subprocess
    import sys
    logger.warning("Annotated subtitles requested but Chromium is missing — "
                   "installing it now (one-time, this can take a minute)…")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, timeout=900)
        return True
    except Exception as e:
        logger.error("Automatic Chromium install failed: %s", e)
        return False


# =============================================================================
# PRE-PAUSE (reading_together)
# =============================================================================

def _prepend_pre_pause(clip, pre_pause_ms: int, assets_dir: Path, cfg: dict, W: int, H: int):
    """
    Prepend a silent "read it yourself" segment to a finished TTS clip.

    The segment freezes the clip's first frame (image + sentence, exactly as it
    will look during narration), holds it for `pre_pause_ms`, and overlays the book
    icon in the upper-left corner. The original clip (with its audio) follows
    unchanged, so the learner sees the text first and then hears it read.
    """
    pre_s   = pre_pause_ms / 1000.0
    base_np = clip.get_frame(0)                      # image + subtitle, no book icon
    layers  = [ImageClip(base_np).set_duration(pre_s)]

    icon = make_corner_icon_clip(
        cfg.get("pre_pause_icon", "icons/book.png"), assets_dir,
        cfg.get("pre_pause_icon_size", 150),
        cfg.get("pre_pause_icon_margin_x", 50),
        cfg.get("pre_pause_icon_margin_y", 50),
        pre_s,
    )
    if icon:
        layers.append(icon)

    pre_clip = (CompositeVideoClip(layers, size=(W, H))
                .set_duration(pre_s)
                .set_audio(_silent(pre_s)))
    return concatenate_videoclips([pre_clip, clip], method="compose")


# =============================================================================
# AUDIO HELPERS
# =============================================================================

def _attach_audio(clip, audio_path: Path, fps: int):
    """
    Attach audio to a clip with three fixes:
    1. Never let the video outlast the actual audio. If the recorded scene
       duration is longer than the real mp3 (e.g. duration_ms was stale or never
       written), the writer would read past the end of the file and crash with
       "Accessing time t=… with clip duration=…". We clamp the clip to the real
       audio length so video and audio always match.
    2. End 2 frames early to dodge the ffmpeg EOF boundary that repeats the last
       audio buffer (the "stutter" artifact).
    3. 80 ms fade-out to remove the hard edge at the clip boundary.
    """
    if not Path(audio_path).exists():
        logger.warning(f"Audio not found: {audio_path}")
        return clip

    src  = AudioFileClip(str(audio_path))
    adur = src.duration or 0.0
    # Align the clip to whichever is shorter — the real audio or the planned dur.
    target = min(clip.duration, adur)
    if target <= 0:
        logger.warning(f"Audio has no usable duration: {audio_path}")
        src.close()
        return clip

    end    = max(target - 2 / fps, 0) or target   # 2-frame EOF guard
    fade_s = min(0.08, end)
    audio  = src.subclip(0, end).audio_fadeout(fade_s)
    return clip.set_duration(target).set_audio(audio)


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
    p.add_argument(
        "--footnote",
        default="",
        help="Disclaimer / footnote shown below the narration text on intro scenes.",
    )
    p.add_argument(
        "--inter-pause-ms",
        type=int,
        default=None,
        dest="inter_pause_ms",
        help="Override silent-pause duration in milliseconds (e.g. 500).",
    )
    p.add_argument(
        "--format-override",
        default=None,
        dest="format_override",
        choices=["vertical", "horizontal"],
        help="Force the render format regardless of the manifest (reading_together long pass).",
    )
    p.add_argument(
        "--out-subdir",
        default="",
        dest="out_subdir",
        help="Write per-scene clips into videos/<subdir>/ (e.g. 'h' for the horizontal pass).",
    )
    p.add_argument(
        "--read-pre-pause-ms",
        type=int,
        default=None,
        dest="read_pre_pause_ms",
        help="reading_together: silent pre-pause (ms) before each sentence's narration "
             "(except the first). Overrides config; 0 disables.",
    )
    a = p.parse_args()
    create_videos(a.project_name, a.overwrite,
                  annotated_subtitles=a.annotated_subtitles,
                  footnote=a.footnote,
                  inter_pause_ms=a.inter_pause_ms,
                  format_override=a.format_override,
                  out_subdir=a.out_subdir,
                  read_pre_pause_ms=a.read_pre_pause_ms)


if __name__ == "__main__":
    main()
