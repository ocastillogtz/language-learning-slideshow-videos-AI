"""
ideogram_annotation_renderer.py
===============================
The "Ideogram" branch of the two grammar-annotation renderers.  It consumes the
SAME annotation schema as html_annotation_renderer (see ANNOTATION_SCHEMA.md),
turns it into a descriptive prompt, and generates an educational grammar
infographic via fal.ai's `fal-ai/ideogram-v4` model.

Why two renderers?  The HTML/CSS renderer is pixel-precise and cheap; Ideogram
is stylistic and can draw little icons, but its text is less reliable.  Both run
on identical input so you can compare results sentence-by-sentence
(see render_comparison.py).

Colours are kept consistent with the HTML renderer palette so the two outputs
are visually comparable:
  Temporal=blue · Kausal=red · Modal=green · Lokal=purple · Nebensatz=teal ·
  separable-verb group=orange.

Requirements
------------
  pip install fal-client python-dotenv
  FAL_KEY set in .env  (https://fal.ai -> Dashboard -> API Keys)

CLI
---
  python ideogram_annotation_renderer.py            # render all demo cases
  python ideogram_annotation_renderer.py --print    # just print the prompts (no API call)
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# fal model + default generation parameters (from the user's working example)
IDEOGRAM_MODEL = "fal-ai/ideogram-v4"

DEFAULT_PARAMS: dict[str, Any] = {
    "enable_prompt_expansion": False,   # keep exact German text; set True for richer scenes
    "rendering_speed": "BALANCED",
    "num_images": 1,
    "sync_mode": False,
    "enable_safety_checker": True,
    "output_format": "jpeg",
    "acceleration": "none",
}

# image_size per format (Ideogram v4 takes explicit width/height)
IMAGE_SIZE = {
    "horizontal": {"width": 1536, "height": 896},
    "vertical":   {"width": 896,  "height": 1536},
}

# span type -> (colour word for the prompt, German label, "question" hint)
SPAN_PROMPT = {
    "temporal":  ("blue",   "Temporal",  "wann?"),
    "kausal":    ("red",    "Kausal",    "warum?"),
    "modal":     ("green",  "Modal",     "wie?"),
    "lokal":     ("purple", "Lokal",     "wo?"),
    "nebensatz": ("teal",   "Nebensatz", "subordinate clause"),
}

# separable-verb group colours (names, cycled per distinct group)
GROUP_COLOR_WORDS = ["orange", "pink", "violet", "cyan", "lime"]

CASE_LABEL = {
    "nominative": "Nominativ", "nom": "Nominativ",
    "accusative": "Akkusativ", "acc": "Akkusativ",
    "dative": "Dativ", "dat": "Dativ",
    "genitive": "Genitiv", "gen": "Genitiv",
}
GENDER_LABEL = {"masculine": "m", "feminine": "f", "neuter": "n",
                "masc": "m", "fem": "f", "neu": "n"}


# =============================================================================
# PROMPT BUILDER  (pure, network-free, unit-tested)
# =============================================================================

def _phrase(tokens: list[dict], token_ids: list[int]) -> str:
    by_i = {t.get("i", idx): t for idx, t in enumerate(tokens)}
    words = [by_i[i]["text"] for i in sorted(token_ids) if i in by_i]
    return " ".join(words).strip()


def _sentence_text(annotation: dict) -> str:
    if annotation.get("text"):
        return annotation["text"].strip()
    return " ".join(t["text"] for t in annotation.get("tokens", [])).strip()


def build_ideogram_prompt(annotation: dict) -> str:
    """Translate the annotation schema into an Ideogram instruction string."""
    tokens = annotation.get("tokens", [])
    for idx, t in enumerate(tokens):
        t.setdefault("i", idx)
    sentence = _sentence_text(annotation)

    lines: list[str] = [
        "Educational German grammar infographic for B1 learners.",
        "Clean, simple, flat infographic style, bright colors on a white background,",
        "generous whitespace, not crowded, highly readable, accurate German spelling,",
        "clean sans-serif text, no watermark, no extra words.",
        "",
        "Show the full German sentence in large clear text at the top:",
        f'"{sentence}"',
        "",
    ]

    # --- TEKAMOLO + Nebensatz boxes ---
    box_lines: list[str] = []
    for sp in annotation.get("spans", []):
        typ = sp.get("type")
        if typ not in SPAN_PROMPT:
            continue
        ids = sp.get("token_ids")
        if not ids and "start" in sp and "end" in sp:
            ids = list(range(sp["start"], sp["end"] + 1))
        phrase = _phrase(tokens, ids or [])
        color, label, hint = SPAN_PROMPT[typ]
        if typ == "nebensatz":
            line = (f'- {color} dashed box around the subordinate clause "{phrase}" '
                    f'labeled "{label}"')
            vf = sp.get("verb_final")
            if vf is not None:
                by_i = {t["i"]: t for t in tokens}
                verb = by_i.get(vf, {}).get("text", "")
                if verb:
                    line += (f'; draw a small arrow showing the conjugated verb '
                             f'"{verb}" moves to the END of the clause')
            box_lines.append(line)
        else:
            box_lines.append(
                f'- {color} box around "{phrase}" labeled "{label} ({hint})"')
    if box_lines:
        lines.append("Below the sentence, highlight these grammatical parts as labeled colored boxes:")
        lines.extend(box_lines)
        lines.append("")

    # --- separable verbs (group_id) ---
    groups: dict[str, list[str]] = {}
    for t in tokens:
        gid = t.get("group_id")
        if gid:
            groups.setdefault(gid, []).append(t["text"])
    for n, (gid, parts) in enumerate(groups.items()):
        if len(parts) >= 2:
            cw = GROUP_COLOR_WORDS[n % len(GROUP_COLOR_WORDS)]
            joined = '" and "'.join(parts)
            lines.append(
                f'Show the two parts of the separable verb "{joined}" in the SAME '
                f'{cw} color, connected by a thin {cw} arrow (trennbares Verb).')

    # --- case / gender labels ---
    case_bits: list[str] = []
    for t in tokens:
        if t.get("case"):
            lbl = CASE_LABEL.get(t["case"], t["case"])
            g = GENDER_LABEL.get(t.get("gender", ""), "")
            case_bits.append(f'"{t["text"]}" = {lbl}{f" ({g})" if g else ""}')
    if case_bits:
        lines.append("")
        lines.append("Add small grammar labels above these words: " + "; ".join(case_bits) + ".")

    lines.append("")
    lines.append("Keep it simple, readable and uncluttered. Educational diagram style.")
    return "\n".join(lines)


# =============================================================================
# RENDER (fal.ai)
# =============================================================================

def _on_queue_update(update) -> None:
    import fal_client
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            logger.info("  [fal] %s", log["message"])


def render_annotation_ideogram(
    annotation: dict,
    out_path: str | Path,
    horizontal: bool = False,
    params: dict | None = None,
    prompt_override: str | None = None,
) -> Path:
    """Generate the grammar infographic via fal Ideogram v4 and save it."""
    import fal_client
    from dotenv import load_dotenv
    load_dotenv()

    prompt = prompt_override or build_ideogram_prompt(annotation)
    size = IMAGE_SIZE["horizontal" if horizontal else "vertical"]

    args = {"prompt": prompt, "image_size": size, **DEFAULT_PARAMS}
    if params:
        args.update(params)

    logger.info("Ideogram render (%s) -> %s", "horizontal" if horizontal else "vertical", out_path)
    result = fal_client.subscribe(
        IDEOGRAM_MODEL, arguments=args, with_logs=True, on_queue_update=_on_queue_update,
    )

    url = result["images"][0]["url"]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        out_path.write_bytes(resp.read())
    logger.info("  Saved %s", out_path)
    return out_path


# =============================================================================
# CLI
# =============================================================================

def _main() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from html_annotation_renderer import demo_cases   # reuse identical test data

    cases = demo_cases()

    if "--print" in sys.argv:
        for name, ann in cases.items():
            print("=" * 70, "\n", name, "\n", "=" * 70, sep="")
            print(build_ideogram_prompt(ann), "\n")
        return

    out_dir = Path("annotation_test_output")
    out_dir.mkdir(exist_ok=True)
    for name, ann in cases.items():
        try:
            render_annotation_ideogram(ann, out_dir / f"{name}__ideogram_h.jpg", horizontal=True)
        except Exception as e:
            logger.error("Failed %s: %s", name, e)


if __name__ == "__main__":
    _main()
