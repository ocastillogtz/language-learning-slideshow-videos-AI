"""
render_comparison.py
====================
A/B harness: runs BOTH grammar-annotation renderers on the same shared demo
sentences and builds a side-by-side HTML gallery so you can compare them.

  python render_comparison.py                 # HTML PNG + Ideogram, both
  python render_comparison.py --no-ideogram   # HTML renderer only (no API calls)
  python render_comparison.py --orientation horizontal

Outputs land in annotation_test_output/ ; open comparison.html in a browser.

Requirements
------------
  HTML side:     playwright + chromium  (python -m playwright install chromium)
  Ideogram side: fal-client + FAL_KEY in .env
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from html_annotation_renderer import demo_cases, render_annotation_png
from ideogram_annotation_renderer import render_annotation_ideogram, build_ideogram_prompt

logger = logging.getLogger(__name__)

CARD = """
<div class="case">
  <h2>{name}</h2>
  <div class="sentence">{sentence}</div>
  <div class="cols">
    <figure><figcaption>HTML / CSS renderer</figcaption>{html_img}</figure>
    <figure><figcaption>Ideogram v4</figcaption>{ideo_img}</figure>
  </div>
  <details><summary>Ideogram prompt</summary><pre>{prompt}</pre></details>
</div>
"""

PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Renderer comparison</title>
<style>
 body{{background:#1f2329;color:#e6e9ee;font-family:sans-serif;margin:0;padding:28px}}
 h1{{font-weight:600}} h2{{color:#9aa4b2;font-size:15px;margin:0 0 4px}}
 .case{{margin:0 0 40px;border-bottom:1px solid #333;padding-bottom:24px}}
 .sentence{{color:#cbd3df;margin:0 0 12px;font-size:14px}}
 .cols{{display:flex;gap:18px;flex-wrap:wrap}}
 figure{{margin:0;background:#2b2f36;border-radius:12px;padding:10px;flex:1;min-width:340px}}
 figcaption{{font-size:12px;color:#9aa4b2;margin-bottom:8px}}
 img{{max-width:100%;border-radius:8px;display:block}}
 .missing{{color:#7c828c;font-size:13px;padding:40px;text-align:center}}
 details{{margin-top:10px}} summary{{cursor:pointer;color:#9aa4b2;font-size:13px}}
 pre{{white-space:pre-wrap;background:#15181d;padding:12px;border-radius:8px;font-size:12px;color:#bcd}}
</style></head><body><h1>Grammar annotation — renderer comparison</h1>{cards}</body></html>"""


def _img_tag(path: Path) -> str:
    return f'<img src="{path.name}" alt="">' if path.exists() else \
           '<div class="missing">not generated</div>'


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ideogram", action="store_true", help="skip fal Ideogram calls")
    ap.add_argument("--no-html", action="store_true", help="skip HTML/Chromium render")
    ap.add_argument("--orientation", choices=["vertical", "horizontal"], default="horizontal")
    args = ap.parse_args()

    horiz = args.orientation == "horizontal"
    out = Path("annotation_test_output")
    out.mkdir(exist_ok=True)
    cases = demo_cases()
    cards = []

    for name, ann in cases.items():
        html_png = out / f"{name}__html_{args.orientation}.png"
        ideo_jpg = out / f"{name}__ideogram_{args.orientation}.jpg"

        if not args.no_html:
            try:
                render_annotation_png(ann, html_png, horizontal=horiz)
            except Exception as e:
                logger.error("HTML render failed for %s: %s", name, e)

        if not args.no_ideogram:
            try:
                render_annotation_ideogram(ann, ideo_jpg, horizontal=horiz)
            except Exception as e:
                logger.error("Ideogram render failed for %s: %s", name, e)

        cards.append(CARD.format(
            name=name,
            sentence=ann.get("text", ""),
            html_img=_img_tag(html_png),
            ideo_img=_img_tag(ideo_jpg),
            prompt=build_ideogram_prompt(ann),
        ))

    (out / "comparison.html").write_text(PAGE.format(cards="\n".join(cards)), encoding="utf-8")
    logger.info("Wrote %s", out / "comparison.html")


if __name__ == "__main__":
    main()
