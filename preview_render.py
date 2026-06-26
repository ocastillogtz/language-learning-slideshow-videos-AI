"""
preview_render.py
=================
Render a still PNG preview of how narration / subtitle / footnote text will look
on screen, composited over a sample background from assets/samples/.

It reuses the EXACT same helpers as the real video renderer (create_video.py) and
the same per-orientation config (apply_video_format), so the preview matches what a
rendered clip would look like — same fonts, sizes, colours, margins, and the dark
subtitle backing box.

Used by the frontend "Subtitle Preview" tool via the /preview/text route.
"""

import io
from PIL import Image
from moviepy.editor import ImageClip, CompositeVideoClip
from moviepy.config import change_settings

from utils_config import load_config, apply_video_format
from utils_image import pad_image_to_frame, pil_to_numpy
import create_video as cv

_PREVIEW_DUR = 1.0  # seconds — we only ever read frame 0


def render_text_preview(
    text: str,
    video_format: str = "vertical",
    style: str = "dialog",          # "dialog" | "narration"
    footnote: str = "",
    repeat_message: str = "",
) -> bytes:
    """
    Return PNG bytes of `text` rendered over assets/samples/<video_format>.png.

    style:
      "dialog"    — bottom-aligned dialogue subtitle (subtitle font/colour)
      "narration" — vertically-centred narrator text (narrator font/colour)
    footnote       — optional disclaimer drawn just below the subtitle/narration box
    repeat_message — optional centred "now repeat" overlay (shadowing preview)
    """
    if video_format not in ("vertical", "horizontal"):
        video_format = "vertical"

    cfg = load_config()
    apply_video_format(cfg, video_format)
    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    W, H       = cfg["target_w"], cfg["target_h"]
    assets_dir = cfg["assets_dir"]

    # Background: the sample image (padded to the canvas), or a neutral grey fallback.
    sample = assets_dir / "samples" / f"{video_format}.png"
    if sample.exists():
        pil      = Image.open(sample).convert("RGB")
        frame_np = pil_to_numpy(pad_image_to_frame(pil, cfg))
    else:
        frame_np = pil_to_numpy(Image.new("RGB", (W, H), (28, 28, 32)))

    layers        = [ImageClip(frame_np).set_duration(_PREVIEW_DUR)]
    is_narrator   = (style == "narration")
    text          = (text or "").strip()
    sub_bg_bottom = None

    # Subtitle / narration text — same paths as create_video._build_clip.
    if text:
        sub = cv._subtitle(text, _PREVIEW_DUR, is_narrator, cfg)
        if is_narrator:
            layers += cv._sub_layers(sub, cfg["sub_margin_left"], "center", _PREVIEW_DUR, cfg)
            sub_bg_bottom = H // 2 + sub.h // 2 + cfg["sub_bg_padding_y"]
        else:
            sub_y = H - cfg["sub_margin_bottom"] - sub.h
            layers += cv._sub_layers(sub, cfg["sub_margin_left"], sub_y, _PREVIEW_DUR, cfg)
            sub_bg_bottom = sub_y + sub.h + cfg["sub_bg_padding_y"]

    # Footnote / disclaimer, anchored below the text box (centre fallback if no text).
    footnote = (footnote or "").strip()
    if footnote:
        if sub_bg_bottom is None:
            sub_bg_bottom = H // 2 + cfg["sub_bg_padding_y"]
        layers += cv._footnote_layers(footnote, sub_bg_bottom, _PREVIEW_DUR, cfg, W)

    # Optional centred shadowing "repeat" overlay.
    repeat_message = (repeat_message or "").strip()
    if repeat_message:
        layers += cv._repeat_message_layers(repeat_message, _PREVIEW_DUR, cfg, W, H)

    clip = CompositeVideoClip(layers, size=(W, H)).set_duration(_PREVIEW_DUR)
    try:
        frame = clip.get_frame(0)
    finally:
        clip.close()

    img = Image.fromarray(frame.astype("uint8"))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def available_samples() -> dict:
    """Return {orientation: bool} for which sample backgrounds exist on disk."""
    cfg = load_config()
    d   = cfg["assets_dir"] / "samples"
    return {fmt: (d / f"{fmt}.png").exists() for fmt in ("vertical", "horizontal")}
