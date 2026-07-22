"""
test_ideogram_renderer.py
=========================
Network-free checks for the Ideogram prompt builder. No fal API call is made.

    python test_ideogram_renderer.py
"""

import sys

from ideogram_annotation_renderer import build_ideogram_prompt
from html_annotation_renderer import demo_cases


def _passed(m): print(f"  PASS  {m}")
def _fail(m):   print(f"  FAIL  {m}"); _fail.count += 1
_fail.count = 0


def test_sentence_in_prompt():
    ann = demo_cases()["02_tekamolo_full"]
    p = build_ideogram_prompt(ann)
    assert ann["text"] in p, "full sentence missing from prompt"
    _passed("full sentence included in prompt")


def test_tekamolo_colors_and_labels():
    p = build_ideogram_prompt(demo_cases()["02_tekamolo_full"])
    for color, label in [("blue", "Temporal"), ("red", "Kausal"),
                         ("green", "Modal"), ("purple", "Lokal")]:
        assert color in p, f"{color} missing"
        assert label in p, f"{label} missing"
    _passed("TEKAMOLO colours + labels present")


def test_phrase_grouping():
    p = build_ideogram_prompt(demo_cases()["02_tekamolo_full"])
    assert '"wegen der Arbeit"' in p, "kausal phrase not grouped from tokens"
    assert '"mit dem Zug"' in p, "modal phrase not grouped from tokens"
    _passed("multi-word phrases reconstructed from token_ids")


def test_trennbar_same_color():
    p = build_ideogram_prompt(demo_cases()["01_trennbar_nebensatz"])
    assert "separable verb" in p and "SAME" in p, "trennbar instruction missing"
    assert '"ist" and "aufgestanden,"' in p, "verb parts not paired"
    _passed("separable verb parts paired with same-colour instruction")


def test_nebensatz_verb_final():
    p = build_ideogram_prompt(demo_cases()["01_trennbar_nebensatz"])
    assert "Nebensatz" in p and "END of the clause" in p, "verb-final instruction missing"
    _passed("Nebensatz + verb-final instruction present")


def test_case_labels():
    p = build_ideogram_prompt(demo_cases()["03_case_gender"])
    assert "Dativ" in p and "Akkusativ" in p and "Nominativ" in p, "case labels missing"
    _passed("case labels present")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} tests\n")
    for t in tests:
        try:
            t()
        except AssertionError as e:
            _fail(f"{t.__name__}: {e}")
        except Exception as e:
            _fail(f"{t.__name__}: unexpected error {e!r}")
    print()
    if _fail.count:
        print(f"{_fail.count} test(s) FAILED"); sys.exit(1)
    print("All tests passed.")
