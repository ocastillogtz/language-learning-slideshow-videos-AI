"""
subtitle_renderer.py
====================

Renders grammar-annotated subtitles as RGBA PIL images for use in MoviePy clips.

Bugs fixed:
1. No word wrapping — long sentences overflowed the canvas width, making later
   words invisible. Words now wrap onto multiple lines.
2. Fixed y_note = y_main - 70, meaning 3-line annotations (case + gender + role)
   overlapped the word text. Layout now measures actual note height and positions
   notes above the word with a proper gap.
3. Note x-position could go negative when the annotation string was wider than the
   word. Notes are now clamped to stay within the canvas.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, CompositeVideoClip


# ── Grammar colour mapping ────────────────────────────────────────────────────
GRAMMAR_COLORS = {
    "nominative": (100, 200, 100),
    "accusative": (255, 100, 100),
    "dative":     (100, 150, 255),
    "genitive":   (200, 100, 200),
    "verb":       (255, 200, 100),
    "subject":    (100, 255, 200),
    "object":     (255, 150, 200),
    "default":    (200, 200, 200),
}

NOTE_GAP = 8          # pixels between bottom of note and top of word
LINE_GAP = 6          # extra gap between wrapped lines


def build_note(token: dict) -> str:
    parts = []
    if "case"   in token: parts.append(token["case"])
    if "gender" in token: parts.append(token["gender"])
    if "role"   in token: parts.append(token["role"])
    return "\n".join(parts)


def get_color(token: dict) -> tuple:
    if "case" in token:
        return GRAMMAR_COLORS.get(token["case"], GRAMMAR_COLORS["default"])
    if "role" in token:
        return GRAMMAR_COLORS.get(token["role"], GRAMMAR_COLORS["default"])
    return GRAMMAR_COLORS["default"]


def _load_fonts(font_path: str, bold_font_path: str, font_size: int, note_size: int):
    """Load TTF fonts, falling back to PIL default if files are missing."""
    try:
        font      = ImageFont.truetype(font_path,      font_size)
        bold_font = ImageFont.truetype(bold_font_path, font_size)
        note_font = ImageFont.truetype(font_path,      note_size)
    except (IOError, OSError):
        # Graceful fallback — PIL default bitmap font (no size parameter)
        default   = ImageFont.load_default()
        font = bold_font = note_font = default
    return font, bold_font, note_font


def _measure_word(draw: ImageDraw.ImageDraw, word: str, font) -> tuple[int, int]:
    """Return (width, height) of a word using textbbox."""
    bbox = draw.textbbox((0, 0), word, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _measure_note(draw: ImageDraw.ImageDraw, note: str, font) -> tuple[int, int]:
    """Return (width, height) of a multiline note string."""
    if not note:
        return 0, 0
    bbox = draw.multiline_textbbox((0, 0), note, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_tokens(
    tokens: list[dict],
    draw: ImageDraw.ImageDraw,
    font,
    bold_font,
    note_font,
    canvas_width: int,
    x_start: int = 30,
    word_spacing: int = 20,
) -> list[list[dict]]:
    """
    Split tokens into lines so that no line exceeds canvas_width.

    Returns a list of lines, each line being a list of token dicts augmented
    with '_word_w', '_word_h', '_note_w', '_note_h', '_note', '_color', '_font'.
    """
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    x = x_start

    for token in tokens:
        use_font  = bold_font if token.get("bold") else font
        word      = token["text"]
        note      = build_note(token)
        color     = get_color(token)
        ww, wh    = _measure_word(draw, word, use_font)
        nw, nh    = _measure_note(draw, note, note_font)

        # The column width needed is the max of the word and its note
        col_w = max(ww, nw) + word_spacing

        if current_line and x + col_w > canvas_width - x_start:
            # Flush current line and start a new one
            lines.append(current_line)
            current_line = []
            x = x_start

        enriched = {**token, "_word_w": ww, "_word_h": wh, "_note_w": nw,
                    "_note_h": nh, "_note": note, "_color": color, "_font": use_font}
        current_line.append(enriched)
        x += col_w

    if current_line:
        lines.append(current_line)

    return lines


def _line_height(line: list[dict], note_font_size: int, word_font_size: int) -> int:
    """Compute the pixel height needed for one wrapped line (notes + gap + word)."""
    max_note_h = max((t["_note_h"] for t in line if t["_note"]), default=0)
    max_word_h = max(t["_word_h"] for t in line)
    note_block = max_note_h + NOTE_GAP if max_note_h else 0
    return note_block + max_word_h


def create_annotated_subtitle(
    tokens: list[dict],
    width: int = 1080,
    height: int = 300,
    font_path: str = "fonts/NotoSans-Regular.ttf",
    bold_font_path: str = "fonts/NotoSans-Bold.ttf",
    font_size: int = 60,
    note_size: int = 28,
) -> Image.Image:
    """
    Render grammar-annotated subtitle onto a transparent RGBA canvas.

    Tokens that have grammar annotations get coloured labels drawn above the word.
    Long sentences wrap onto multiple lines so nothing is clipped.

    Parameters
    ----------
    tokens          : list of token dicts from generate_annotations()
    width, height   : canvas size in pixels
    font_path       : path to a NotoSans (or similar) Regular TTF
    bold_font_path  : path to a NotoSans Bold TTF
    font_size       : point size for the main word text
    note_size       : point size for the annotation labels above each word
    """
    # ── Measure pass on a scratch canvas ─────────────────────────────────────
    scratch = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_scratch = ImageDraw.Draw(scratch)
    font, bold_font, note_font = _load_fonts(font_path, bold_font_path, font_size, note_size)

    lines = _wrap_tokens(tokens, draw_scratch, font, bold_font, note_font, width)

    # Calculate total height needed
    line_heights = [_line_height(line, note_size, font_size) for line in lines]
    total_h = sum(line_heights) + LINE_GAP * (len(lines) - 1)

    # Expand canvas height if needed
    actual_height = max(height, total_h + 20)
    img  = Image.new("RGBA", (width, actual_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Draw pass ─────────────────────────────────────────────────────────────
    x_start    = 30
    word_spacing = 20

    # Start drawing from the top so everything fits
    y_cursor = 10

    for line_idx, line in enumerate(lines):
        lh          = line_heights[line_idx]
        max_note_h  = max((t["_note_h"] for t in line if t["_note"]), default=0)
        note_block  = max_note_h + NOTE_GAP if max_note_h else 0
        y_word      = y_cursor + note_block      # baseline for words in this line
        x           = x_start

        for token in line:
            word   = token["text"]
            note   = token["_note"]
            color  = token["_color"]
            ufont  = token["_font"]
            ww     = token["_word_w"]
            nw     = token["_note_w"]
            nh     = token["_note_h"]

            col_w  = max(ww, nw)

            # ── Note (annotation labels) ──────────────────────────────────
            if note:
                note_x = x + (col_w - nw) // 2
                note_x = max(0, min(note_x, width - nw))   # clamp to canvas
                note_y = y_word - nh - NOTE_GAP
                draw.multiline_text(
                    (note_x, note_y),
                    note,
                    font=note_font,
                    fill=color,
                    align="center",
                )

            # ── Word ─────────────────────────────────────────────────────
            word_x = x + (col_w - ww) // 2
            draw.text(
                (word_x, y_word),
                word,
                font=ufont,
                fill=(255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )

            x += col_w + word_spacing

        y_cursor += lh + LINE_GAP

    return img


def subtitle_clip(tokens: list[dict], duration: float = 5.0) -> ImageClip:
    img = create_annotated_subtitle(tokens)
    return ImageClip(np.array(img)).set_duration(duration)


# ── End-to-end test (no OpenAI call, uses hardcoded tokens) ──────────────────
if __name__ == "__main__":
    # Short sentence — tests basic layout
    short_tokens = [
        {"text": "Ich",   "role": "subject", "bold": True},
        {"text": "gebe",  "role": "verb"},
        {"text": "dem",   "case": "dat",     "gender": "masc"},
        {"text": "Mann",  "role": "object"},
        {"text": "das",   "case": "acc",  "gender": "neu"},
        {"text": "Buch"},
    ]

    # Long sentence — tests word wrapping
    long_tokens = [
        {"text": "Ich"},
        {"text": "kann",  "role": "verb"},
        {"text": "mich",  "case": "acc"},
        {"text": "nicht"},
        {"text": "entscheiden,"},
        {"text": "ob"},
        {"text": "ich",   "role": "subject"},
        {"text": "eine",  "case": "accu", "gender": "fem"},
        {"text": "lustige"},
        {"text": "oder"},
        {"text": "eine",  "case": "acc", "gender": "fem"},
        {"text": "elegante"},
        {"text": "Geburtstagskarte", "case": "acc", "gender": "fem"},
        {"text": "kaufen", "role": "verb"},
        {"text": "soll."},
    ]

    # Render and save test images
    img_short = create_annotated_subtitle(short_tokens, width=870, height=250, font_size=50, note_size=20)
    img_short.save("test_subtitle_short.png")
    print("Saved test_subtitle_short.png")

    img_long = create_annotated_subtitle(long_tokens, width=870, height=250, font_size=50, note_size=20)
    img_long.save("test_subtitle_long.png")
    print("Saved test_subtitle_long.png")

    # Also produce a video clip
    bg  = ImageClip(np.zeros((1920, 1080, 3), dtype=np.uint8)).set_duration(5)
    sub = subtitle_clip(short_tokens, duration=5).set_position(("center", "bottom"))
    CompositeVideoClip([bg, sub]).write_videofile("test_subtitle.mp4", fps=24, logger=None)
    print("Saved test_subtitle.mp4")
