"""
html_annotation_renderer.py
===========================
Renders a grammar-annotated German sentence as styled HTML/CSS, then rasterizes
it to a transparent PNG via Playwright/Chromium.  The PNG is a drop-in for the
video pipeline: white text with a dark outline, with an optional rounded
semi-transparent dark backing baked in, ready to be placed over a scene image.

This is the "HTML" branch of the two annotation renderers (the other being
Ideogram-via-fal).  Both consume the SAME annotation schema (see below) so they
can be compared on identical input.

ANNOTATION SCHEMA
-----------------
{
  "text": "Gestern ist der Fuchs früh aufgestanden, weil er Hunger hatte.",
  "tokens": [
    {"i": 0, "text": "Gestern"},
    {"i": 1, "text": "ist",  "role": "verb", "group_id": "v1"},
    {"i": 2, "text": "der",  "case": "nominative", "gender": "masculine"},
    {"i": 3, "text": "Fuchs","role": "subject"},
    {"i": 4, "text": "früh"},
    {"i": 5, "text": "aufgestanden,", "role": "verb", "group_id": "v1"},
    ...
  ],
  "spans": [
    {"type": "nebensatz", "token_ids": [6,7,8,9], "verb_final": 9}
  ]
}

Notes
-----
* token field "i" is optional; if omitted, list order is used as the index.
* the ONLY span type drawn is "nebensatz" (subordinate clause), and only when it
  carries a "verb_final" — i.e. the clause actually pushes the conjugated verb to
  the end. That verb-position contrast is the point of the box; clauses without it
  (and the old TEKAMOLO fields) are not boxed.
* A span may use "token_ids" (any list -> min..max contiguous range) or explicit
  "start"/"end" (inclusive).  Boxes are always contiguous ranges.
* spans must be properly nested or disjoint; a partially-overlapping span is
  dropped (with a warning) so the HTML stays valid.
* tokens sharing a "group_id" render in the same colour (separable-verb halves).
* a verb token may carry "infinitive": the dictionary base form. When it differs
  from the (conjugated) word, it is shown in italics *below* the word, so the
  learner sees e.g. "aufgestanden" on top and "aufstehen" beneath.
* a verb token may carry "tense": the conjugation tense (e.g. "Präteritum",
  "Perfekt", "Konjunktiv II"). It is shown as a small label *above* the word.
* every word reserves equal space above and below, so the main word stays on a
  consistent centre line whether or not it has a label above / an infinitive below.
* "verb_final" on a nebensatz span marks the clause-final conjugated verb.

CLI
---
  python html_annotation_renderer.py            # renders the built-in demo cases
  python html_annotation_renderer.py --install  # installs the Chromium browser
"""

from __future__ import annotations

import html as _html
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# DEFAULT STYLE
# =============================================================================

DEFAULT_STYLE: dict[str, Any] = {
    "font_family":     "'DejaVu Sans', 'Noto Sans', Arial, sans-serif",
    "bold_weight":     800,
    "word_size_px":    60,      # main word size (vertical default)
    "note_size_px":    22,      # case/gender label size
    "infinitive_px":   24,      # infinitive (base form) label below a verb
    "infinitive_color": "#ffce5f",  # base-form colour (matches verb role colour)
    "tense_px":        22,      # conjugation-tense label above a verb
    "tense_color":     "#a9b2c2",   # cool grey — reads as grammatical metadata
    "box_label_px":    16,      # TEKAMOLO / Nebensatz tab label size
    "word_color":      "#ffffff",
    "stroke_color":    "#000000",
    "stroke_px":       2,       # text outline thickness
    "max_width_px":    980,     # wrap width (canvas inner width)
    "pad_px":          26,
    "word_gap_px":     14,      # horizontal gap between word columns
    "row_gap_px":      30,      # vertical gap between wrapped rows (room for notes/boxes)

    # case -> colour (note label above the word)
    "case_colors": {
        "nominative": "#5fd25f", "nom": "#5fd25f",
        "accusative": "#ff6b6b", "acc": "#ff6b6b",
        "dative":     "#6ba6ff", "dat": "#6ba6ff",
        "genitive":   "#d07bd0", "gen": "#d07bd0",
    },
    # role -> colour (used when no case is present)
    "role_colors": {
        "verb": "#ffce5f", "subject": "#5fe0c0", "object": "#ff9ad0",
    },
    # Nebensatz (subordinate-clause) box colour. TEKAMOLO fields are no longer boxed.
    "box_colors": {
        "nebensatz": "#14b8a6",
    },
    "box_labels": {
        "nebensatz": "NEBENSATZ",
    },
    # separable-verb group colour palette (cycled per distinct group_id)
    "group_palette": ["#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4", "#84cc16"],
}

# Horizontal (16:9) overrides — bigger canvas, slightly larger type
HORIZONTAL_STYLE_OVERRIDES: dict[str, Any] = {
    "max_width_px": 1640,
    "word_size_px": 56,
}


# =============================================================================
# SCHEMA NORMALISATION
# =============================================================================

def _normalized_tokens(annotation: dict) -> list[dict]:
    toks = []
    for idx, t in enumerate(annotation.get("tokens", [])):
        tt = dict(t)
        tt["i"] = t.get("i", idx)
        toks.append(tt)
    toks.sort(key=lambda t: t["i"])
    # re-index to a dense 0..n-1 range so span ids line up with position
    remap = {t["i"]: pos for pos, t in enumerate(toks)}
    for pos, t in enumerate(toks):
        t["i"] = pos
    return toks, remap


def _normalized_spans(annotation: dict, remap: dict) -> list[dict]:
    out = []
    n = len(remap)
    for s in annotation.get("spans", []):
        # Only subordinate clauses are boxed now (TEKAMOLO fields are no longer
        # drawn), and only when the clause actually moves the conjugated verb to
        # the end — i.e. it carries a verb_final. That verb-position contrast is
        # the whole point of marking a Nebensatz; clauses without it are skipped.
        if s.get("type") != "nebensatz" or s.get("verb_final") is None:
            continue
        ss = dict(s)
        if s.get("token_ids"):
            ids = [remap.get(i, i) for i in s["token_ids"]]
            start, end = min(ids), max(ids)
        elif "start" in s and "end" in s:
            start = remap.get(s["start"], s["start"])
            end   = remap.get(s["end"], s["end"])
        else:
            continue
        start = max(0, start)
        end   = min(n - 1, end)
        if end < start:
            continue
        ss["start"], ss["end"] = start, end
        ss["verb_final"] = remap.get(s["verb_final"], s["verb_final"])
        out.append(ss)
    return out


def _build_span_tree(spans: list[dict]) -> list[dict]:
    """Build a forest of properly-nested spans. Drops partial overlaps."""
    spans = sorted(spans, key=lambda s: (s["start"], -s["end"]))
    roots: list[dict] = []
    stack: list[dict] = []   # open ancestor nodes
    for s in spans:
        node = {"span": s, "children": []}
        while stack and stack[-1]["span"]["end"] < s["start"]:
            stack.pop()
        if stack:
            top = stack[-1]["span"]
            if s["end"] <= top["end"]:
                stack[-1]["children"].append(node)
                stack.append(node)
            else:
                logger.warning("Dropping partially-overlapping span %s", s)
        else:
            roots.append(node)
            stack.append(node)
    return roots


# =============================================================================
# HTML BUILD
# =============================================================================

def _group_color_map(tokens: list[dict], style: dict) -> dict:
    palette = style["group_palette"]
    seen: dict[str, str] = {}
    for t in tokens:
        gid = t.get("group_id")
        if gid and gid not in seen:
            seen[gid] = palette[len(seen) % len(palette)]
    return seen


def _bare_word(text: str) -> str:
    """The word stripped of surrounding punctuation, for comparing to an infinitive."""
    return text.strip(" .,;:!?\"'»«()…-").strip()


# canonical display forms for common German tenses (input is matched case-insensitively)
_TENSE_DISPLAY = {
    "präsens": "Präsens", "praesens": "Präsens", "present": "Präsens",
    "präteritum": "Präteritum", "praeteritum": "Präteritum",
    "preterite": "Präteritum", "imperfekt": "Präteritum",
    "perfekt": "Perfekt", "perfect": "Perfekt",
    "plusquamperfekt": "Plusquamperfekt", "pluperfect": "Plusquamperfekt",
    "futur": "Futur I", "futur i": "Futur I", "futur 1": "Futur I", "future": "Futur I",
    "futur ii": "Futur II", "futur 2": "Futur II",
    "konjunktiv": "Konjunktiv", "konjunktiv i": "Konjunktiv I",
    "konjunktiv ii": "Konjunktiv II", "konjunktiv 2": "Konjunktiv II", "subjunctive": "Konjunktiv II",
    "partizip": "Partizip II", "partizip ii": "Partizip II", "partizip 2": "Partizip II",
    "partizip perfekt": "Partizip II", "participle": "Partizip II",
    "imperativ": "Imperativ", "imperative": "Imperativ",
}


def _tense_label(tense: str) -> str:
    return _TENSE_DISPLAY.get(str(tense).strip().lower(), str(tense).strip())


# German case abbreviations shown above the word (the canonical case value stays
# English internally; only the displayed label is German). e.g. accusative -> AKK.
_CASE_LABELS = {
    "nominative": "NOM", "nom": "NOM",
    "accusative": "AKK", "acc": "AKK", "akk": "AKK",
    "dative": "DAT", "dat": "DAT",
    "genitive": "GEN", "gen": "GEN",
}


def _case_label(case: str) -> str:
    return _CASE_LABELS.get(str(case).strip().lower(), str(case)[:3].upper())


# German role labels shown above the word (role value stays English internally).
_ROLE_LABELS = {
    "subject": "SUBJEKT", "subjekt": "SUBJEKT",
    "object": "OBJEKT", "objekt": "OBJEKT",
}


def _role_label(role: str) -> str:
    return _ROLE_LABELS.get(str(role).strip().lower(), str(role).upper())


def _note_text_and_color(token: dict, style: dict):
    case = token.get("case")
    gender = token.get("gender")
    role = token.get("role")
    if case:
        color = style["case_colors"].get(case, "#cccccc")
        g = {"masculine": "m", "feminine": "f", "neuter": "n",
             "masc": "m", "fem": "f", "neu": "n"}.get(gender or "", "")
        label = _case_label(case) + (" · " + g if g else "")
        return label, color
    if role and role != "verb":
        return _role_label(role), style["role_colors"].get(role, "#cccccc")
    if role == "verb" and token.get("tense"):
        return _tense_label(token["tense"]), style.get("tense_color", "#a9b2c2")
    return None, None


def _token_html(token: dict, group_colors: dict, verb_final_set: set, style: dict) -> str:
    word = _html.escape(token["text"])
    classes = ["word"]
    inline = ""
    if token.get("role") == "verb" or token.get("bold"):
        classes.append("bold")
    gid = token.get("group_id")
    if gid and gid in group_colors:
        classes.append("grp")
        inline = f'style="color:{group_colors[gid]};border-bottom:4px solid {group_colors[gid]};"'

    # ABOVE the word: case/gender, non-verb role, or (for verbs) the conjugation tense
    note_label, note_color = _note_text_and_color(token, style)
    above_html = (
        f'<span class="note" style="color:{note_color}">{_html.escape(note_label)}</span>'
        if note_label else ''
    )

    # BELOW the word: the infinitive (when it differs) then the verb-position marker
    below_parts = []
    inf = (token.get("infinitive") or "").strip()
    if inf and inf.lower() != _bare_word(token["text"]).lower():
        inf_color = style.get("infinitive_color", "#ffce5f")
        below_parts.append(
            f'<span class="infinitive" style="color:{inf_color}">{_html.escape(inf)}</span>'
        )
    if token["i"] in verb_final_set:
        below_parts.append('<span class="verbpos">↳ Verb</span>')
    below_html = "".join(below_parts)

    return (
        '<span class="wordcol">'
        f'<span class="above">{above_html}</span>'
        f'<span class="{" ".join(classes)}" {inline}>{word}</span>'
        f'<span class="below">{below_html}</span>'
        '</span>'
    )


def _slot_lines(token: dict, verb_final_set: set, style: dict) -> tuple[int, int]:
    """How many label lines this token needs above and below the word."""
    above = 1 if _note_text_and_color(token, style)[0] else 0
    below = 0
    inf = (token.get("infinitive") or "").strip()
    if inf and inf.lower() != _bare_word(token["text"]).lower():
        below += 1
    if token["i"] in verb_final_set:
        below += 1
    return above, below


def _box_open(span: dict, style: dict) -> str:
    typ = span["type"]
    color = style["box_colors"].get(typ, "#999999")
    label = style["box_labels"].get(typ, typ.upper())
    dashed = "dashed" if typ == "nebensatz" else "solid"
    return (
        f'<span class="box" style="border:3px {dashed} {color};">'
        f'<span class="box-label" style="background:{color};">{_html.escape(label)}</span>'
    )


def _render_forest(nodes, tokens, lo, hi, group_colors, verb_final_set, style) -> str:
    out = []
    nodes = sorted(nodes, key=lambda nd: nd["span"]["start"])
    i, ni = lo, 0
    while i <= hi:
        if ni < len(nodes) and nodes[ni]["span"]["start"] == i:
            nd = nodes[ni]
            sp = nd["span"]
            inner = _render_forest(nd["children"], tokens, sp["start"], sp["end"],
                                   group_colors, verb_final_set, style)
            out.append(_box_open(sp, style) + inner + "</span>")
            i = sp["end"] + 1
            ni += 1
        else:
            out.append(_token_html(tokens[i], group_colors, verb_final_set, style))
            i += 1
    return "".join(out)


#: style keys scaled together by `font_scale` (everything except the canvas width)
_SCALABLE_KEYS = (
    "word_size_px", "note_size_px", "infinitive_px", "tense_px", "box_label_px",
    "word_gap_px", "row_gap_px", "pad_px", "stroke_px",
)


def _apply_font_scale(st: dict, font_scale: float) -> None:
    """Scale all type sizes / spacing in-place by `font_scale` (max_width_px is left
    untouched so the wrap width still matches the target canvas)."""
    if not font_scale or font_scale == 1.0:
        return
    for k in _SCALABLE_KEYS:
        v = st.get(k)
        if isinstance(v, (int, float)):
            st[k] = max(1, round(v * font_scale))


def render_annotation_html(annotation: dict, style: dict | None = None,
                           horizontal: bool = False, dark_preview: bool = False,
                           backing: bool = False, backing_opacity: float = 0.55,
                           backing_radius: int = 18, font_scale: float = 1.0) -> str:
    """Return a complete standalone HTML document for the annotated sentence.

    backing=True bakes a rounded semi-transparent dark box behind the text (so the
    subtitle stays readable over any scene image).  The box is part of the PNG, so
    no separate backing clip is needed in the video pipeline.

    font_scale multiplies every type size and spacing value at once (the word, the
    tense/case/infinitive labels, box labels, gaps, padding, outline). It is the
    general "make everything bigger/smaller" knob; the wrap width (max_width_px) is
    deliberately *not* scaled so text still wraps to the target canvas. For a single
    specific size instead, pass it through `style`, e.g. style={"word_size_px": 72}.
    Resolution order: defaults -> horizontal overrides -> style -> font_scale.
    """
    st = dict(DEFAULT_STYLE)
    if horizontal:
        st.update(HORIZONTAL_STYLE_OVERRIDES)
    if style:
        st.update(style)
    _apply_font_scale(st, font_scale)

    tokens, remap = _normalized_tokens(annotation)
    spans = _normalized_spans(annotation, remap)
    tree = _build_span_tree(spans)
    group_colors = _group_color_map(tokens, st)
    verb_final_set = {s["verb_final"] for s in spans
                      if s.get("type") == "nebensatz" and s.get("verb_final") is not None}

    body = _render_forest(tree, tokens, 0, len(tokens) - 1,
                          group_colors, verb_final_set, st) if tokens else ""

    # Reserve EQUAL space above and below every word so the main word stays on a
    # consistent centre line regardless of which words have a label / infinitive.
    above_below = [_slot_lines(t, verb_final_set, st) for t in tokens]
    max_above = max((a for a, _ in above_below), default=0)
    max_below = max((b for _, b in above_below), default=0)
    line_h = max(st["note_size_px"], st["infinitive_px"]) + 9   # ~one label line, px
    slot_h = max(max_above, max_below) * line_h                  # symmetric -> word centred

    shadow = ", ".join(
        f"{dx}px {dy}px 0 {st['stroke_color']}"
        for dx in (-st["stroke_px"], 0, st["stroke_px"])
        for dy in (-st["stroke_px"], 0, st["stroke_px"])
        if not (dx == 0 and dy == 0)
    )
    body_bg = "#2b2f36" if dark_preview else "transparent"
    if backing:
        cap_bg = f"rgba(0,0,0,{backing_opacity})"
        cap_radius = backing_radius
    elif dark_preview:
        cap_bg = "#2b2f36"
        cap_radius = 0
    else:
        cap_bg = "transparent"
        cap_radius = 0

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ background:{body_bg}; }}
  #cap {{
    display:inline-block;
    background:{cap_bg};
    border-radius:{cap_radius}px;
    max-width:{st['max_width_px']}px;
    padding:{st['pad_px']}px;
  }}
  .sentence {{
    display:flex; flex-wrap:wrap; align-items:flex-end;
    column-gap:{st['word_gap_px']}px; row-gap:{st['row_gap_px']}px;
    font-family:{st['font_family']};
  }}
  /* each word is: reserved [above] slot, the word, reserved [below] slot.
     Equal slot heights keep the word vertically centred and on one line. */
  .wordcol {{ display:inline-flex; flex-direction:column; align-items:center; }}
  .above {{
    min-height:{slot_h}px; display:flex; align-items:flex-end; justify-content:center;
  }}
  .below {{
    min-height:{slot_h}px; display:flex; flex-direction:column;
    align-items:center; justify-content:flex-start;
  }}
  .note {{
    font-size:{st['note_size_px']}px; font-weight:700; line-height:1.1;
    margin-bottom:4px; letter-spacing:.03em; white-space:nowrap;
  }}
  .word {{
    font-size:{st['word_size_px']}px; color:{st['word_color']};
    line-height:1.0; text-shadow:{shadow};
  }}
  .bold {{ font-weight:{st['bold_weight']}; }}
  .grp {{ padding-bottom:1px; }}
  .infinitive {{
    margin-top:5px; font-size:{st['infinitive_px']}px; font-weight:700;
    font-style:italic; line-height:1.1; white-space:nowrap;
    text-shadow:{shadow};
  }}
  .verbpos {{
    margin-top:4px; font-size:{st['note_size_px']}px; font-weight:700;
    color:#14b8a6; white-space:nowrap;
  }}
  .box {{
    display:inline-flex; flex-wrap:wrap; align-items:flex-end; align-content:flex-end;
    position:relative; border-radius:10px; padding:14px 12px 10px 12px;
    column-gap:{st['word_gap_px']}px; row-gap:{st['row_gap_px']}px;
    max-width:100%;             /* long clauses wrap inside the box instead of overflowing */
    margin-top:14px;            /* room for the label tab */
  }}
  .box-label {{
    position:absolute; top:-13px; left:10px;
    font-size:{st['box_label_px']}px; font-weight:800; color:#fff;
    padding:1px 8px; border-radius:6px; letter-spacing:.05em;
    font-family:{st['font_family']};
  }}
</style></head>
<body><div id="cap"><div class="sentence">{body}</div></div></body></html>"""


# =============================================================================
# RASTERIZE (Playwright / Chromium)
# =============================================================================

class AnnotationBatchRenderer:
    """Keeps one Chromium instance open to render many annotations efficiently.

    Usage::

        with AnnotationBatchRenderer(horizontal=True, backing=True) as r:
            arr = r.render(annotation)          # -> RGBA numpy array
            r.render_to(annotation, "out.png")  # -> writes a PNG

    Requires Playwright + Chromium (``python -m playwright install chromium``).
    """

    def __init__(self, style: dict | None = None, horizontal: bool = False,
                 backing: bool = False, backing_opacity: float = 0.55, scale: int = 2,
                 font_scale: float = 1.0):
        self.style = style
        self.horizontal = horizontal
        self.backing = backing
        self.backing_opacity = backing_opacity
        self.scale = scale            # device pixel ratio (render DPI)
        self.font_scale = font_scale  # type-size multiplier
        self._pw = self._browser = self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright   # local import: optional dep
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=["--force-color-profile=srgb"])
        self._page = self._browser.new_page(device_scale_factor=self.scale)
        return self

    def _png_bytes(self, annotation: dict) -> bytes:
        html_doc = render_annotation_html(
            annotation, style=self.style, horizontal=self.horizontal,
            backing=self.backing, backing_opacity=self.backing_opacity,
            font_scale=self.font_scale,
        )
        self._page.set_content(html_doc, wait_until="networkidle")
        el = self._page.query_selector("#cap")
        return el.screenshot(omit_background=True)

    def render(self, annotation: dict):
        """Return an RGBA numpy array (device_scale_factor applied)."""
        import io
        import numpy as np
        from PIL import Image
        png = self._png_bytes(annotation)
        return np.array(Image.open(io.BytesIO(png)).convert("RGBA"))

    def render_to(self, annotation: dict, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(self._png_bytes(annotation))
        return out_path

    def __exit__(self, *exc):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


def render_annotation_png(annotation: dict, out_path: str | Path,
                          style: dict | None = None, horizontal: bool = False,
                          scale: int = 2, backing: bool = False,
                          font_scale: float = 1.0) -> Path:
    """Render a single annotation to a transparent PNG. Requires Playwright + Chromium."""
    with AnnotationBatchRenderer(style=style, horizontal=horizontal,
                                 backing=backing, scale=scale, font_scale=font_scale) as r:
        out = r.render_to(annotation, out_path)
    logger.info("Saved %s", out)
    return out


# =============================================================================
# DEMO / TEST DATA
# =============================================================================

def demo_cases() -> dict[str, dict]:
    """Hand-authored annotation test cases covering each feature."""
    return {
        "01_trennbar_nebensatz": {
            "text": "Gestern ist der Fuchs früh aufgestanden, weil er Hunger hatte.",
            "tokens": [
                {"text": "Gestern"},
                {"text": "ist", "role": "verb", "group_id": "v1", "infinitive": "sein", "tense": "Perfekt"},
                {"text": "der", "case": "nominative", "gender": "masculine"},
                {"text": "Fuchs", "role": "subject"},
                {"text": "früh"},
                {"text": "aufgestanden,", "role": "verb", "group_id": "v1", "infinitive": "aufstehen", "tense": "Perfekt"},
                {"text": "weil"},
                {"text": "er"},
                {"text": "Hunger"},
                {"text": "hatte.", "role": "verb", "infinitive": "haben", "tense": "Präteritum"},
            ],
            "spans": [
                {"type": "nebensatz", "token_ids": [6, 7, 8, 9], "verb_final": 9},
            ],
        },
        "02_tekamolo_full": {
            "text": "Ich fahre morgen wegen der Arbeit mit dem Zug nach Berlin.",
            "tokens": [
                {"text": "Ich", "case": "nominative", "gender": "masculine", "role": "subject"},
                {"text": "fahre", "role": "verb", "infinitive": "fahren", "tense": "Präsens"},
                {"text": "morgen"},
                {"text": "wegen"},
                {"text": "der", "case": "genitive", "gender": "feminine"},
                {"text": "Arbeit"},
                {"text": "mit"},
                {"text": "dem", "case": "dative", "gender": "masculine"},
                {"text": "Zug"},
                {"text": "nach"},
                {"text": "Berlin."},
            ],
            "spans": [],
        },
        "03_case_gender": {
            "text": "Ich gebe dem Mann das Buch.",
            "tokens": [
                {"text": "Ich", "case": "nominative", "gender": "masculine", "role": "subject"},
                {"text": "gebe", "role": "verb", "infinitive": "geben", "tense": "Präsens"},
                {"text": "dem", "case": "dative", "gender": "masculine"},
                {"text": "Mann"},
                {"text": "das", "case": "accusative", "gender": "neuter"},
                {"text": "Buch."},
            ],
            "spans": [],
        },
        "04_long_wrap": {
            "text": "Als die Sonne unterging, beschloss der alte Müller, dass er am nächsten "
                    "Morgen in die große Stadt gehen würde, um dort Mehl zu verkaufen.",
            "tokens": [
                {"text": "Als"}, {"text": "die", "case": "nominative", "gender": "feminine"},
                {"text": "Sonne", "role": "subject"}, {"text": "unterging,", "role": "verb", "infinitive": "untergehen", "tense": "Präteritum"},
                {"text": "beschloss", "role": "verb", "infinitive": "beschließen", "tense": "Präteritum"}, {"text": "der", "case": "nominative", "gender": "masculine"},
                {"text": "alte"}, {"text": "Müller,", "role": "subject"},
                {"text": "dass"}, {"text": "er"}, {"text": "am"}, {"text": "nächsten"},
                {"text": "Morgen"}, {"text": "in"}, {"text": "die", "case": "accusative", "gender": "feminine"},
                {"text": "große"}, {"text": "Stadt"}, {"text": "gehen", "role": "verb", "infinitive": "gehen"},
                {"text": "würde,", "role": "verb", "infinitive": "werden", "tense": "Konjunktiv II"}, {"text": "um"}, {"text": "dort"},
                {"text": "Mehl"}, {"text": "zu"}, {"text": "verkaufen.", "role": "verb", "infinitive": "verkaufen"},
            ],
            "spans": [
                {"type": "nebensatz", "token_ids": [0, 1, 2, 3], "verb_final": 3},
                {"type": "nebensatz", "token_ids": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
                 "verb_final": 18},
            ],
        },
        # Long relative clause that must wrap inside the Nebensatz box (regression
        # case for box word-wrap). From a real annotation.
        "05_long_nebensatz_wrap": {
            "text": "Ein Mann hatte einen Esel, der viele Jahre die Säcke zur Mühle getragen hatte.",
            "tokens": [
                {"text": "Ein", "case": "nominative", "gender": "masculine"},
                {"text": "Mann", "role": "subject"},
                {"text": "hatte", "role": "verb", "infinitive": "haben", "tense": "Präteritum"},
                {"text": "einen", "case": "accusative", "gender": "masculine"},
                {"text": "Esel", "role": "object"},
                {"text": ","},
                {"text": "der", "case": "nominative", "gender": "masculine"},
                {"text": "viele"},
                {"text": "Jahre"},
                {"text": "die", "case": "accusative", "gender": "masculine"},
                {"text": "Säcke", "role": "object"},
                {"text": "zur"},
                {"text": "Mühle"},
                {"text": "getragen", "role": "verb", "group_id": "v1",
                 "infinitive": "tragen", "tense": "Plusquamperfekt"},
                {"text": "hatte.", "role": "verb", "group_id": "v1",
                 "infinitive": "haben", "tense": "Plusquamperfekt"},
            ],
            "spans": [
                {"type": "nebensatz",
                 "token_ids": [6, 7, 8, 9, 10, 11, 12, 13, 14], "verb_final": 14},
            ],
        },
    }


def _main() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--install" in sys.argv:
        import subprocess
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return

    out_dir = Path("annotation_test_output")
    out_dir.mkdir(exist_ok=True)
    cases = demo_cases()

    gallery = ['<html><head><meta charset="utf-8"><style>body{background:#2b2f36;'
               'font-family:sans-serif;padding:24px}h2{color:#9aa4b2;font-size:14px;'
               'margin:24px 0 6px}</style></head><body>']
    for name, ann in cases.items():
        for fmt, horiz in (("vertical", False), ("horizontal", True)):
            doc = render_annotation_html(ann, horizontal=horiz, dark_preview=True)
            (out_dir / f"{name}__{fmt}.html").write_text(doc, encoding="utf-8")
            gallery.append(f'<h2>{name} - {fmt}</h2>')
            gallery.append(doc.split("<body>")[1].split("</body>")[0])
    gallery.append("</body></html>")
    (out_dir / "gallery.html").write_text("\n".join(gallery), encoding="utf-8")
    logger.info("Wrote HTML previews to %s", out_dir)

    try:
        for name, ann in cases.items():
            render_annotation_png(ann, out_dir / f"{name}__vertical.png", horizontal=False, backing=True)
            render_annotation_png(ann, out_dir / f"{name}__horizontal.png", horizontal=True, backing=True)
        logger.info("PNG rendering complete.")
    except Exception as e:
        logger.warning("PNG rendering skipped (%s). Run with Chromium installed.", e)


if __name__ == "__main__":
    _main()
