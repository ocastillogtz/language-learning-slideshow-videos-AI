"""
subtitle_render.py
==================
The ONE dialog-subtitle style, used by every project type: the configured
[subtitles] font, fill colour and outline (Calibri-Bold, BlanchedAlmond,
sienna4 by default), with highlighted words re-coloured in place.

Why not ImageMagick? create_video used to render plain lines with ImageMagick's
"caption" method (font + colour + outline applied) but lines with inline markup
(*bold* / _coloured_) with its "pango" method, which IGNORES the font, fill and
stroke arguments — so every highlighted line came out as thin white text, a
second subtitle style. Pillow draws both kinds identically: same font file, same
outline, and a markup span only changes the colour of its own words.

Inline markers (see utils_markup):
  _text_   -> next colour from [subtitles] markup_italic_colors (cycled)
  *text*   -> [subtitles] markup_bold_color (defaults to the first italic colour)
  -text-   -> shown as plain text (it is only excluded from TTS)

The config speaks ImageMagick names (font "Calibri-Bold", colour "sienna4"), so
both are resolved through ImageMagick once and cached: fonts via
`magick -list font`, colours Pillow doesn't know via `magick xc:<name>`.
"""

import functools
import logging
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

from utils_markup import SPAN_RE as _SPAN_RE, _BOLD_RE, _ITALIC_RE, _SILENT_RE
_LINE_SPACING = 1.05      # line height = font size x this (matches the old ImageMagick caption)


# =============================================================================
# NAME RESOLUTION (ImageMagick font / colour names -> file / RGB)
# =============================================================================

@functools.lru_cache(maxsize=1)
def _imagemagick_fonts(magick: str) -> dict:
    """{font name: glyph file} from `magick -list font` ({} if unavailable)."""
    try:
        out = subprocess.run([magick, "-list", "font"], capture_output=True,
                             text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    fonts, name = {}, None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Font:"):
            name = line[5:].strip()
        elif line.startswith("glyphs:") and name:
            fonts[name.lower()] = line[7:].strip()
    return fonts


@functools.lru_cache(maxsize=None)
def resolve_font(font: str, magick: str = "") -> str:
    """Font file for an ImageMagick font name (or pass-through for a file path)."""
    if font and Path(font).is_file():
        return font
    path = _imagemagick_fonts(magick or "magick").get((font or "").lower())
    if path and Path(path).is_file():
        return path
    for guess in (Path("C:/Windows/Fonts") / f"{font}.ttf",):
        if guess.is_file():
            return str(guess)
    raise FileNotFoundError(
        f"Subtitle font {font!r} not found (not a file and unknown to ImageMagick "
        f"'{magick or 'magick'}'). Set [subtitles] font to an installed font name or a .ttf path.")


@functools.lru_cache(maxsize=None)
def resolve_color(color: str, magick: str = "") -> tuple:
    """RGB tuple for a CSS/hex colour or an ImageMagick X11 name like 'sienna4'."""
    try:
        return ImageColor.getrgb(color)[:3]
    except ValueError:
        pass
    try:
        out = subprocess.run([magick or "magick", f"xc:{color}", "-format",
                              "%[pixel:p{0,0}]", "info:"],
                             capture_output=True, text=True, timeout=30).stdout
        nums = re.findall(r"[\d.]+", out)
        if len(nums) >= 3:
            vals = [float(n) for n in nums[:3]]
            if "%" in out:
                vals = [v * 2.55 for v in vals]
            return tuple(int(round(v)) for v in vals)
    except (OSError, subprocess.SubprocessError):
        pass
    logger.warning("Unknown subtitle colour %r — using white", color)
    return (255, 255, 255)


# =============================================================================
# LAYOUT
# =============================================================================

def _spans(text: str, base, bold, italic_colors: list) -> list:
    """[(text, rgb)] with the markers removed and each span coloured."""
    out, n_italic = [], 0
    for part in _SPAN_RE.split(text):
        if not part:
            continue
        if _BOLD_RE.fullmatch(part):
            out.append((part[1:-1], bold))
        elif _ITALIC_RE.fullmatch(part):
            out.append((part[1:-1], italic_colors[n_italic % len(italic_colors)]
                        if italic_colors else bold))
            n_italic += 1
        elif _SILENT_RE.fullmatch(part):
            out.append((part[1:-1], base))
        else:
            out.append((part, base))
    return out


def _words(spans: list) -> list:
    """Split coloured spans into words; a word is [(text, rgb), …] with no whitespace
    inside, so '_hat_.' stays one word made of two coloured pieces."""
    words, cur = [], []
    for text, rgb in spans:
        for i, chunk in enumerate(re.split(r"(\s+)", text)):
            if i % 2:                       # whitespace -> word boundary
                if cur:
                    words.append(cur)
                    cur = []
            elif chunk:
                cur.append((chunk, rgb))
    if cur:
        words.append(cur)
    return words


def _wrap(words: list, font, max_w: int) -> list:
    """Greedy word wrap -> list of lines, each a list of words."""
    space = font.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        ww = sum(font.getlength(t) for t, _ in w)
        add = ww if not cur else cur_w + space + ww
        if cur and add > max_w:
            lines.append(cur)
            cur, cur_w = [w], ww
        else:
            cur, cur_w = cur + [w], add
    if cur:
        lines.append(cur)
    return lines


# =============================================================================
# RENDER
# =============================================================================

def render_subtitle(text: str, width: int, *, font: str, fontsize: int, color: str,
                    stroke_color: str, stroke_width: int, italic_colors=None,
                    bold_color: str = "", magick: str = "") -> np.ndarray:
    """RGBA array (height x `width`) of the subtitle, lines centred.

    The canvas is always `width` wide (like ImageMagick caption with size=(w, None)),
    so the background box behind it keeps the same full width as before."""
    pil_font = ImageFont.truetype(resolve_font(font, magick), int(fontsize))
    base   = resolve_color(color, magick)
    stroke = resolve_color(stroke_color, magick)
    italic = [resolve_color(c, magick) for c in (italic_colors or [])]
    bold   = resolve_color(bold_color, magick) if bold_color else (italic[0] if italic else base)

    sw = max(0, int(stroke_width))
    lines = _wrap(_words(_spans(text, base, bold, italic)), pil_font, width - 2 * sw)
    if not lines:
        lines = [[[("", base)]]]

    ascent, descent = pil_font.getmetrics()
    line_h = int(round(fontsize * _LINE_SPACING))
    height = line_h * len(lines) + 2 * sw + max(0, ascent + descent - line_h)
    img  = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    space = pil_font.getlength(" ")

    # Lay out every piece first, then draw ALL outlines before ANY fill, so a
    # piece's outline never covers the neighbouring piece's letters.
    pieces = []
    for li, line in enumerate(lines):
        line_w = sum(sum(pil_font.getlength(t) for t, _ in w) for w in line) + space * (len(line) - 1)
        x = (width - line_w) / 2
        y = sw + li * line_h
        for wi, word in enumerate(line):
            if wi:
                x += space
            for t, rgb in word:
                pieces.append((x, y, t, rgb))
                x += pil_font.getlength(t)
    if sw:
        for x, y, t, _ in pieces:
            draw.text((x, y), t, font=pil_font, fill=stroke,
                      stroke_width=sw, stroke_fill=stroke)
    for x, y, t, rgb in pieces:
        draw.text((x, y), t, font=pil_font, fill=rgb)
    return np.array(img)
