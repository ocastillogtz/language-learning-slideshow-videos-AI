"""
character_art.py
================
Draw a new character "in the series style" with a fal.ai image-edit model.

The edit model receives, in this order:
  1. the hand-made drawing of the new character (its ref_drawing / ref image),
  2. ONE style sample: the existing characters' art side by side,
  3. a prompt (editable in the UI) that says: redraw image 1 in the style of image 2.

Each run is saved as a candidate (assets/characters/<name>/candidates/…) and listed
in the character's "art_candidates"; nothing is overwritten until a candidate is
accepted as the scene reference (art_34left_file_path), turnaround or thumbnail.
"""

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image

import db
from manage_characters import char_folder, load_characters
from utils_config import load_config, workspace_for_assets_dir

logger = logging.getLogger(__name__)

SAMPLE_HEIGHT  = 512      # height of each figure in the style sample
SAMPLE_PER_ROW = 5        # figures per row before wrapping
SAMPLE_GAP     = 24
# Every image slot of a character: slot → (catalog field, file stem). Used by the
# direct upload route too, so field names live in one place.
IMAGE_SLOTS = {
    "scene_reference": ("art_34left_file_path",  "34left"),
    "thumbnail":       ("thumbnail_file_path",   "thumbnail"),
    "turnaround":      ("artwork_file_path",     "art"),
    "reference":       ("ref_image_file_path",   "ref"),
    "drawing":         ("ref_drawing_file_path", "ref_drawing"),
}
# Slots a generated candidate can be accepted into.
TARGETS = {k: IMAGE_SLOTS[k][0] for k in ("scene_reference", "turnaround", "thumbnail")}


def _cover(c: dict) -> str | None:
    """The image that best shows a character's look (full body first)."""
    for f in ("art_34left_file_path", "ref_image_file_path", "artwork_file_path", "thumbnail_file_path"):
        if c.get(f):
            return c[f]
    return None


def style_candidates(assets_dir: Path, exclude: str | None = None) -> list[dict]:
    """Characters that can serve as style examples: [{name, path, default}].
    Defaults to the main cast (characters with a 3/4-left scene reference)."""
    chars = load_characters(assets_dir)
    own = _cover(chars.get(exclude) or {}) if exclude else None
    out, seen = [], {own} if own else set()       # never show the character its own art
    for name, c in chars.items():
        rel = _cover(c)
        if name == exclude or not rel or not (assets_dir / rel).exists() or rel in seen:
            continue
        seen.add(rel)                                    # characters sharing art appear once
        out.append({"name": name, "path": rel, "default": bool(c.get("art_34left_file_path"))})
    return out


def build_style_sample(assets_dir: Path, names: list[str]) -> Image.Image:
    """The chosen characters' art side by side (wrapping into rows) on white."""
    chars = load_characters(assets_dir)
    figures = []
    for n in names:
        rel = _cover(chars.get(n) or {})
        if rel and (assets_dir / rel).exists():
            im = Image.open(assets_dir / rel).convert("RGB")
            w, h = im.size
            figures.append(im.resize((max(1, int(w * SAMPLE_HEIGHT / h)), SAMPLE_HEIGHT), Image.LANCZOS))
    if not figures:
        raise ValueError("Pick at least one existing character with artwork as the style sample.")
    rows = [figures[i:i + SAMPLE_PER_ROW] for i in range(0, len(figures), SAMPLE_PER_ROW)]
    width = max(sum(f.width for f in r) + SAMPLE_GAP * (len(r) + 1) for r in rows)
    height = len(rows) * SAMPLE_HEIGHT + SAMPLE_GAP * (len(rows) + 1)
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    y = SAMPLE_GAP
    for r in rows:
        x = (width - (sum(f.width for f in r) + SAMPLE_GAP * (len(r) - 1))) // 2
        for f in r:
            sheet.paste(f, (x, y))
            x += f.width + SAMPLE_GAP
        y += SAMPLE_HEIGHT + SAMPLE_GAP
    return sheet


def drawing_path(assets_dir: Path, c: dict) -> Path | None:
    """The hand-made drawing of the character (uploaded reference drawing)."""
    for f in ("ref_drawing_file_path", "ref_image_file_path"):
        if c.get(f) and (assets_dir / c[f]).exists():
            return assets_dir / c[f]
    return None


def default_prompt(c: dict, has_drawing: bool) -> str:
    desc = ", ".join(x for x in (c.get("fixed_description"), c.get("variable_description")) if x)
    style = load_config()["image_character_art_style"]
    if has_drawing:
        return (
            f"Image 1 is a hand-made drawing of a new character{': ' + desc if desc else ''}. "
            "Image 2 shows the existing characters of this illustrated series. Redraw the character "
            "from image 1 as ONE full-body figure in a 3/4 left view, in exactly the art style of the "
            "characters in image 2 — same line weight, colouring, proportions, face and eye style — so "
            "the new character clearly belongs to the same series. Keep the identity, hairstyle and "
            "outfit from image 1. Plain white background, nobody else in the picture. " + style
        )
    return (
        "The image shows the existing characters of this illustrated series. Draw ONE new character "
        f"for the series{': ' + desc if desc else ''} — a full-body figure in a 3/4 left view, in "
        "exactly the same art style (line weight, colouring, proportions, face and eye style). "
        "Plain white background, nobody else in the picture. " + style
    )


def generate(assets_dir: Path, name: str, model: str, prompt: str, style_names: list[str],
             image_size: str = "portrait_4_3") -> dict:
    """Run the edit model (PAID) and store the result as a candidate. Returns it."""
    from create_images import _call_fal, _resolve_model, _to_bytes, _upload

    chars = load_characters(assets_dir)
    if name not in chars:
        raise ValueError(f"Character '{name}' not found.")
    c = chars[name]
    endpoint = _resolve_model(load_config(), model)

    urls = []
    drawing = drawing_path(assets_dir, c)
    if drawing:
        img = Image.open(drawing).convert("RGB")
        img.thumbnail((1536, 1536))
        urls.append(_upload(_to_bytes(img)))
    urls.append(_upload(_to_bytes(build_style_sample(assets_dir, style_names))))

    logger.info("Styled character art for '%s' with %s (%d reference images)", name, endpoint, len(urls))
    data = _call_fal(prompt, urls, endpoint, image_size)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rel = f"characters/{char_folder(name)}/candidates/{stamp}.png"
    (assets_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    (assets_dir / rel).write_bytes(data)

    cand = {"path": rel, "model": model or endpoint, "created": stamp,
            "style_sample": style_names, "used_drawing": bool(drawing), "prompt": prompt}

    def _add(chars):                                     # atomic: the call took a while
        if name in chars:
            chars[name].setdefault("art_candidates", []).insert(0, cand)
    db.update_assets("characters", _add, workspace_for_assets_dir(assets_dir))
    return cand


def accept(assets_dir: Path, name: str, rel: str, target: str) -> dict:
    field = TARGETS.get(target)
    if not field:
        raise ValueError(f"target must be one of {list(TARGETS)}")
    def _accept(chars):
        c = chars.get(name)
        if not c or not any(x["path"] == rel for x in c.get("art_candidates", [])):
            raise ValueError("Unknown candidate")
        c[field] = rel
        return c
    return db.update_assets("characters", _accept, workspace_for_assets_dir(assets_dir))


def discard(assets_dir: Path, name: str, rel: str) -> dict:
    def _discard(chars):
        c = chars.get(name)
        if not c:
            raise ValueError(f"Character '{name}' not found.")
        c["art_candidates"] = [x for x in c.get("art_candidates", []) if x["path"] != rel]
        return c
    c = db.update_assets("characters", _discard, workspace_for_assets_dir(assets_dir))
    if not any(c.get(f) == rel for f, _ in IMAGE_SLOTS.values()):
        (assets_dir / rel).unlink(missing_ok=True)
    return c
