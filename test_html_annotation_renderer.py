"""
test_html_annotation_renderer.py
================================
Automated checks for the HTML grammar renderer.

Structural/grammar tests need no browser (they assert on the generated HTML).
Aesthetic tests that need pixels run only if Playwright + Chromium are installed;
otherwise they are skipped, so this file is safe to run anywhere:

    python test_html_annotation_renderer.py
"""

import re
import sys
from pathlib import Path

import html_annotation_renderer as r


def _passed(msg): print(f"  PASS  {msg}")
def _fail(msg):   print(f"  FAIL  {msg}"); _fail.count += 1
_fail.count = 0


# --------------------------------------------------------------------------- #
# basic / existing structural tests
# --------------------------------------------------------------------------- #
def test_basic_tokens_render():
    ann = {"tokens": [{"text": "Hallo"}, {"text": "Welt"}], "spans": []}
    html = r.render_annotation_html(ann)
    assert "Hallo" in html and "Welt" in html, "words missing"
    _passed("basic tokens appear in output")


def test_trennbar_same_color():
    """Both halves of a separable verb must share one colour."""
    ann = {"tokens": [{"text": "ist", "group_id": "v1"},
                      {"text": "Mitte"},
                      {"text": "auf", "group_id": "v1"}], "spans": []}
    html = r.render_annotation_html(ann)
    color = r.DEFAULT_STYLE["group_palette"][0]
    assert html.count(f"color:{color}") >= 2, "separable verb halves not coloured the same"
    _passed("trennbares Verb halves share one colour")


def test_tekamolo_not_rendered():
    """The old TEKAMOLO fields must no longer be boxed or labelled."""
    ann = {"tokens": [{"text": "morgen"}, {"text": "hier"}],
           "spans": [{"type": "temporal", "token_ids": [0]},
                     {"type": "lokal", "token_ids": [1]}]}
    html = r.render_annotation_html(ann)
    assert 'class="box"' not in html, "TEKAMOLO spans should not be boxed"
    assert "TEMPORAL" not in html and "LOKAL" not in html, "TEKAMOLO labels should be gone"
    _passed("TEKAMOLO spans are not rendered")


def test_nebensatz_verb_marker():
    ann = {"tokens": [{"text": "weil"}, {"text": "er"}, {"text": "schläft"}],
           "spans": [{"type": "nebensatz", "token_ids": [0, 1, 2], "verb_final": 2}]}
    html = r.render_annotation_html(ann)
    assert "NEBENSATZ" in html and "verbpos" in html, "nebensatz box / verb marker missing"
    _passed("Nebensatz box + verb-position marker render")


def test_nebensatz_without_verb_final_not_boxed():
    """Only clauses that move the verb to the end (verb_final present) are boxed."""
    ann = {"tokens": [{"text": "und"}, {"text": "er"}, {"text": "schläft"}],
           "spans": [{"type": "nebensatz", "token_ids": [0, 1, 2]}]}  # no verb_final
    html = r.render_annotation_html(ann)
    assert 'class="box"' not in html, "a nebensatz without verb_final must not be boxed"
    _passed("Nebensatz without a verb-end contrast is not boxed")


def test_nested_boxes():
    """A Nebensatz fully inside another Nebensatz must nest, not break the HTML."""
    ann = {"tokens": [{"text": "dass"}, {"text": "er"}, {"text": "weiß,"},
                      {"text": "dass"}, {"text": "sie"}, {"text": "kommt"}],
           "spans": [{"type": "nebensatz", "token_ids": [0, 1, 2, 3, 4, 5], "verb_final": 2},
                     {"type": "nebensatz", "token_ids": [3, 4, 5], "verb_final": 5}]}
    html = r.render_annotation_html(ann)
    assert html.count('class="box"') == 2, "expected 2 nested boxes"
    assert html.count("<span") == html.count("</span>"), "unbalanced spans"
    _passed("nested Nebensätze produce valid nesting")


def test_partial_overlap_dropped():
    """Partially overlapping clauses (neither nested) -> inner one dropped, no crash."""
    ann = {"tokens": [{"text": "a"}, {"text": "b"}, {"text": "c"}, {"text": "d"}],
           "spans": [{"type": "nebensatz", "token_ids": [0, 1, 2], "verb_final": 2},
                     {"type": "nebensatz", "token_ids": [1, 2, 3], "verb_final": 3}]}
    html = r.render_annotation_html(ann)
    assert html.count('class="box"') == 1, "overlapping span should have been dropped"
    _passed("partially-overlapping span dropped gracefully")


def test_box_wraps_long_clause():
    """A long Nebensatz must be allowed to wrap inside its box rather than overflow
    the canvas — the box rule needs flex-wrap and a width cap."""
    toks = [{"text": "weil"}] + [{"text": f"w{i}"} for i in range(20)] + [{"text": "hatte."}]
    ann = {"tokens": toks,
           "spans": [{"type": "nebensatz", "token_ids": list(range(len(toks))),
                      "verb_final": len(toks) - 1}]}
    html = r.render_annotation_html(ann)
    m = re.search(r"\.box \{(.*?)\}", html, re.S)
    assert m, "no .box rule found"
    rule = m.group(1)
    assert "flex-wrap:wrap" in rule, "box must allow wrapping"
    assert "max-width:100%" in rule, "box must be width-capped so it can wrap"
    assert 'class="box"' in html, "long clause should still produce a box"
    _passed("long Nebensatz box is set up to wrap (flex-wrap + max-width)")


def test_real_long_nebensatz_demo_case():
    """The real 'Esel' sentence: one long relative clause that must box and wrap,
    not overflow. Regression case from a production annotation."""
    ann = r.demo_cases()["05_long_nebensatz_wrap"]
    html = r.render_annotation_html(ann)
    assert html.count('class="box"') == 1, "expected exactly one Nebensatz box"
    assert "NEBENSATZ" in html, "Nebensatz label missing"
    # the box must be allowed to wrap its long contents
    rule = re.search(r"\.box \{(.*?)\}", html, re.S).group(1)
    assert "flex-wrap:wrap" in rule and "max-width:100%" in rule, "box not wrappable"
    # spans + tokens stay well-formed
    assert html.count("<span") == html.count("</span>"), "unbalanced spans"
    _passed("real long-Nebensatz case boxes once and is set up to wrap")


def test_generator_spans_only_nebensatz_with_verb_final():
    """generate_annotations keeps only nebensatz spans that carry a verb_final."""
    try:
        import generate_annotations as g
    except Exception as e:
        print(f"  SKIP  generator import ({e})"); return
    spans = g._clean_spans([
        {"type": "temporal", "token_ids": [0]},                         # TEKAMOLO -> drop
        {"type": "nebensatz", "token_ids": [1, 2, 3]},                  # no verb_final -> drop
        {"type": "nebensatz", "token_ids": [1, 2, 3], "verb_final": 3},  # keep
    ], n_tokens=4)
    assert len(spans) == 1, f"expected 1 span, got {spans}"
    assert spans[0]["type"] == "nebensatz" and spans[0]["verb_final"] == 3
    _passed("generator keeps only nebensatz spans with a verb_final")


def test_html_escaping():
    ann = {"tokens": [{"text": "Fish & <Chips>"}], "spans": []}
    html = r.render_annotation_html(ann)
    assert "&amp;" in html and "&lt;" in html, "special chars not escaped"
    _passed("special characters are HTML-escaped")


# --------------------------------------------------------------------------- #
# infinitive feature — grammar correctness
# --------------------------------------------------------------------------- #
def test_infinitive_shown_when_different():
    ann = {"tokens": [{"text": "er"},
                      {"text": "aufgestanden,", "role": "verb", "infinitive": "aufstehen"}],
           "spans": []}
    html = r.render_annotation_html(ann)
    assert 'class="infinitive"' in html and "aufstehen" in html, "infinitive not rendered"
    _passed("infinitive base form rendered for a Partizip")


def test_infinitive_hidden_when_same():
    ann = {"tokens": [{"text": "gehen", "role": "verb", "infinitive": "gehen"}], "spans": []}
    html = r.render_annotation_html(ann)
    assert 'class="infinitive"' not in html, "redundant infinitive should be hidden"
    _passed("identical infinitive is not rendered (no clutter)")


def test_infinitive_hidden_ignoring_punctuation():
    """'verkaufen.' (with period) vs infinitive 'verkaufen' -> identical, so hide."""
    ann = {"tokens": [{"text": "verkaufen.", "role": "verb", "infinitive": "verkaufen"}], "spans": []}
    html = r.render_annotation_html(ann)
    assert 'class="infinitive"' not in html, "punctuation-only diff should still hide"
    _passed("trailing punctuation does not trigger a redundant infinitive")


def test_conjugation_on_top_infinitive_below():
    """The conjugated word must come BEFORE the infinitive in DOM order so it
    renders on top (column layout) and the base form sits beneath it."""
    ann = {"tokens": [{"text": "ging", "role": "verb", "infinitive": "gehen"}], "spans": []}
    html = r.render_annotation_html(ann)
    assert html.index(">ging<") < html.index('class="infinitive"'), \
        "infinitive should come after (below) the conjugated word"
    _passed("conjugation renders on top, infinitive below")


def test_separable_verb_both_halves_carry_infinitive():
    ann = {"tokens": [{"text": "steht", "role": "verb", "group_id": "v1", "infinitive": "aufstehen"},
                      {"text": "früh"},
                      {"text": "auf.", "role": "verb", "group_id": "v1", "infinitive": "aufstehen"}],
           "spans": []}
    html = r.render_annotation_html(ann)
    assert html.count("aufstehen") == 2, "both separable-verb halves should show the infinitive"
    _passed("split separable verb shows infinitive on both halves")


def test_generator_keeps_infinitive_only_on_verbs():
    """generate_annotations must keep 'infinitive' only on tokens it marks as verbs."""
    try:
        import generate_annotations as g
    except Exception as e:
        print(f"  SKIP  generator import ({e})"); return
    cleaned = g._clean_tokens([
        {"text": "Haus", "infinitive": "hausen"},                 # not a verb -> drop
        {"text": "ging", "role": "verb", "infinitive": "gehen"},  # verb -> keep
    ])
    assert "infinitive" not in cleaned[0], "infinitive leaked onto a non-verb"
    assert cleaned[1].get("infinitive") == "gehen", "verb infinitive dropped"
    _passed("generator keeps infinitive only on verbs")


def test_demo_cases_grammar_is_correct():
    """Spot-check that demo annotations carry linguistically correct infinitives."""
    expected = {
        "ist": "sein", "aufgestanden,": "aufstehen", "hatte.": "haben",
        "fahre": "fahren", "gebe": "geben",
        "unterging,": "untergehen", "beschloss": "beschließen", "würde,": "werden",
    }
    seen = {}
    for case in r.demo_cases().values():
        for tok in case["tokens"]:
            if tok.get("role") == "verb" and tok.get("infinitive"):
                seen[tok["text"]] = tok["infinitive"]
    for word, inf in expected.items():
        assert seen.get(word) == inf, \
            f"{word!r} should map to infinitive {inf!r}, got {seen.get(word)!r}"
    _passed("demo-case verb infinitives are grammatically correct")


# --------------------------------------------------------------------------- #
# tense feature — grammar correctness
# --------------------------------------------------------------------------- #
def test_tense_label_above_verb():
    ann = {"tokens": [{"text": "ging", "role": "verb", "infinitive": "gehen", "tense": "praeteritum"}],
           "spans": []}
    html = r.render_annotation_html(ann)
    assert "Präteritum" in html, "tense label missing / not normalised"
    assert html.index("Präteritum") < html.index(">ging<"), "tense should be above (before) the word"
    _passed("tense label normalised and rendered above the verb")


def test_tense_only_on_verbs():
    try:
        import generate_annotations as g
    except Exception as e:
        print(f"  SKIP  generator import ({e})"); return
    cleaned = g._clean_tokens([
        {"text": "Morgen", "tense": "Praesens"},                  # not a verb -> drop
        {"text": "ging", "role": "verb", "tense": "Praeteritum"},  # verb -> keep
    ])
    assert "tense" not in cleaned[0], "tense leaked onto a non-verb"
    assert cleaned[1].get("tense") == "Praeteritum", "verb tense dropped"
    _passed("generator keeps tense only on verbs")


# --------------------------------------------------------------------------- #
# aesthetics — vertical alignment (the word stays on one centred line)
# --------------------------------------------------------------------------- #
def test_reserved_slots_keep_word_on_one_line():
    """The above/below reserves are equal (word centred) and identical across every
    word, so a word with a tense label / infinitive does not sit higher or lower
    than its plain neighbours."""
    ann = {"tokens": [{"text": "Heute"},
                      {"text": "ging", "role": "verb", "infinitive": "gehen", "tense": "Präteritum"},
                      {"text": "er"}],
           "spans": []}
    html = r.render_annotation_html(ann)
    aboves = re.findall(r"\.above\s*\{\s*min-height:(\d+)px", html)
    belows = re.findall(r"\.below\s*\{\s*min-height:(\d+)px", html)
    assert aboves and belows and aboves[0] == belows[0], "above/below reserves must be equal"
    assert int(aboves[0]) > 0, "a sentence with labels must reserve slot height"
    assert html.count('class="above"') == 3 and html.count('class="below"') == 3, \
        "every word must reserve an above and below slot"
    _passed(f"equal reserved slots ({aboves[0]}px) keep words on one centred line")


# --------------------------------------------------------------------------- #
# aesthetics — layout sanity (no browser needed)
# --------------------------------------------------------------------------- #
def test_spans_are_balanced():
    """Every <span> must be closed — malformed HTML would look broken when rendered."""
    for name, case in r.demo_cases().items():
        html = r.render_annotation_html(case)
        opens = len(re.findall(r"<span\b", html))
        closes = html.count("</span>")
        assert opens == closes, f"{name}: unbalanced spans ({opens} open vs {closes} close)"
    _passed("rendered HTML has balanced <span> tags (well-formed)")


def test_font_scale_scales_everything():
    """The font_scale knob scales the word AND its labels together, but leaves the
    wrap width fixed so text still wraps to the target canvas."""
    ann = {"tokens": [{"text": "ging", "role": "verb", "infinitive": "gehen", "tense": "Praeteritum"}],
           "spans": []}
    base = r.render_annotation_html(ann)
    big = r.render_annotation_html(ann, font_scale=1.5)

    def size_of(cls, html):
        return int(re.search(rf"\.{cls} \{{[^}}]*?font-size:(\d+)px", html).group(1))

    assert size_of("word", big) == round(size_of("word", base) * 1.5), "word not scaled"
    assert size_of("infinitive", big) == round(size_of("infinitive", base) * 1.5), \
        "infinitive label not scaled"
    assert f"max-width:{r.DEFAULT_STYLE['max_width_px']}px" in big, "wrap width must stay fixed"
    _passed("font_scale scales word + labels together, leaves wrap width fixed")


def test_font_scale_composes_with_style():
    """font_scale multiplies whatever size won resolution (default/horizontal/style)."""
    ann = {"tokens": [{"text": "x"}], "spans": []}
    html = r.render_annotation_html(ann, style={"word_size_px": 40}, font_scale=2.0)
    word = int(re.search(r"\.word \{[^}]*?font-size:(\d+)px", html).group(1))
    assert word == 80, f"expected style(40) * scale(2) = 80, got {word}"
    _passed("font_scale composes on top of style overrides")


def test_infinitive_not_larger_than_word():
    """Aesthetic rule: the base form is a secondary label, never bigger than the word."""
    st = r.DEFAULT_STYLE
    assert st["infinitive_px"] <= st["word_size_px"], "infinitive font must not exceed the word"
    assert st["infinitive_px"] >= st["note_size_px"] - 4, "infinitive should stay legible"
    _passed("infinitive font size is subordinate to the word but legible")


def test_infinitive_has_breathing_room():
    """There must be a gap between the word and the infinitive so they don't collide."""
    ann = {"tokens": [{"text": "ging", "role": "verb", "infinitive": "gehen"}], "spans": []}
    html = r.render_annotation_html(ann)
    after = html.split(".infinitive")[1][:120]
    assert "margin-top" in after, "infinitive needs top margin for spacing"
    _passed("infinitive has vertical breathing room (margin-top)")


# --------------------------------------------------------------------------- #
# aesthetics — pixel checks (need Playwright + Chromium)
# --------------------------------------------------------------------------- #
def test_infinitive_adds_a_visible_row():
    """With an infinitive the column is taller than without — proves it is actually
    drawn and laid out, and acts as a regression guard on the look."""
    try:
        import playwright  # noqa
    except ImportError:
        print("  SKIP  pixel test (playwright not installed)"); return
    base = {"tokens": [{"text": "ging", "role": "verb"}], "spans": []}
    withinf = {"tokens": [{"text": "ging", "role": "verb", "infinitive": "gehen"}], "spans": []}
    with r.AnnotationBatchRenderer() as br:
        h0 = br.render(base).shape[0]
        h1 = br.render(withinf).shape[0]
    assert h1 > h0, f"infinitive row added no height ({h0} -> {h1})"
    _passed(f"infinitive adds a visible row (height {h0}px -> {h1}px)")


def test_png_if_available():
    try:
        import playwright  # noqa
    except ImportError:
        print("  SKIP  PNG render (playwright not installed)"); return
    out = Path("annotation_test_output/_test.png")
    r.render_annotation_png(r.demo_cases()["01_trennbar_nebensatz"], out)
    assert out.exists() and out.stat().st_size > 0, "PNG not written"
    _passed(f"PNG rendered -> {out}")


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
        print(f"{_fail.count} test(s) FAILED")
        sys.exit(1)
    print("All tests passed.")
