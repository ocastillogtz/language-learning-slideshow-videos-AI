"""
grammar_guide.py
================
"grammar_guide" project type: a horizontal 16:9 grammar explainer (e.g. the complete
guide to German declension). A narrator explains, two students ask and try examples.

Every frame is COMPOSED LOCALLY (PIL, no API cost) from a small per-line state:

  ┌──────────────────────────────────────────────────────────────────────┐
  │ [A1] Kapitel 2 · Der bestimmte Artikel        [Akkusativ · Maskulin] │  ← level / chapter / section
  │ ┌────────────────────────────┐ ┌──────────────────────────────────┐ │
  │ │  BOARD (exact table,        │ │ BEISPIEL                         │ │
  │ │  reused all video long,     │ │ Ich sehe den Hund.               │ │  ← example card, case-coloured
  │ │  current cell highlighted)  │ │          AKK·m                   │ │
  │ └────────────────────────────┘ └──────────────────────────────────┘ │
  │                 subtitle (the spoken line, drawn by create_video)    │
  └──────────────────────────────────────────────────────────────────────┘

BOARDS are the reusable visual aids (article table, pronoun table, noun endings,
adjective endings …). Table boards are DRAWN LOCALLY from their spec (free, every
letter exact, highlighted cells filled in the case colour while the rest fade).

Opt-in: "renderer": "ideogram" on a board generates it with fal.ai Ideogram v4 instead
(cached in assets/boards/ by prompt) and needs its cells CALIBRATED (`grid-preview`,
`calibrate`). Tested 2026-10: Ideogram v4 cannot render dense tables reliably (garbled
or wrong cells, false safety blocks) — keep it for text-free art only.

Script fields (per dialog line; every state field PERSISTS until a later line changes it,
"" / null clears it):
  speaker   "Narrator" or one of the two students
  text      the spoken line (subtitle; *bold* / _coloured_ markup allowed)
  chapter   {"title", "level"} → starts a chapter (title card + YouTube timestamp)
  section   upper-right label, e.g. "Akkusativ · Maskulin · n-Deklination"
  case      nom|akk|dat|gen → colour of the section label (neutral when empty)
  board     id of a board in script["boards"]
  highlight list of cell refs on that board: "akk.m" (row.col), "akk" (whole row), "m" (column)
  example   one sentence or a list (max 3) with markup: [den Student{en}|akk.m]
            [...|case.gender] colours a phrase by case and labels it; {..} marks an ending
  note      small grey line under the example, e.g. "der Hund → den Hund"
  tts       optional spoken version of text (e.g. endings as letters: "ein S oder E-S")
  switch_at text fragment where the NEW frame should appear (the line keeps the previous
            frame until then). Automatic for narrator lines that open with a short
            reaction ("Genau.", "Richtig!", "Perfekt!") and change what is on screen.
  illustration {"visual": "English scene description", "characters": ["Jonas", ...]}
            a picture of the example on top of the card (fal.ai, billable, see
            `illustrate`). Cleared by a new "example" that brings no illustration.

CLI
---
  python grammar_guide.py boards <project> [--regenerate ID]   # Ideogram boards only (billable!)
  python grammar_guide.py grid-preview <project> <board_id>   # ruler overlay (free)
  python grammar_guide.py calibrate <project> <board_id> --x 0.05,0.2,... --y 0.1,0.25,...
  python grammar_guide.py illustrate <project>                 # example pictures (billable!)
  python grammar_guide.py compose <project>                    # (re)compose all frames (free)
  python grammar_guide.py cheatsheet <project>                 # A4 PDF: all tables + notes (free)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import unicodedata
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FRAME_REF_TYPE  = "grammar_frame"
BOARD_ASSET_DIR = "boards"
FRAMES_SUBDIR   = "images/guide"
IDEOGRAM_MODEL  = "fal-ai/ideogram-v4"
BOARD_SIZE      = {"width": 1536, "height": 896}

W, H = 1920, 1080

# Case colours — the same palette as the annotated subtitles (ANNOTATION_SCHEMA.md).
# Nature palette (dark green · hunter green · khaki · raw umber · café noir). The four
# case colours stay clearly distinct but earthy: moss · terracotta · lake · heather.
DARK_GREEN, HUNTER_GREEN, KHAKI = (16, 40, 32), (76, 100, 68), (202, 186, 156)
RAW_UMBER, CAFE_NOIR = (138, 98, 64), (77, 45, 24)
CASE_COLORS = {"nom": "#4C6444", "akk": "#B5532A", "dat": "#3D6B85", "gen": "#7A4A68"}
CASE_NAMES  = {"nom": "Nominativ", "akk": "Akkusativ", "dat": "Dativ", "gen": "Genitiv"}
CASE_ALIASES = {"nom": "nom", "nominativ": "nom", "n": "nom",
                "akk": "akk", "acc": "akk", "akkusativ": "akk", "a": "akk",
                "dat": "dat", "dativ": "dat", "d": "dat",
                "gen": "gen", "genitiv": "gen", "g": "gen"}
GENDER_SHORT = {"m": "m", "mask": "m", "maskulin": "m", "f": "f", "fem": "f", "feminin": "f",
                "n": "n", "neut": "n", "neutrum": "n", "pl": "Pl", "plural": "Pl"}
LEVEL_COLORS = {"A1": "#4C6444", "A2": "#6B7B3A", "B1": "#8A6240", "B2": "#4D2D18",
                "C1": "#A0522D", "C2": "#5C3A21"}
NEUTRAL = "#4D2D18"

# Palette of the composed frame.
BG_TOP, BG_BOTTOM = (22, 52, 42), (11, 29, 23)
CARD_BG   = (246, 240, 229)   # beige
BOARD_BG  = (252, 249, 243)
INK       = (47, 30, 18)
MUTED     = (138, 112, 86)
HIGHLIGHT = (233, 212, 156)   # khaki marker behind an emphasised {ending}
ON_DARK   = (240, 233, 220)   # text on the dark-green background

# Layout (1920×1080). Everything above y=750 is ours; below it the subtitle lives.
TOP_Y, TOP_H   = 30, 76
PANEL_Y, PANEL_B = 128, 850
BOARD_X, BOARD_R = 40, 1100
CARD_X, CARD_R   = 1130, 1880

_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_FONT_FILES = {"black": "seguibl.ttf", "bold": "segoeuib.ttf", "regular": "segoeui.ttf",
               "semibold": "seguisb.ttf"}


# Subtitle settings for grammar_guide renders (create_video applies them): a plain
# horizontal YouTube frame needs no Shorts/Reels safe area at the bottom or right.
RENDER_CFG = {"sub_margin_bottom": 36, "sub_margin_left": 40, "sub_margin_right": 40,
              "sub_bg_color": CAFE_NOIR, "sub_bg_opacity": 0.82}


def is_grammar_guide(project_type: dict) -> bool:
    return bool((project_type.get("scene_builder_rules") or {}).get("grammar_guide"))


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for name in (_FONT_FILES.get(weight), _FONT_FILES["bold"], "arialbd.ttf"):
        if name and (_FONT_DIR / name).exists():
            return ImageFont.truetype(str(_FONT_DIR / name), size)
    return ImageFont.load_default()


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_") or "x"


def case_key(value) -> str:
    return CASE_ALIASES.get(_norm(value), "") if value else ""


# =============================================================================
# EXAMPLE MARKUP   "Ich sehe [den Student{en}|akk.m]."
# =============================================================================

_SPAN_RE = re.compile(r"\[([^\]|]+)\|([^\]]+)\]")


def parse_example(text: str) -> list[dict]:
    """Split an example into runs: {"text", "case", "gender"} (case "" = plain).
    Inside a run, {..} marks an emphasised ending (kept in the text, see _ending_parts)."""
    runs, pos = [], 0
    for m in _SPAN_RE.finditer(text or ""):
        if m.start() > pos:
            runs.append({"text": text[pos:m.start()], "case": "", "gender": ""})
        tag = m.group(2).strip().split(".")
        runs.append({"text": m.group(1), "case": case_key(tag[0]),
                     "gender": GENDER_SHORT.get(_norm(tag[1]), tag[1]) if len(tag) > 1 else ""})
        pos = m.end()
    if pos < len(text or ""):
        runs.append({"text": text[pos:], "case": "", "gender": ""})
    return runs


def plain_example(text: str) -> str:
    """The example as plain text (markup removed) — for validation and logs."""
    return "".join(r["text"] for r in parse_example(text)).replace("{", "").replace("}", "")


def _ending_parts(text: str) -> list[tuple[str, bool]]:
    """'Student{en}' → [('Student', False), ('en', True)]."""
    out, pos = [], 0
    for m in re.finditer(r"\{([^}]*)\}", text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


# =============================================================================
# BOARDS  (Ideogram, cached in assets/boards/)
# =============================================================================

def board_prompt(board: dict) -> str:
    """Ideogram prompt for one board spec. Tables list every cell explicitly so the
    model renders the exact German forms; rows are tinted with the case palette."""
    title = board.get("title", "")
    style = (board.get("style") or "").strip()
    lines = [
        "Clean, modern educational grammar chart for German learners. Flat vector infographic,",
        "white background, crisp dark sans-serif text, generous spacing, perfectly aligned",
        "table grid with thin light-grey lines, highly readable, accurate German spelling,",
        "no watermark, no extra words, no people. The chart fills the whole image.",
        "",
        f'Title at the top in bold: "{title}"',
    ]
    if board.get("kind", "table") == "table":
        cols = board.get("columns") or []
        lines += ["", f"A table with {len(cols) + 1} columns and {len(board.get('rows') or []) + 1} rows."]
        lines.append("Header row (bold): " + " | ".join(['""'] + [f'"{c}"' for c in cols]))
        for row in board.get("rows") or []:
            ck = case_key(row.get("label"))
            tint = {"nom": "light green", "akk": "light red", "dat": "light blue",
                    "gen": "light purple"}.get(ck)
            cells = " | ".join(f'"{c}"' for c in row.get("cells") or [])
            label = f'"{row.get("label", "")}"'
            lines.append(f"Row {label}" + (f" (row label on a {tint} background)" if tint else "")
                         + f": {cells}")
        lines.append("Each cell shows exactly the text given, centred in the cell, nothing else.")
    else:
        lines += ["", (board.get("description") or "").strip()]
    if board.get("caption"):
        lines += ["", f'Small caption under the table: "{board["caption"]}"']
    if style:
        lines += ["", style]
    return "\n".join(lines)


def uses_ideogram(board: dict) -> bool:
    return board.get("renderer") == "ideogram"


def board_cache_path(assets_dir: Path, board: dict) -> Path:
    h = hashlib.sha1(board_prompt(board).encode("utf-8")).hexdigest()[:8]
    return assets_dir / BOARD_ASSET_DIR / f"{_slug(board.get('id'))}_{h}.jpg"


def _grid_path(img_path: Path) -> Path:
    return img_path.with_suffix(".grid.json")


def load_grid(img_path: Path) -> dict | None:
    p = _grid_path(img_path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _call_ideogram(prompt: str, out_path: Path) -> None:
    import fal_client
    from dotenv import load_dotenv
    load_dotenv()
    # expansion_model "None": no prompt rewriting (it would paraphrase the exact cell
    # texts) and no expansion fee. v4 ignores the older enable_prompt_expansion flag.
    args = {"prompt": prompt, "image_size": BOARD_SIZE, "expansion_model": "None",
            "rendering_speed": "QUALITY", "num_images": 1, "output_format": "jpeg"}
    result = fal_client.subscribe(IDEOGRAM_MODEL, arguments=args, with_logs=True)
    url = result["images"][0]["url"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        out_path.write_bytes(resp.read())


def _project(project_name: str) -> tuple[dict, Path, Path]:
    cfg = load_config()
    project = cfg["projects_dir"] / project_name
    return cfg, project, project / "project_manifest.json"


def _load_manifest(project_name: str) -> dict:
    _, _, mp = _project(project_name)
    return json.loads(mp.read_text(encoding="utf-8"))


def _save_manifest(project_name: str, manifest: dict) -> None:
    _, _, mp = _project(project_name)
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def guide_boards(manifest: dict) -> dict:
    return (manifest.get("grammar_guide") or {}).get("boards") or {}


def ensure_boards(project_name: str, manifest: dict, *, regenerate: list[str] | None = None) -> dict:
    """Make sure every board has its Ideogram image (cached in assets/boards/, copied into
    the project). Calls fal.ai ONLY for a board without a cached image, or one listed in
    `regenerate`. Mutates manifest["grammar_guide"]["boards"][id]["file"]; caller saves."""
    cfg, project, _ = _project(project_name)
    regenerate = set(regenerate or [])
    failed = []
    for bid, board in guide_boards(manifest).items():
        if not uses_ideogram(board):
            continue                    # drawn locally at compose time
        cached = board_cache_path(cfg["assets_dir"], board)
        if bid in regenerate or not cached.exists():
            logger.info("Generating board '%s' with Ideogram (fal.ai) …", bid)
            try:
                _call_ideogram(board_prompt(board), cached)
            except Exception as e:      # one refused board must not stop the others
                logger.error("Board '%s' failed: %s", bid, str(e)[:300])
                failed.append(bid)
                continue
            _grid_path(cached).unlink(missing_ok=True)   # a new layout needs a new grid
            logger.info("  Cached → %s", cached)
        else:
            logger.info("Reusing cached board '%s': %s", bid, cached.name)
        rel = f"images/boards/{cached.name}"
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, project / rel)
        board["file"] = rel
        board["cache"] = str(cached.relative_to(cfg["assets_dir"]).as_posix())
    if failed:
        logger.error("Boards not generated: %s", ", ".join(failed))
    return manifest


def _board_image_path(project: Path, assets_dir: Path, board: dict) -> Path | None:
    if board.get("file") and (project / board["file"]).exists():
        return project / board["file"]
    cached = board_cache_path(assets_dir, board)
    return cached if cached.exists() else None


def _board_grid(assets_dir: Path, board: dict) -> dict | None:
    cached = board_cache_path(assets_dir, board)
    return load_grid(cached)


def grid_preview(project_name: str, board_id: str, out: Path | None = None) -> Path:
    """Draw a 5 % ruler (and the stored grid, if any) over a board so its row/column
    boundaries can be read off. Free."""
    cfg, project, _ = _project(project_name)
    board = guide_boards(_load_manifest(project_name))[board_id]
    src = _board_image_path(project, cfg["assets_dir"], board)
    if not src:
        raise FileNotFoundError(f"Board '{board_id}' has no image yet — run `boards` first.")
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    w, h = im.size
    f = _font("bold", 18)
    for i in range(1, 20):
        x, y = int(w * i / 20), int(h * i / 20)
        col = (255, 0, 160) if i % 2 == 0 else (255, 150, 220)
        d.line([(x, 0), (x, h)], fill=col, width=1)
        d.line([(0, y), (w, y)], fill=col, width=1)
        d.text((x + 2, 2), f"{i * 5}", font=f, fill=(200, 0, 120))
        d.text((2, y + 2), f"{i * 5}", font=f, fill=(200, 0, 120))
    grid = _board_grid(cfg["assets_dir"], board)
    if grid:
        for x in grid["x"]:
            d.line([(int(x * w), 0), (int(x * w), h)], fill=(0, 170, 0), width=3)
        for y in grid["y"]:
            d.line([(0, int(y * h)), (w, int(y * h))], fill=(0, 170, 0), width=3)
    out = out or project / "images" / "boards" / f"_grid_{board_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def calibrate(project_name: str, board_id: str, xs: list[float], ys: list[float]) -> Path:
    """Store a board's grid: xs = column boundaries left→right (label column first),
    ys = row boundaries top→bottom (header row first), as 0-1 fractions of the image.
    Stored next to the cached image, so every project using the board shares it."""
    cfg, project, _ = _project(project_name)
    board = guide_boards(_load_manifest(project_name))[board_id]
    n_cols = len(board.get("columns") or []) + 1
    n_rows = len(board.get("rows") or []) + 1
    if len(xs) != n_cols + 1 or len(ys) != n_rows + 1:
        raise ValueError(f"Board '{board_id}' needs {n_cols + 1} x and {n_rows + 1} y boundaries "
                         f"(got {len(xs)} / {len(ys)}).")
    if xs != sorted(xs) or ys != sorted(ys):
        raise ValueError("Boundaries must be increasing.")
    cached = board_cache_path(cfg["assets_dir"], board)
    if not cached.exists():
        raise FileNotFoundError(f"Board '{board_id}' has no cached image.")
    _grid_path(cached).write_text(json.dumps({"x": xs, "y": ys}), encoding="utf-8")
    return _grid_path(cached)


# =============================================================================
# HIGHLIGHT REFERENCES   "akk.m" · "akk" · "m" · "du.akk"
# =============================================================================

def _label_matches(token: str, label: str) -> bool:
    t, lab = _norm(token), _norm(label)
    if not t:
        return False
    if t == lab:
        return True
    ck = CASE_ALIASES.get(t)
    if ck and case_key(label) == ck and len(t) > 1:
        return True
    gk = GENDER_SHORT.get(t)
    if gk and GENDER_SHORT.get(lab) == gk:
        return True
    return len(t) >= 3 and lab.startswith(t)


def _find(token: str, labels: list[str]) -> int | None:
    hits = [i for i, lab in enumerate(labels) if _label_matches(token, lab)]
    return hits[0] if len(hits) == 1 else (hits[0] if hits and _norm(token) == _norm(labels[hits[0]]) else None)


def resolve_highlight(board: dict, ref: str) -> list[tuple[int, int]] | None:
    """Cell(s) a ref points at as (row, col) indices (0-based, data rows/cols only).
    None when it can't be resolved."""
    rows = [r.get("label", "") for r in board.get("rows") or []]
    cols = list(board.get("columns") or [])
    parts = [p for p in re.split(r"[.:/]", str(ref)) if p.strip()]
    if len(parts) == 2:
        r, c = _find(parts[0], rows), _find(parts[1], cols)
        if r is None or c is None:                      # "m.akk" / "du.akk" orders
            r2, c2 = _find(parts[1], rows), _find(parts[0], cols)
            if r2 is not None and c2 is not None:
                r, c = r2, c2
        return [(r, c)] if r is not None and c is not None else None
    if len(parts) == 1:
        r = _find(parts[0], rows)
        if r is not None:
            return [(r, c) for c in range(len(cols))]
        c = _find(parts[0], cols)
        if c is not None:
            return [(r, c) for r in range(len(rows))]
    return None


# =============================================================================
# SCRIPT → SCENES
# =============================================================================

STATE_KEYS = ("section", "case", "board", "highlight", "example", "note", "illustration")


def validate_script(script: dict, cast: list[str]) -> list[str]:
    """Problems that would make the video wrong (returned as messages, not raised)."""
    errs = []
    boards = {b.get("id"): b for b in script.get("boards") or [] if isinstance(b, dict)}
    for bid, b in boards.items():
        if not bid:
            errs.append("a board has no id")
        if b.get("kind", "table") == "table":
            n = len(b.get("columns") or [])
            for r in b.get("rows") or []:
                if len(r.get("cells") or []) != n:
                    errs.append(f"board {bid}: row {r.get('label')!r} has {len(r.get('cells') or [])} cells, "
                                f"expected {n}")
    dialog = script.get("dialog") or []
    if dialog and not isinstance(dialog[0].get("chapter"), dict):
        errs.append('dialog[0] must open a chapter ("chapter": {"title", "level"})')
    board = None
    for i, d in enumerate(dialog):
        sp = d.get("speaker")
        if sp != "Narrator" and sp not in cast:
            errs.append(f"dialog[{i}]: speaker {sp!r} is neither Narrator nor in the cast {cast}")
        ch = d.get("chapter")
        if ch is not None and (not isinstance(ch, dict) or not ch.get("title")):
            errs.append(f"dialog[{i}]: chapter needs a title")
        if "board" in d:
            board = d["board"] or None
            if board and board not in boards:
                errs.append(f"dialog[{i}]: unknown board {board!r}")
        if d.get("case") and not case_key(d["case"]):
            errs.append(f"dialog[{i}]: unknown case {d['case']!r}")
        hl = d.get("highlight")
        if hl:
            if not board or board not in boards:
                errs.append(f"dialog[{i}]: highlight without a board")
            else:
                for ref in hl if isinstance(hl, list) else [hl]:
                    if resolve_highlight(boards[board], ref) is None:
                        errs.append(f"dialog[{i}]: highlight {ref!r} matches no cell of board {board!r}")
        il = d.get("illustration")
        if il:
            if not isinstance(il, dict) or not (il.get("visual") or "").strip():
                errs.append(f"dialog[{i}]: illustration needs a \"visual\"")
            else:
                for nm in il.get("characters") or []:
                    if nm not in cast:
                        errs.append(f"dialog[{i}]: illustration character {nm!r} is not in the cast {cast}")
        ex = d.get("example")
        for e in (ex if isinstance(ex, list) else [ex] if ex else []):
            if e.count("[") != e.count("]") or e.count("{") != e.count("}"):
                errs.append(f"dialog[{i}]: unbalanced markup in example {e!r}")
    return errs


REACTION_OPENERS = ("genau", "richtig", "sehr gut", "perfekt", "super", "wunderbar", "ausgezeichnet",
                    "stimmt", "fantastisch", "sehr schön", "gute frage", "klar", "prima", "toll", "ja")
VISIBLE_KEYS = ("section", "case", "board", "highlight", "example", "note", "illustration")


def switch_fraction(item: dict, spoken: str, changed: bool) -> float | None:
    """Where (0-1 of the spoken line) the new frame should appear, or None for 'at once'.
    Estimated from the character position: speech rate within one line is ~constant."""
    if not changed or item.get("chapter"):
        return None
    text = item.get("text", "")
    frag = (item.get("switch_at") or "").strip()
    if frag:
        pos = text.find(frag)
        if pos <= 0:
            return None
        prefix = text[:pos]
    else:
        if (item.get("speaker") or "Narrator") != "Narrator":
            return None
        m = re.match(r"\s*([^.!?]{1,40}[.!?])\s+\S", text)
        if not m:
            return None
        first = m.group(1)
        low = first.lower().strip(" .!?")
        if len(first.split()) > 5 or not any(low.startswith(o) for o in REACTION_OPENERS):
            return None
        prefix = first + " "
    # Map the cut onto the spoken text (it may spell endings differently).
    from utils_markup import strip_for_tts
    plain_prefix, plain_all = strip_for_tts(prefix), strip_for_tts(text)
    if not plain_all:
        return None
    frac = len(plain_prefix) / len(plain_all)
    return round(min(max(frac, 0.0), 0.9), 3)


def build_scenes(gpt_output: dict, chars_data: dict, cast: list[str], *,
                 inter_ms: int, chapter_card_ms: int = 2200) -> list[dict]:
    """One TTS scene per dialog line (each with a composed frame), a pause after each
    line, and a silent title card at every chapter start. The frame state of each line
    is stored in scene["_guide"]; compose_frames() turns it into the image."""
    narrator_voice = chars_data.get("Narrator", {}).get("voice_id", "")
    scenes, idx = [], 1
    state = {k: None for k in STATE_KEYS}
    chapter, chapter_no = None, 0
    narrator_label = gpt_output.get("narrator_label") or "Erzähler"

    def sid() -> str:
        nonlocal idx
        s = f"scene_{idx:03d}"
        idx += 1
        return s

    def frame_image() -> dict:
        return {"file_path": None, "prompt_to_create": "(composed locally — grammar_guide frame)",
                "reference_type": FRAME_REF_TYPE}

    for i, item in enumerate(gpt_output.get("dialog") or []):
        speaker = item.get("speaker") or "Narrator"
        if isinstance(item.get("chapter"), dict) and item["chapter"].get("title"):
            chapter_no += 1
            chapter = {"no": chapter_no, "title": item["chapter"]["title"].strip(),
                       "level": (item["chapter"].get("level") or "").strip().upper()}
            # A new chapter starts from a clean slate (no stale example/highlight).
            state = {k: None for k in STATE_KEYS}
            scenes.append({
                "id": sid(), "description": f"chapter {chapter_no}: {chapter['title']}",
                "characters": [], "image": frame_image(), "audio": None,
                "subtitle_text": None, "duration_ms": chapter_card_ms,
                "_guide": {"card": True, "chapter": chapter},
                "_chapter_start": {"title": chapter["title"], "level": chapter["level"]},
            })
        before = dict(state)
        for k in STATE_KEYS:
            if k in item:
                state[k] = item[k] or None
        if "example" in item and "illustration" not in item:
            state["illustration"] = None     # a picture belongs to its own example
        changed = any(before.get(k) != state.get(k) for k in VISIBLE_KEYS)
        text = item.get("text", "")
        # Optional spoken version: endings read as letters ("E-S") while the subtitle
        # keeps the written form ("-es") — bare "es" would be voiced as the pronoun.
        spoken = (item.get("tts") or "").strip() or text
        voice = (chars_data.get(speaker, {}).get("voice_id") or narrator_voice) \
            if speaker != "Narrator" else narrator_voice
        scenes.append({
            "id": sid(),
            "description": f"guide_{i:03d} [{speaker}] {state.get('section') or ''}".strip(),
            "characters": [speaker] if speaker != "Narrator" else [],
            "_is_guide_line": True, "_dialog_index": i,
            "image": frame_image(),
            "audio": {"type": "tts", "file_path": None, "tts_text": spoken,
                      "voice_id": voice, "duration_ms": None},
            "subtitle_text": text, "duration_ms": None,
            "_guide": {"chapter": chapter, "speaker": speaker,
                       "speakers": ["Narrator", *cast[:2]], "narrator_label": narrator_label,
                       **{k: state[k] for k in STATE_KEYS}},
        })
        frac = switch_fraction(item, spoken, changed)
        if frac:
            # Same line, previous topic's frame first (speaker pill already current).
            scenes[-1]["_guide_before"] = {**scenes[-1]["_guide"], **{k: before[k] for k in STATE_KEYS}}
            scenes[-1]["_switch_frac"] = frac
            # automatic reaction opener → cut at the first breath (see create_video)
            scenes[-1]["_switch_first"] = not (item.get("switch_at") or "").strip()
        scenes.append({"id": sid(), "description": "pause", "characters": [], "image": None,
                       "audio": None, "subtitle_text": None, "duration_ms": inter_ms})
    return scenes


# =============================================================================
# FRAME COMPOSITION (PIL, free)
# =============================================================================

def _background() -> Image.Image:
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    return im


def _pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, font, fill, fg=(255, 255, 255),
          pad_x: int = 26, h: int = TOP_H, anchor_right: bool = False, max_w: int | None = None) -> int:
    """Rounded label; returns its width. anchor_right → x is the right edge."""
    while max_w and d.textlength(text, font=font) + 2 * pad_x > max_w and font.size > 22:
        font = font.font_variant(size=font.size - 2)
    w = int(d.textlength(text, font=font)) + 2 * pad_x
    x0 = x - w if anchor_right else x
    d.rounded_rectangle([x0, y, x0 + w, y + h], radius=h // 2, fill=fill)
    d.text((x0 + w // 2, y + h // 2), text, font=font, fill=fg, anchor="mm")
    return w


def _draw_top(d: ImageDraw.ImageDraw, g: dict) -> None:
    ch = g.get("chapter") or {}
    right = CARD_R
    if g.get("section"):
        col = _hex(CASE_COLORS.get(case_key(g.get("case")), NEUTRAL))
        right -= _pill(d, CARD_R, TOP_Y, g["section"], _font("black", 40), col,
                       anchor_right=True, max_w=CARD_R - 900)
    x = BOARD_X
    if ch.get("level"):
        x += _pill(d, x, TOP_Y, ch["level"], _font("black", 44),
                   _hex(LEVEL_COLORS.get(ch["level"], NEUTRAL))) + 22
    if ch.get("title"):
        title, f = f"Kapitel {ch.get('no', '')} · {ch['title']}", _font("bold", 38)
        while d.textlength(title, font=f) > right - 30 - x and f.size > 22:
            f = f.font_variant(size=f.size - 2)
        d.text((x, TOP_Y + TOP_H // 2), title, font=f, fill=ON_DARK, anchor="lm")


def _shadow_paste(base: Image.Image, im: Image.Image, x: int, y: int, radius: int = 22) -> None:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius=radius, fill=255)
    sh = Image.new("RGBA", (im.size[0] + 60, im.size[1] + 60), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([30, 36, 30 + im.size[0], 36 + im.size[1]], radius=radius,
                                         fill=(0, 0, 0, 140))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    base.paste(sh, (x - 30, y - 30), sh)
    base.paste(im, (x, y), mask)


CASE_TINTS = {"nom": (221, 229, 212), "akk": (243, 219, 204), "dat": (214, 227, 234),
              "gen": (233, 218, 228)}
GRID_LINE = (226, 216, 198)


def _fit(text: str, weight: str, size: int, max_w: float):
    f = _font(weight, size)
    while f.getlength(text) > max_w and size > 14:
        size -= 2
        f = _font(weight, size)
    return f


def _cells_of(board: dict, highlight) -> list[tuple[int, int]]:
    cells = []
    for ref in (highlight if isinstance(highlight, list) else [highlight] if highlight else []):
        cells += resolve_highlight(board, ref) or []
    return sorted(set(cells))


def render_table(board: dict, w: int, h: int, highlight=None, case: str = "",
                 scale: float = 1.0) -> Image.Image:
    """Draw a table board exactly from its spec at w×h. Highlighted cells are filled with
    the case colour (contiguous runs framed as one band); when anything is highlighted
    the other cells fade so the eye lands on the form being discussed."""
    im = Image.new("RGB", (w, h), BOARD_BG)
    d = ImageDraw.Draw(im)
    k = scale
    pad = int(30 * k)
    cols, rows = list(board.get("columns") or []), list(board.get("rows") or [])
    title = board.get("title", "")
    tf = _fit(title, "black", int(46 * k), w - 2 * pad)
    d.text((w // 2, pad + 4), title, font=tf, fill=INK, anchor="mt")
    top = pad + 4 + tf.size + int(22 * k)
    bottom = h - pad
    if board.get("caption"):
        cf = _fit(board["caption"], "semibold", int(28 * k), w - 2 * pad)
        d.text((w // 2, bottom), board["caption"], font=cf, fill=MUTED, anchor="md")
        bottom -= cf.size + int(18 * k)
    n_rows = len(rows) + 1
    row_h = (bottom - top) / n_rows
    label_w = max([_font("bold", int(40 * k)).getlength(r.get("label", "")) for r in rows] + [0]) + 48 * k
    label_w = min(label_w, (w - 2 * pad) * 0.34)
    col_w = (w - 2 * pad - label_w) / max(1, len(cols))
    xs = [pad, pad + label_w] + [pad + label_w + col_w * (i + 1) for i in range(len(cols))]
    ys = [top + row_h * i for i in range(n_rows + 1)]

    # One size for every data cell so the table reads evenly.
    size = int(min(row_h * 0.64, 52 * k))
    texts = [c for r in rows for c in r.get("cells") or []]
    while size > 16 and any(_font("black", size).getlength(t) > col_w - 24 * k for t in texts):
        size -= 2
    cell_f, cell_hf = _font("semibold", size), _font("black", size)
    head_size = int(min(max(size * 0.82, row_h * 0.5), 36 * k))
    while head_size > 14 and any(_font("bold", head_size).getlength(c) > col_w - 16 for c in cols):
        head_size -= 2
    head_f = _font("bold", head_size)
    lab_size = min(int(row_h * 0.56), int(40 * k))
    while lab_size > 14 and any(_font("bold", lab_size).getlength(r.get("label", "")) > label_w - 28
                                for r in rows):
        lab_size -= 2
    lab_f = _font("bold", lab_size)

    hl = _cells_of(board, highlight)
    hl_set = set(hl)
    col = _hex(CASE_COLORS.get(case_key(case), "#8A6240"))
    tint = tuple(int(255 - (255 - c) * 0.22) for c in col)
    faded = (192, 178, 158) if hl else INK

    for r, row in enumerate(rows):                       # row labels, tinted by case
        y0, y1 = ys[r + 1], ys[r + 2]
        d.rectangle([xs[0], y0, xs[1], y1], fill=CASE_TINTS.get(case_key(row.get("label")), (238, 230, 216)))
        d.text(((xs[0] + xs[1]) / 2, (y0 + y1) / 2), row.get("label", ""), font=lab_f, fill=INK, anchor="mm")
    for c, name in enumerate(cols):                      # header
        d.text(((xs[c + 1] + xs[c + 2]) / 2, (ys[0] + ys[1]) / 2), name, font=head_f,
               fill=CAFE_NOIR, anchor="mm")
    # A highlighted cell takes its ROW's case colour when the row is a case (Akkusativ
    # row → terracotta) — the section may mix cases; other boards use the line's case.
    def row_col(r):
        rk = case_key(rows[r].get("label"))
        return _hex(CASE_COLORS[rk]) if rk else col

    def tint_of(c3):
        return tuple(int(255 - (255 - v) * 0.22) for v in c3)
    for r, c in hl:                                      # highlight fills, under the text
        d.rectangle([xs[c + 1], ys[r + 1], xs[c + 2], ys[r + 2]], fill=tint_of(row_col(r)))
    for y in ys[2:-1]:                                   # grid
        d.line([(xs[0], y), (xs[-1], y)], fill=GRID_LINE, width=max(2, int(2 * k)))
    d.line([(xs[0], ys[1]), (xs[-1], ys[1])], fill=KHAKI, width=max(3, int(3 * k)))
    for x in xs[1:-1]:
        d.line([(x, ys[0]), (x, ys[-1])], fill=GRID_LINE, width=max(2, int(2 * k)))
    for r, row in enumerate(rows):                       # cells
        for c, text in enumerate(row.get("cells") or []):
            on = (r, c) in hl_set
            d.text(((xs[c + 1] + xs[c + 2]) / 2, (ys[r + 1] + ys[r + 2]) / 2), text,
                   font=cell_hf if on else cell_f, fill=row_col(r) if on else faded, anchor="mm")

    def rect(r, c):
        return (xs[c + 1], ys[r + 1], xs[c + 2], ys[r + 2])
    for x0, y0, x1, y1 in _merge_cells(hl, rect):        # one frame per highlighted band
        r0 = min(range(len(rows)), key=lambda r: abs(ys[r + 1] - y0))
        one_row = abs(ys[r0 + 2] - y1) < 1
        d.rounded_rectangle([x0 + 3, y0 + 3, x1 - 3, y1 - 3], radius=int(12 * k),
                            outline=row_col(r0) if one_row else col,
                            width=max(6, int(6 * k)))
    return im


def _board_panel(board: dict | None, img_path: Path | None, grid: dict | None,
                 highlight, case: str, box: tuple[int, int, int, int]) -> Image.Image:
    """The board drawn into `box` (w, h), with highlighted cells."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    if board and not uses_ideogram(board) and board.get("kind", "table") == "table":
        return render_table(board, bw, bh, highlight, case)
    if not img_path:
        im = Image.new("RGB", (bw, bh), CARD_BG)
        d = ImageDraw.Draw(im)
        d.text((bw // 2, bh // 2 - 30), (board or {}).get("title", "Board"), font=_font("black", 48),
               fill=INK, anchor="mm")
        d.text((bw // 2, bh // 2 + 30), "(board image not generated yet)", font=_font("regular", 30),
               fill=MUTED, anchor="mm")
        return im
    src = Image.open(img_path).convert("RGB")
    s = min(bw / src.width, bh / src.height)
    src = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    im = Image.new("RGB", (bw, bh), (255, 255, 255))
    ox, oy = (bw - src.width) // 2, (bh - src.height) // 2
    im.paste(src, (ox, oy))
    cells = []
    for ref in (highlight if isinstance(highlight, list) else [highlight] if highlight else []):
        cells += resolve_highlight(board, ref) or []
    if cells and grid:
        xs, ys = grid["x"], grid["y"]

        def rect(r, c):   # data cell (r, c) → pixel rect in the panel (skip header/label)
            return (ox + xs[c + 1] * src.width, oy + ys[r + 1] * src.height,
                    ox + xs[c + 2] * src.width, oy + ys[r + 2] * src.height)
        rects = _merge_cells(sorted(set(cells)), rect)
        dim = Image.new("RGBA", im.size, (15, 20, 30, 120))
        md = ImageDraw.Draw(dim)
        for x0, y0, x1, y1 in rects:
            md.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], fill=(0, 0, 0, 0))
        im = Image.alpha_composite(im.convert("RGBA"), dim).convert("RGB")
        d = ImageDraw.Draw(im)
        col = _hex(CASE_COLORS.get(case_key(case), "#F59E0B"))
        for x0, y0, x1, y1 in rects:
            d.rounded_rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], radius=10, outline=col, width=7)
    return im


def _merge_cells(cells: list[tuple[int, int]], rect) -> list[tuple]:
    """Adjacent highlighted cells of one row (or one column) become a single band,
    so a whole row/column reads as one highlight instead of a row of boxes."""
    rows: dict[int, list[int]] = {}
    for r, c in cells:
        rows.setdefault(r, []).append(c)
    runs = []                                    # (row, first col, last col)
    for r, cs in rows.items():
        start = prev = cs[0]
        for c in cs[1:] + [None]:
            if c is not None and c == prev + 1:
                prev = c
                continue
            runs.append((r, start, prev))
            if c is not None:
                start = prev = c
    # Single-cell runs stacked in the same column → one vertical band.
    singles = [(r, a) for r, a, b in runs if a == b]
    out, used = [], set()
    for r, a, b in runs:
        if a != b:
            x0, y0, _, y1 = rect(r, a)
            out.append((x0, y0, rect(r, b)[2], y1))
    for r, c in singles:
        if (r, c) in used:
            continue
        r_end = r
        while (r_end + 1, c) in singles:
            r_end += 1
        for k in range(r, r_end + 1):
            used.add((k, c))
        x0, y0, x1, _ = rect(r, c)
        out.append((x0, y0, x1, rect(r_end, c)[3]))
    return out


def _layout_example(text: str, font, label_font, max_w: int) -> list[list[dict]]:
    """Wrap one marked example into lines of units (a coloured span never breaks)."""
    units = []
    for run in parse_example(text):
        if run["case"]:
            units.append({**run, "w": _text_w(run["text"], font)})
        else:
            for part in re.findall(r"\S+|\s+", run["text"]):
                if not part.isspace():
                    # Text touching the previous unit (e.g. the "." after a coloured
                    # phrase) is glued to it so a line break can't separate them.
                    glue = bool(units) and not units[-1].get("space")
                    units.append({**run, "text": part, "w": _text_w(part, font), "glue": glue})
                elif units:
                    units[-1]["space"] = True
    lines, cur, cur_w = [], [], 0
    sp = font.getlength(" ")
    for u in units:
        add = u["w"] + (sp if cur and cur[-1].get("space") else 0)
        if cur and cur_w + add > max_w:
            carry = [cur.pop()] if u.get("glue") and len(cur) > 1 else []
            lines.append(cur)
            cur, cur_w = carry, sum(c["w"] for c in carry)
            add = u["w"]
        cur.append(u)
        cur_w += add
    if cur:
        lines.append(cur)
    return lines


def _text_w(text: str, font) -> float:
    return sum(font.getlength(t) for t, _ in _ending_parts(text))


def _draw_example(im: Image.Image, text: str, x: int, y: int, max_w: int, size: int) -> int:
    """Draw one example at (x, y); returns the y below it."""
    d = ImageDraw.Draw(im)
    font, label_font = _font("bold", size), _font("black", max(20, size * 2 // 5))
    lines = _layout_example(text, font, label_font, max_w)
    sp = font.getlength(" ")
    line_h = int(size * 1.25)
    for line in lines:
        has_label = any(u["case"] for u in line)
        cx = x
        for k, u in enumerate(line):
            if k and line[k - 1].get("space"):
                cx += sp
            col = _hex(CASE_COLORS[u["case"]]) if u["case"] else INK
            ux = cx
            for part, is_end in _ending_parts(u["text"]):
                pw = font.getlength(part)
                if is_end:
                    d.rounded_rectangle([ux - 2, y + size * 0.18, ux + pw + 2, y + size * 1.12],
                                        radius=6, fill=HIGHLIGHT)
                d.text((ux, y), part, font=font, fill=col)
                if is_end:
                    d.line([(ux, y + size * 1.14), (ux + pw, y + size * 1.14)], fill=col, width=4)
                ux += pw
            if u["case"]:
                lab = CASE_NAMES[u["case"]][:3].upper() + (f" · {u['gender']}" if u["gender"] else "")
                d.text((cx + u["w"] / 2, y + line_h + 8), lab, font=label_font, fill=col, anchor="mt")
            cx += u["w"]
        y += line_h + (label_font.size + 22 if has_label else 6)
    return y


def _speaker_row(d: ImageDraw.ImageDraw, g: dict, x: int, y: int, max_x: int) -> None:
    speaker = g.get("speaker")
    f = _font("bold", 26)
    for name in g.get("speakers") or []:
        label = g.get("narrator_label") or "Erzähler" if name == "Narrator" else name
        active = name == speaker
        w = int(d.textlength(label, font=f)) + 36
        if x + w > max_x:
            break
        d.rounded_rectangle([x, y, x + w, y + 44], radius=22,
                            fill=CAFE_NOIR if active else (232, 222, 204))
        d.text((x + w // 2, y + 22), label, font=f, fill=(255, 255, 255) if active else MUTED, anchor="mm")
        x += w + 12


def _card(g: dict, w: int, h: int, illus: Image.Image | None = None) -> Image.Image:
    im = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(im)
    pad = 40
    examples = g.get("example")
    examples = examples if isinstance(examples, list) else [examples] if examples else []
    examples = [e for e in examples if e][:3]
    y = pad
    if illus is not None:
        # The picture of the example on top (centre-cropped to the slot), sentence below.
        # A shorter picture when the card also carries a second example or a note.
        busy = len(examples) > 1 or bool(g.get("note"))
        iw, ih = w - 2 * 24, int(h * (0.46 if busy else 0.55))
        s = max(iw / illus.width, ih / illus.height)
        pic = illus.convert("RGB").resize((int(illus.width * s) + 1, int(illus.height * s) + 1), Image.LANCZOS)
        top = int((pic.height - ih) * 0.3)        # keep faces: crop mostly from the bottom
        pic = pic.crop(((pic.width - iw) // 2, top, (pic.width - iw) // 2 + iw, top + ih))
        mask = Image.new("L", (iw, ih), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, iw - 1, ih - 1], radius=16, fill=255)
        im.paste(pic, (24, 24), mask)
        y = 24 + ih + 22
    if examples:
        if illus is None:
            d.text((pad, y), "BEISPIEL" if len(examples) == 1 else "BEISPIELE", font=_font("black", 26),
                   fill=MUTED)
            y += 56
    # Examples, the gaps between them and the note shrink TOGETHER until all of it ends
    # above the speaker pills (the note used to be drawn wherever the examples ended).
    limit = h - (44 + 28 + 14 if g.get("speakers") else 30)   # room for the speaker pills, if any
    note = g.get("note") or ""
    size = ((60 if len(examples) == 1 else 50) if illus is None else 48) if examples else 0

    def note_metrics(sz):
        nf = _font("semibold", max(22, min(34, int(sz * 0.7)) if sz else 34))
        return nf, int(nf.size * 1.35), _wrap(note, nf, w - 2 * pad, d) if note else []

    while True:
        gap = max(6, int(size * 0.3))
        yy = y
        probe = Image.new("RGB", (w, h * 3))
        for e in examples:
            yy = _draw_example(probe, e, pad, yy, w - 2 * pad, size) + gap
        nf, nlh, nlines = note_metrics(size)
        if yy + len(nlines) * nlh <= limit or size <= 24 or not examples:
            break
        size -= 2
    for e in examples:
        y = _draw_example(im, e, pad, y, w - 2 * pad, size) + gap
    for line in nlines:
        d.text((pad, y), line, font=nf, fill=MUTED)
        y += nlh
    _speaker_row(d, g, pad, h - 44 - 28, w - pad)
    return im


def _wrap(text: str, font, max_w: int, d: ImageDraw.ImageDraw) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = f"{cur} {wd}".strip()
        if cur and d.textlength(t, font=font) > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    return lines + ([cur] if cur else [])


def _chapter_card(g: dict) -> Image.Image:
    im = _background()
    d = ImageDraw.Draw(im)
    ch = g.get("chapter") or {}
    d.text((W // 2, H // 2 - 120), f"KAPITEL {ch.get('no', '')}", font=_font("black", 54),
           fill=KHAKI, anchor="mm")
    f = _font("black", 110)
    lines = _wrap(ch.get("title", ""), f, W - 300, d)
    y = H // 2 - 20
    for ln in lines:
        d.text((W // 2, y), ln, font=f, fill=ON_DARK, anchor="mm")
        y += 128
    if ch.get("level"):
        f2 = _font("black", 48)
        w = int(d.textlength(ch["level"], font=f2)) + 60
        _pill(d, W // 2 - w // 2, y + 10, ch["level"], f2,
              _hex(LEVEL_COLORS.get(ch["level"], NEUTRAL)), h=80)
    return im


def render_frame(g: dict, boards: dict, project: Path, assets_dir: Path) -> Image.Image:
    if g.get("card"):
        return _chapter_card(g)
    im = _background()
    d = ImageDraw.Draw(im)
    _draw_top(d, g)
    board = boards.get(g.get("board")) if g.get("board") else None
    if board:
        panel = _board_panel(board, _board_image_path(project, assets_dir, board),
                             _board_grid(assets_dir, board), g.get("highlight"), g.get("case"),
                             (BOARD_X, PANEL_Y, BOARD_R, PANEL_B))
        _shadow_paste(im, panel, BOARD_X, PANEL_Y)
        card_x = CARD_X
    else:
        card_x = BOARD_X        # no board → the card takes the whole width
    illus = None
    if g.get("illustration"):
        ip = project / illustration_rel(g["illustration"])
        illus = Image.open(ip) if ip.exists() else None
    _shadow_paste(im, _card(g, CARD_R - card_x, PANEL_B - PANEL_Y, illus), card_x, PANEL_Y)
    return im


def _frame_key(g: dict, boards: dict, assets_dir: Path, project: Path | None = None) -> str:
    board = boards.get(g.get("board")) if g.get("board") else None
    extra = {"spec": board} if board else {}
    if g.get("illustration") and project is not None:
        ip = project / illustration_rel(g["illustration"])
        extra["illus"] = int(ip.stat().st_mtime) if ip.exists() else None
    if board and uses_ideogram(board):
        cached = board_cache_path(assets_dir, board)
        extra = {"board_img": cached.name if cached.exists() else None,
                 "grid": load_grid(cached) if cached.exists() else None, "spec": board}
    blob = json.dumps({"g": g, **extra, "v": 8}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def compose_frames(project_name: str, manifest: dict, *, scene_ids: list[str] | None = None) -> int:
    """Render (or reuse) the composed frame of every grammar_guide scene and point the
    scene image at it. Identical frame states share one file. Free. Returns how many
    new frames were drawn. Mutates the manifest; the caller saves it."""
    cfg, project, _ = _project(project_name)
    boards = guide_boards(manifest)
    out_dir = project / FRAMES_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    drawn = 0
    for s in manifest.get("scenes", []):
        g = s.get("_guide")
        if not g or (scene_ids and s["id"] not in scene_ids):
            continue
        key = _frame_key(g, boards, cfg["assets_dir"], project)
        rel = f"{FRAMES_SUBDIR}/{key}.png"
        if not (project / rel).exists():
            render_frame(g, boards, project, cfg["assets_dir"]).save(project / rel)
            drawn += 1
        img = s.setdefault("image", {})
        img["file_path"] = rel
        img["reference_type"] = FRAME_REF_TYPE
        gb = s.get("_guide_before")
        if gb:
            kb = _frame_key(gb, boards, cfg["assets_dir"], project)
            rel_b = f"{FRAMES_SUBDIR}/{kb}.png"
            if not (project / rel_b).exists():
                render_frame(gb, boards, project, cfg["assets_dir"]).save(project / rel_b)
                drawn += 1
            img["file_path_before"] = rel_b
        else:
            img.pop("file_path_before", None)
    return drawn


def prepare_images(project_name: str, manifest: dict, *, generate_boards: bool = True) -> None:
    """Image step for a grammar_guide project: boards (Ideogram, cached) + frames."""
    if generate_boards and any(uses_ideogram(b) for b in guide_boards(manifest).values()):
        ensure_boards(project_name, manifest)
    if generate_boards and illustration_specs(manifest):
        generate_illustrations(project_name, manifest)
    n = compose_frames(project_name, manifest)
    logger.info("grammar_guide: %d new frame(s) composed.", n)


# =============================================================================
# ILLUSTRATIONS (fal.ai, billable)
# =============================================================================

ILLUS_SUBDIR = "images/illus"
ILLUS_FRAMING = ("Horizontal 16:9 widescreen composition, medium shot. The characters and the key "
                 "object of the action are large and centred in the frame, clearly readable at small "
                 "size; simple background that fits the situation.")


def illustration_prompt(spec: dict, chars_data: dict) -> str:
    from create_script import _action_single_prompt, _action_both_prompt, _load_style_tokens
    import create_script
    names = [n for n in spec.get("characters") or [] if n in chars_data]
    loc = "the everyday place described in the Action below"
    if len(names) == 1:
        from create_script import _only_these_in_shot
        # The default limiter ("draw no other people") also deletes the extras an example
        # needs (the children Jonas helps, the colleague Vitoria asks) — allow generic extras.
        return _action_single_prompt(names[0], chars_data[names[0]], loc, spec["visual"],
                                     ILLUS_FRAMING).replace(
            _only_these_in_shot([names[0]]),
            f"{names[0]} is the only character from the reference images. Any other people the "
            "Action mentions (children, a colleague, a shop assistant, friends …) MUST also be drawn, "
            "as generic people with their own simple look.")
    if len(names) >= 2:
        a, b = names[:2]
        return _action_both_prompt(a, chars_data[a], b, chars_data[b], loc, spec["visual"], ILLUS_FRAMING)
    _load_style_tokens()
    return (f"{create_script._STYLE_TOKENS}\nFRAMING: {ILLUS_FRAMING}\n\n"
            f"Action: {spec['visual']}\n\nNo people unless described. "
            "No text, no subtitles, no speech bubbles, no watermarks.")


def illustration_rel(spec: dict) -> str:
    blob = json.dumps({"v": spec.get("visual"), "c": spec.get("characters") or []}, sort_keys=True,
                      ensure_ascii=False)
    return f"{ILLUS_SUBDIR}/{hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]}.png"


def illustration_specs(manifest: dict) -> list[dict]:
    seen, out = set(), []
    for s in manifest.get("scenes", []):
        spec = (s.get("_guide") or {}).get("illustration")
        if spec and illustration_rel(spec) not in seen:
            seen.add(illustration_rel(spec))
            out.append(spec)
    return out


def generate_illustrations(project_name: str, manifest: dict, *, regenerate: bool = False) -> list[str]:
    """Generate every missing example illustration with the project's fal model and the
    characters' reference art. BILLABLE: one fal call per missing picture. Returns the
    project-relative paths of the pictures that failed."""
    from create_images import _char_ref_path, _edit_with_refs, _call_fal_text_only, _resolve_model
    from utils_config import load_new_characters, apply_video_format
    cfg, project, _ = _project(project_name)
    apply_video_format(cfg, "horizontal")
    chars_data = load_new_characters(cfg["assets_dir"])
    model = _resolve_model(cfg, None)
    failed = []
    specs = illustration_specs(manifest)
    for k, spec in enumerate(specs, 1):
        rel = illustration_rel(spec)
        dest = project / rel
        if dest.exists() and not regenerate:
            continue
        names = [n for n in spec.get("characters") or [] if n in chars_data]
        refs = [_char_ref_path(chars_data[n], cfg["assets_dir"]) for n in names]
        prompt = illustration_prompt(spec, chars_data)
        logger.info("Illustration %d/%d (%s): %s", k, len(specs), ", ".join(names) or "no cast",
                    spec["visual"][:70])
        try:
            data = (_edit_with_refs(prompt, refs, model, cfg["fal_t2i_model"], cfg["fal_image_size"])
                    if refs else _call_fal_text_only(prompt, cfg["fal_t2i_model"], cfg["fal_image_size"]))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except Exception as e:
            logger.error("  failed: %s", str(e)[:300])
            failed.append(rel)
    return failed


# =============================================================================
# CHAPTERS → YOUTUBE TIMESTAMPS
# =============================================================================

def _ts(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def compute_chapters(manifest: dict, durations: dict[str, float], intro_dur_s: float,
                     speed_factor: float) -> list[dict]:
    """Start of every chapter in the FINAL video ([intro] + speed(content)), from the
    real clip durations (scene id → seconds, only clips that exist)."""
    speed = float(speed_factor) or 1.0
    running, out = 0.0, []
    for s in manifest.get("scenes", []):
        if s["id"] not in durations:
            continue
        if s.get("_chapter_start"):
            c = s["_chapter_start"]
            out.append({"t_ms": int(round((intro_dur_s + running / speed) * 1000)),
                        "title": c["title"], "level": c.get("level", "")})
        running += durations[s["id"]]
    return out


def chapters_text(chapters: list[dict]) -> str:
    """YouTube chapter list: must start at 00:00 (an "Intro" line is added when the
    first chapter starts later, e.g. after the branding intro)."""
    if not chapters:
        return ""
    # YouTube: the list must start at 00:00 and every chapter must last >= 10 s. A short
    # branding intro is folded into the first chapter; a long one gets its own line.
    chapters = [dict(c) for c in chapters]
    lines = []
    if chapters[0]["t_ms"] >= 10_000:
        lines.append("00:00 Intro")
    else:
        chapters[0]["t_ms"] = 0
    for c in chapters:
        lvl = f" ({c['level']})" if c.get("level") else ""
        lines.append(f"{_ts(c['t_ms'] / 1000)} {c['title']}{lvl}")
    return "\n".join(lines)


# =============================================================================
# CHEATSHEET (A4 PDF + PNG pages, free)
# =============================================================================

A4_W, A4_H = 1654, 2339          # A4 at 200 dpi
SHEET_MARGIN = 90


def _sheet_page(title: str, page_no: int) -> tuple[Image.Image, int]:
    im = Image.new("RGB", (A4_W, A4_H), (250, 246, 238))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, A4_W, 150], fill=DARK_GREEN)
    d.text((SHEET_MARGIN, 75), title, font=_fit(title, "black", 54, A4_W - 2 * SHEET_MARGIN - 160),
           fill=ON_DARK, anchor="lm")
    d.text((A4_W - SHEET_MARGIN, 75), f"{page_no}", font=_font("black", 44), fill=KHAKI, anchor="rm")
    d.rectangle([0, A4_H - 70, A4_W, A4_H], fill=HUNTER_GREEN)
    d.text((A4_W // 2, A4_H - 35), "Deutsch mit Brezel · Spickzettel zum Video", font=_font("semibold", 28),
           fill=ON_DARK, anchor="mm")
    return im, 190


def _table_height(board: dict) -> int:
    n = len(board.get("rows") or []) + 1
    return 150 + n * (64 if n > 6 else 78) + (50 if board.get("caption") else 0)


def _note_box(note: dict, w: int) -> Image.Image:
    """A boxed info block: heading + bullet lines (wrapped)."""
    head_f, body_f, bold_f = _font("black", 40), _font("regular", 32), _font("bold", 32)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = []
    for item in note.get("lines") or []:
        label, _, rest = item.partition(": ") if ": " in item else ("", "", item)
        # First line starts after the bold label, continuation lines at the text edge.
        first_w = w - 110 - (int(bold_f.getlength(label + ": ")) if label else 0)
        words, wrapped, cur = rest.split(), [], ""
        for wd in words:
            t = f"{cur} {wd}".strip()
            if cur and probe.textlength(t, font=body_f) > (first_w if not wrapped else w - 110):
                wrapped.append(cur)
                cur = wd
            else:
                cur = t
        wrapped.append(cur)
        lines.append((label, wrapped))
    h = 40 + 56 + sum(len(wl) * 44 + 12 for _, wl in lines) + 24
    im = Image.new("RGB", (w, h), BOARD_BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 10, h], fill=_hex(CASE_COLORS.get(case_key(note.get("case")), "#8A6240")))
    d.text((40, 30), note.get("heading", ""), font=head_f, fill=CAFE_NOIR)
    y = 30 + 66
    for label, wl in lines:
        d.text((44, y + 18), "•", font=bold_f, fill=RAW_UMBER, anchor="lm")
        x = 74
        if label:
            d.text((x, y), label + ":", font=bold_f, fill=INK)
            x += int(bold_f.getlength(label + ": "))
        for k, ln in enumerate(wl):
            d.text((x if k == 0 else 74, y + k * 44), ln, font=body_f, fill=INK)
        y += len(wl) * 44 + 12
    return im


def make_cheatsheet(project_name: str, manifest: dict) -> list[Path]:
    """Render every board of the project plus the script's "cheatsheet" notes onto A4
    pages: projects/<p>/cheatsheet/<name>.pdf (+ one PNG per page). Free."""
    _, project, _ = _project(project_name)
    gg = manifest.get("grammar_guide") or {}
    sheet = gg.get("cheatsheet") or {}
    title = sheet.get("title") or "Spickzettel"
    blocks = []
    for bid in sheet.get("boards") or list(guide_boards(manifest)):
        b = guide_boards(manifest).get(bid)
        if b and b.get("kind", "table") == "table":
            blocks.append(("table", b))
    blocks += [("note", n) for n in sheet.get("notes") or []]

    out_dir = project / "cheatsheet"
    out_dir.mkdir(parents=True, exist_ok=True)
    w = A4_W - 2 * SHEET_MARGIN
    pages, page_no = [], 1
    page, y = _sheet_page(title, page_no)
    for kind, data in blocks:
        img = (render_table(data, w, _table_height(data), scale=1.35) if kind == "table"
               else _note_box(data, w))
        if y + img.height > A4_H - 110:
            pages.append(page)
            page_no += 1
            page, y = _sheet_page(title, page_no)
        _shadow_paste(page, img, SHEET_MARGIN, y, radius=18)
        y += img.height + 44
    pages.append(page)

    stem = _slug(sheet.get("file_name") or title)
    paths = []
    for i, pg in enumerate(pages, 1):
        pp = out_dir / f"{stem}_S{i}.png"
        pg.save(pp)
        paths.append(pp)
    pdf = out_dir / f"{stem}.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=200.0)
    return [pdf] + paths


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    logging.getLogger().setLevel(logging.INFO)
    p = argparse.ArgumentParser(description="grammar_guide boards, calibration and frames")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("boards", help="generate missing boards with Ideogram (BILLABLE)")
    b.add_argument("project")
    b.add_argument("--regenerate", action="append", default=[], metavar="BOARD_ID")
    g = sub.add_parser("grid-preview", help="ruler overlay to read cell boundaries (free)")
    g.add_argument("project")
    g.add_argument("board_id")
    c = sub.add_parser("calibrate", help="store a board's row/column boundaries (free)")
    c.add_argument("project")
    c.add_argument("board_id")
    c.add_argument("--x", required=True, help="column boundaries, comma-separated 0-1")
    c.add_argument("--y", required=True, help="row boundaries, comma-separated 0-1")
    il = sub.add_parser("illustrate", help="generate missing example pictures (BILLABLE, fal.ai)")
    il.add_argument("project")
    il.add_argument("--regenerate", action="store_true")
    cs = sub.add_parser("cheatsheet", help="A4 PDF with all tables + notes (free)")
    cs.add_argument("project")
    m = sub.add_parser("compose", help="(re)compose every frame (free)")
    m.add_argument("project")
    a = p.parse_args()

    if a.cmd == "boards":
        man = _load_manifest(a.project)
        ensure_boards(a.project, man, regenerate=a.regenerate)
        compose_frames(a.project, man)
        _save_manifest(a.project, man)
    elif a.cmd == "grid-preview":
        print(grid_preview(a.project, a.board_id))
    elif a.cmd == "calibrate":
        xs = [float(v) for v in a.x.split(",")]
        ys = [float(v) for v in a.y.split(",")]
        print(calibrate(a.project, a.board_id, xs, ys))
        man = _load_manifest(a.project)
        compose_frames(a.project, man)
        _save_manifest(a.project, man)
    elif a.cmd == "illustrate":
        man = _load_manifest(a.project)
        failed = generate_illustrations(a.project, man, regenerate=a.regenerate)
        print(f"{compose_frames(a.project, man)} new frame(s); failed: {failed or 'none'}")
        _save_manifest(a.project, man)
    elif a.cmd == "cheatsheet":
        for path in make_cheatsheet(a.project, _load_manifest(a.project)):
            print(path)
    elif a.cmd == "compose":
        man = _load_manifest(a.project)
        print(f"{compose_frames(a.project, man)} new frame(s)")
        _save_manifest(a.project, man)


if __name__ == "__main__":
    main()
