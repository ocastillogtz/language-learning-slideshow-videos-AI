"""
creates complex subtitles with colors and annotations.


"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, CompositeVideoClip


# 🎨 Fixed grammar color mapping
GRAMMAR_COLORS = {
    "nominative": (100, 200, 100),
    "accusative": (255, 100, 100),
    "dative": (100, 150, 255),
    "genitive": (200, 100, 200),
    "verb": (255, 200, 100),
    "subject": (100, 255, 200),
    "object": (255, 150, 200),
    "default": (200, 200, 200),
}


def build_note(token: dict) -> str:
    parts = []

    if "case" in token:
        parts.append(token["case"])
    if "gender" in token:
        parts.append(token["gender"])
    if "role" in token:
        parts.append(token["role"])

    return "\n".join(parts)


def get_color(token: dict):
    if "case" in token:
        return GRAMMAR_COLORS.get(token["case"], GRAMMAR_COLORS["default"])
    if "role" in token:
        return GRAMMAR_COLORS.get(token["role"], GRAMMAR_COLORS["default"])
    return GRAMMAR_COLORS["default"]


def create_annotated_subtitle(
    tokens,
    width=1280,
    height=300,
    font_path="fonts/NotoSans-Regular.ttf",
    bold_font_path="fonts/NotoSans-Bold.ttf",
    font_size=60,
    note_size=28,
):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype(font_path, font_size)
    bold_font = ImageFont.truetype(bold_font_path, font_size)
    note_font = ImageFont.truetype(font_path, note_size)

    spacing = 25
    x = 50
    y_main = height // 2
    y_note = y_main - 70

    for token in tokens:
        word = token["text"]
        note = build_note(token)
        color = get_color(token)

        use_font = bold_font if token.get("bold") else font

        bbox = draw.textbbox((0, 0), word, font=use_font)
        w = bbox[2] - bbox[0]

        # Draw note
        if note:
            note_bbox = draw.multiline_textbbox((0, 0), note, font=note_font)
            note_w = note_bbox[2] - note_bbox[0]

            draw.multiline_text(
                (x + (w - note_w) // 2, y_note),
                note,
                font=note_font,
                fill=color,
                align="center",
            )

        # Draw word
        draw.text(
            (x, y_main),
            word,
            font=use_font,
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

        x += w + spacing

    return img


def subtitle_clip(tokens, duration=5):
    img = create_annotated_subtitle(tokens)
    return ImageClip(np.array(img)).set_duration(duration)


# 🧪 TEST
if __name__ == "__main__":
    tokens = [
        {"text": "Ich", "role": "subject", "bold": True},
        {"text": "gebe", "role": "verb"},
        {"text": "dem", "case": "dative", "gender": "masculine"},
        {"text": "Mann", "role": "object"},
        {"text": "das", "case": "accusative", "gender": "neuter"},
        {"text": "Buch"},
    ]

    bg = ImageClip(np.zeros((720, 1280, 3), dtype=np.uint8)).set_duration(5)

    sub = subtitle_clip(tokens).set_position(("center", "bottom"))

    final = CompositeVideoClip([bg, sub])
    final.write_videofile("test_output1.mp4", fps=24)