"""
create_video.py

Render one video clip per scene → projects/<project>/videos/<scene_id>.mp4

All tunable constants are read from config.ini.
Character thumbnail icon is composited onto dialogue clips at the position
defined in [character_icon] in config.ini.
"""

import json
import logging
import argparse
import configparser
import numpy as np
from pathlib import Path

from PIL import Image, ImageFilter
from moviepy.editor import (
    ImageClip, TextClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip, AudioFileClip,
)
from moviepy.config import change_settings

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    cfg = configparser.ConfigParser()
    cfg.read(config_path)

    projects_dir = Path(cfg["paths"]["projects_dir"])
    assets_dir   = Path(cfg["paths"]["assets_dir"])

    if cfg.has_option("tools", "imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["tools"]["imagemagick"]})

    params = {
        # video
        "target_w":             cfg.getint("video",   "target_w",             fallback=1080),
        "target_h":             cfg.getint("video",   "target_h",             fallback=1920),
        "fps":                  cfg.getint("video",   "fps",                   fallback=30),
        "dialogue_hold_s":      cfg.getfloat("video", "dialogue_hold_s",       fallback=0.4),
        "margin_blur_radius":   cfg.getint("video",   "margin_blur_radius",    fallback=30),
        "narrator_blur_radius": cfg.getint("video",   "narrator_blur_radius",  fallback=18),
        "blend_px":             cfg.getint("video",   "blend_px",              fallback=120),
        # subtitles
        "sub_font":             cfg.get("subtitles",  "font",                  fallback="Arial-Bold"),
        "sub_fontsize":         cfg.getint("subtitles","fontsize",              fallback=76),
        "sub_color":            cfg.get("subtitles",  "color",                 fallback="white"),
        "sub_stroke_color":     cfg.get("subtitles",  "stroke_color",          fallback="black"),
        "sub_stroke_width":     cfg.getint("subtitles","stroke_width",          fallback=4),
        "sub_margin_bottom":    cfg.getint("subtitles","margin_bottom",         fallback=200),
        "sub_margin_left":      cfg.getint("subtitles","margin_left",           fallback=40),
        "sub_margin_right":     cfg.getint("subtitles","margin_right",          fallback=160),
        "sub_bg_opacity":       cfg.getfloat("subtitles","bg_opacity",          fallback=0.45),
        "sub_bg_padding_x":     cfg.getint("subtitles","bg_padding_x",          fallback=20),
        "sub_bg_padding_y":     cfg.getint("subtitles","bg_padding_y",          fallback=12),
        # narrator subtitles
        "nar_font":             cfg.get("narrator_subtitles","font",            fallback="Arial-Bold"),
        "nar_fontsize":         cfg.getint("narrator_subtitles","fontsize",      fallback=76),
        "nar_color":            cfg.get("narrator_subtitles","color",           fallback="white"),
        "nar_stroke_color":     cfg.get("narrator_subtitles","stroke_color",    fallback="black"),
        "nar_stroke_width":     cfg.getint("narrator_subtitles","stroke_width",  fallback=4),
        # character icon
        "icon_x":               cfg.getint("character_icon", "x",              fallback=750),
        "icon_y":               cfg.getint("character_icon", "y",              fallback=1450),
        "icon_size":            cfg.getint("character_icon", "size",           fallback=220),
    }

    log_level = cfg.get("video", "log_level", fallback="INFO")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return projects_dir, assets_dir, params


# =========================
# LOAD CHARACTERS
# =========================
def load_characters(assets_dir: Path) -> dict:
    path = assets_dir / "characters.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# TEXT HELPERS
# =========================
def clean_subtitle_text(text: str) -> str:
    return text.rstrip(".")


# =========================
# IMAGE PROCESSING
# =========================
def pad_image_to_shorts(img: Image.Image, p: dict) -> Image.Image:
    """
    Scale image to target width, pin to top, fill bottom with blurred background.
    """
    W, H   = p["target_w"], p["target_h"]
    blur_r = p["margin_blur_radius"]
    blend  = p["blend_px"]

    src_w, src_h = img.size
    scale  = W / src_w
    new_w  = W
    new_h  = int(src_h * scale)
    img    = img.resize((new_w, new_h), Image.LANCZOS)

    if new_h >= H:
        return img.crop((0, 0, W, H))

    bg_scale = H / src_h
    bg_w     = int(src_w * bg_scale)
    bg       = img.resize((bg_w, H), Image.LANCZOS)
    if bg_w > W:
        x_off = (bg_w - W) // 2
        bg    = bg.crop((x_off, 0, x_off + W, H))
    else:
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
        canvas.paste(bg, ((W - bg_w) // 2, 0))
        bg = canvas

    bg = bg.filter(ImageFilter.GaussianBlur(blur_r))

    result = bg.copy()
    result.paste(img, (0, 0))
    result = _blend_seam(result, new_h - 1, "bottom", blend, blur_r)
    return result


def _blend_seam(canvas: Image.Image, seam_y: int, direction: str,
                blend_px: int, blur_r: int) -> Image.Image:
    arr     = np.array(canvas, dtype=np.float32)
    h, w, _ = arr.shape
    blurred = np.array(canvas.filter(ImageFilter.GaussianBlur(blur_r)), dtype=np.float32)

    for i in range(blend_px):
        alpha = i / blend_px
        y     = seam_y + i if direction == "bottom" else seam_y - i
        if 0 <= y < h:
            arr[y] = (1 - alpha) * blurred[y] + alpha * arr[y]

    return Image.fromarray(arr.astype(np.uint8))


def blur_image(img: Image.Image, radius: int) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def pil_to_numpy(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


# =========================
# CHARACTER ICON
# =========================
def make_icon_clip(
    character: str,
    characters_data: dict,
    assets_dir: Path,
    duration_s: float,
    p: dict,
) -> ImageClip | None:
    """
    Load a character's thumbnail, resize to a circle, return as an ImageClip
    positioned at (icon_x, icon_y). Returns None if no thumbnail is available.
    """
    thumb_path = characters_data.get(character, {}).get("thumbnail")
    if not thumb_path:
        return None

    # Strip leading "assets/" prefix if present so it's relative to assets_dir
    thumb_relative = Path(thumb_path)
    if thumb_relative.parts[0] == "assets":
        thumb_relative = Path(*thumb_relative.parts[1:])
    full_path = assets_dir / thumb_relative

    if not full_path.exists():
        logger.warning(f"Thumbnail not found: {full_path}")
        return None

    size = p["icon_size"]

    # Load and resize to square
    thumb = Image.open(full_path).convert("RGBA")
    thumb = thumb.resize((size, size), Image.LANCZOS)

    # Circular mask
    mask = Image.new("L", (size, size), 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    thumb.putalpha(mask)

    icon_np = np.array(thumb)
    clip = (
        ImageClip(icon_np, ismask=False)
        .set_duration(duration_s)
        .set_position((p["icon_x"], p["icon_y"]))
    )
    return clip


# =========================
# SUBTITLE CLIP
# =========================
def make_subtitle_clip(text: str, duration: float, is_narrator: bool, p: dict) -> TextClip:
    text_w = p["target_w"] - p["sub_margin_left"] - p["sub_margin_right"]
    if is_narrator:
        font, fontsize, color, stroke_color, stroke_width = (
            p["nar_font"], p["nar_fontsize"], p["nar_color"],
            p["nar_stroke_color"], p["nar_stroke_width"]
        )
    else:
        font, fontsize, color, stroke_color, stroke_width = (
            p["sub_font"], p["sub_fontsize"], p["sub_color"],
            p["sub_stroke_color"], p["sub_stroke_width"]
        )
    return TextClip(
        clean_subtitle_text(text),
        font=font, fontsize=fontsize, color=color,
        stroke_color=stroke_color, stroke_width=stroke_width,
        method="caption", size=(text_w, None), align="center",
    ).set_duration(duration)


def subtitle_x(p: dict) -> int:
    return p["sub_margin_left"]


def make_subtitle_bg(sub: TextClip, duration: float, p: dict) -> ColorClip:
    pad_x = p["sub_bg_padding_x"]
    pad_y = p["sub_bg_padding_y"]
    return ColorClip(
        size=(sub.w + pad_x * 2, sub.h + pad_y * 2),
        color=(0, 0, 0),
    ).set_duration(duration).set_opacity(p["sub_bg_opacity"])


def subtitle_layers(sub: TextClip, x: int, y, duration: float, p: dict) -> list:
    pad_x = p["sub_bg_padding_x"]
    pad_y = p["sub_bg_padding_y"]
    bg    = make_subtitle_bg(sub, duration, p)

    if y == "center":
        bg  = bg.set_position((x - pad_x, "center"))
        sub = sub.set_position((x, "center"))
    else:
        bg  = bg.set_position((x - pad_x, y - pad_y))
        sub = sub.set_position((x, y))

    return [bg, sub]


# =========================
# CLIP BUILDERS
# =========================
def build_dialogue_clip(
    scene: dict,
    project_path: Path,
    duration_s: float,
    p: dict,
    characters_data: dict,
    assets_dir: Path,
) -> CompositeVideoClip:
    img_path = project_path / scene["image"]
    img      = Image.open(img_path).convert("RGB")
    frame_np = pil_to_numpy(pad_image_to_shorts(img, p))
    bg_clip  = ImageClip(frame_np).set_duration(duration_s)

    layers = [bg_clip]

    # Character icon
    icon = make_icon_clip(
        scene.get("character", ""), characters_data, assets_dir, duration_s, p
    )
    if icon is not None:
        layers.append(icon)

    # Subtitle
    text = scene.get("text", "").strip()
    if text:
        sub   = make_subtitle_clip(text, duration_s, False, p)
        sub_y = p["target_h"] - p["sub_margin_bottom"] - sub.h
        layers += subtitle_layers(sub, subtitle_x(p), sub_y, duration_s, p)

    return CompositeVideoClip(layers, size=(p["target_w"], p["target_h"])).set_duration(duration_s)


def build_narrator_clip(scene: dict, narrator_img_path: Path,
                        duration_s: float, p: dict) -> CompositeVideoClip:
    img   = Image.open(narrator_img_path).convert("RGB")
    frame = pad_image_to_shorts(img, p)

    if scene.get("section") != "introduction":
        frame = blur_image(frame, p["narrator_blur_radius"])

    frame_np = pil_to_numpy(frame)
    bg_clip  = ImageClip(frame_np).set_duration(duration_s)
    layers   = [bg_clip]

    text = scene.get("text", "").strip()
    if text:
        txt = make_subtitle_clip(text, duration_s, True, p)
        layers += subtitle_layers(txt, subtitle_x(p), "center", duration_s, p)

    return CompositeVideoClip(layers, size=(p["target_w"], p["target_h"])).set_duration(duration_s)


def build_pause_clip(scene, duration_s, p: dict,
                     prev_frame_np=None, prev_is_narrator=False,
                     subtitle_position="center") -> CompositeVideoClip:
    W, H = p["target_w"], p["target_h"]
    if prev_frame_np is not None:
        bg_clip = ImageClip(prev_frame_np).set_duration(duration_s)
    else:
        bg_clip = ColorClip(size=(W, H), color=(0, 0, 0)).set_duration(duration_s)

    layers = [bg_clip]
    text   = scene.get("text", "").strip()

    if text:
        sub = make_subtitle_clip(text, duration_s, prev_is_narrator, p)
        if subtitle_position == "bottom":
            y = H - p["sub_margin_bottom"] - sub.h
        else:
            y = "center"
        layers += subtitle_layers(sub, subtitle_x(p), y, duration_s, p)

    return CompositeVideoClip(layers, size=(W, H)).set_duration(duration_s)


# =========================
# AUDIO HELPERS
# =========================
def make_silent_audio(duration: float):
    from moviepy.audio.AudioClip import AudioArrayClip
    fps     = 44100
    samples = int(duration * fps)
    silence = np.zeros((samples, 2), dtype=np.float32)
    return AudioArrayClip(silence, fps=fps).set_duration(duration)


def attach_audio(clip, audio_path: Path, fps: int):
    if not audio_path.exists():
        logger.warning(f"Audio file not found: {audio_path}")
        return clip
    safe_end = clip.duration - (1 / fps)
    audio    = AudioFileClip(str(audio_path)).subclip(0, max(safe_end, 0))
    audio    = audio.set_duration(clip.duration)
    return clip.set_audio(audio)


# =========================
# NARRATOR IMAGE RESOLVER
# =========================
def resolve_narrator_path(manifest: dict, project_path: Path) -> Path | None:
    rel = manifest.get("narrator_image")
    if rel:
        p = project_path / rel
        if p.exists():
            return p
        logger.warning(f"narrator_image key exists but file missing: {p}")

    for scene in manifest.get("scenes", []):
        if scene.get("is_narrator") and scene.get("image"):
            p = project_path / scene["image"]
            if p.exists():
                logger.info(f"Using fallback narrator image from scene {scene['id']}")
                return p

    return None


# =========================
# MAIN
# =========================
def create_videos(project_name: str, overwrite: bool = False):
    projects_dir, assets_dir, p = load_config()
    characters_data = load_characters(assets_dir)

    project_path  = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenes         = manifest["scenes"]
    narrator_path  = resolve_narrator_path(manifest, project_path)
    sfx_dir        = assets_dir / "sfx"
    videos_dir     = project_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    fps             = p["fps"]
    dialogue_hold_s = p["dialogue_hold_s"]

    last_frame_np    = None
    last_is_narrator = False

    for scene in scenes:
        scene_id   = scene["id"]
        scene_type = scene["type"]

        # ---- SFX ----
        if scene_type == "sfx":
            out_path = videos_dir / f"{scene_id}.mp4"
            if out_path.exists() and not overwrite:
                logger.info(f"Skipping {scene_id} (sfx, exists)")
                continue

            sfx_name       = scene.get("name", "")
            sfx_audio_path = sfx_dir / f"{sfx_name}.mp3"

            if not sfx_audio_path.exists():
                logger.warning(f"SFX not found: {sfx_audio_path} — skipping {scene_id}")
                continue

            sfx_audio = AudioFileClip(str(sfx_audio_path))
            clip      = build_pause_clip({"text": ""}, sfx_audio.duration, p,
                                         prev_frame_np=last_frame_np,
                                         prev_is_narrator=last_is_narrator)
            clip = clip.set_audio(sfx_audio)
            try:
                clip.write_videofile(str(out_path), fps=fps, codec="libx264",
                                     audio_codec="aac",
                                     temp_audiofile=str(videos_dir / f"{scene_id}_tmp.m4a"),
                                     remove_temp=True, logger=None)
                logger.info(f"  Saved: {out_path.name} (sfx: {sfx_name})")
            except Exception as e:
                logger.error(f"  Failed {scene_id}: {e}")
            finally:
                clip.close()
            continue

        out_path = videos_dir / f"{scene_id}.mp4"
        if out_path.exists() and not overwrite:
            logger.info(f"Skipping {scene_id} (exists)")
            continue

        logger.info(f"Rendering {scene_id} | {scene_type}")

        # ---- DURATION ----
        if scene_type == "dialogue":
            duration_s = (scene.get("audio") or {}).get("duration_ms", 2000) / 1000.0
        elif scene_type == "pause":
            duration_s = scene.get("duration_ms", 1000) / 1000.0
        else:
            logger.warning(f"Unknown scene type '{scene_type}' — skipping")
            continue

        # ---- BUILD CLIP ----
        try:
            if scene_type == "dialogue":
                is_narrator = scene.get("is_narrator", False)
                if is_narrator:
                    if not narrator_path:
                        logger.error(f"No narrator image available for {scene_id} — skipping")
                        continue
                    clip  = build_narrator_clip(scene, narrator_path, duration_s, p)
                    img   = Image.open(narrator_path).convert("RGB")
                    frame = pad_image_to_shorts(img, p)
                    if scene.get("section") != "introduction":
                        frame = blur_image(frame, p["narrator_blur_radius"])
                    last_frame_np    = pil_to_numpy(frame)
                    last_is_narrator = True
                else:
                    clip = build_dialogue_clip(
                        scene, project_path, duration_s, p,
                        characters_data, assets_dir,
                    )
                    img = Image.open(project_path / scene["image"]).convert("RGB")
                    last_frame_np    = pil_to_numpy(pad_image_to_shorts(img, p))
                    last_is_narrator = False

            elif scene_type == "pause":
                clip = build_pause_clip(scene, duration_s, p,
                                        prev_frame_np=last_frame_np,
                                        prev_is_narrator=last_is_narrator)

        except Exception as e:
            logger.error(f"Failed to build clip for {scene_id}: {e}")
            continue

        # ---- ATTACH AUDIO ----
        if scene_type == "dialogue":
            audio_rel = (scene.get("audio") or {}).get("file")
            if audio_rel:
                clip = attach_audio(clip, project_path / audio_rel, fps)

        # ---- 400ms HOLD ----
        if scene_type == "dialogue":
            hold = build_pause_clip(
                {"text": scene.get("text", "")},
                dialogue_hold_s, p,
                prev_frame_np=last_frame_np,
                prev_is_narrator=scene.get("is_narrator", False),
                subtitle_position="bottom" if not scene.get("is_narrator", False) else "center",
            )
            hold = hold.set_audio(make_silent_audio(dialogue_hold_s))
            clip = concatenate_videoclips([clip, hold], method="compose")

        # ---- WRITE ----
        try:
            clip.write_videofile(str(out_path), fps=fps, codec="libx264",
                                 audio_codec="aac",
                                 temp_audiofile=str(videos_dir / f"{scene_id}_tmp.m4a"),
                                 remove_temp=True, logger=None)
            logger.info(f"  Saved: {out_path.name}")
        except Exception as e:
            logger.error(f"  Failed to write {scene_id}: {e}")
        finally:
            clip.close()

    logger.info("create_video complete.")


# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Render per-scene video clips")
    parser.add_argument("project_name")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    create_videos(args.project_name, overwrite=args.overwrite)

if __name__ == "__main__":
    create_videos("office_convo_3")
