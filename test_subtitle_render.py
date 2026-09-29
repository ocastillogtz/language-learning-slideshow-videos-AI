"""Tests for the single dialog-subtitle style (subtitle_render) and the markup rules.

Needs Pillow and an installed Calibri Bold (resolved through ImageMagick or
C:/Windows/Fonts); no network, no FFmpeg.
"""
import subtitle_render as sr
from utils_markup import strip_for_tts, strip_markup, has_markup

BASE, BOLD = (255, 235, 205), (255, 215, 0)
ITALIC = [(1, 1, 1), (2, 2, 2)]


# --- silent marker vs hyphenated words -------------------------------------------

def test_silent_label_is_not_spoken():
    assert strip_for_tts("-Sani:- Guten Morgen!") == "Guten Morgen!"


def test_hyphenated_words_are_kept():
    # Regression: "Ja-Nein-Fragen" was read as a silent "-Nein-" span and the TTS
    # said "JaFragen"; "U-Bahn-Station" had the same problem.
    for text in ("*Ob* benutzt man für indirekte Ja-Nein-Fragen.",
                 "Ich warte an der U-Bahn-Station.",
                 "Das Hin-und-her-Fahren nervt."):
        plain = strip_markup(text)
        assert strip_for_tts(text) == plain, text
        assert "-" in plain, text


def test_has_markup_ignores_plain_hyphens():
    assert not has_markup("Ich warte an der U-Bahn-Station.")
    assert has_markup("_weil_ ich müde bin")


# --- span colouring ---------------------------------------------------------------

def test_spans_colour_only_the_highlights():
    spans = sr._spans("Ich komme, _weil_ er _hat_. *Ja!* -Sani:- ok", BASE, BOLD, ITALIC)
    assert ("weil", ITALIC[0]) in spans and ("hat", ITALIC[1]) in spans
    assert ("Ja!", BOLD) in spans and ("Sani:", BASE) in spans
    assert "".join(t for t, _ in spans) == "Ich komme, weil er hat. Ja! Sani: ok"


def test_quiz_blank_stays_one_bold_span():
    spans = sr._spans("Ich habe Angst *____* großen Spinnen.", BASE, BOLD, ITALIC)
    assert ("____", BOLD) in spans


def test_hyphenated_word_is_plain_text():
    spans = sr._spans("indirekte Ja-Nein-Fragen", BASE, BOLD, ITALIC)
    assert spans == [("indirekte Ja-Nein-Fragen", BASE)]


def test_punctuation_after_highlight_stays_on_the_word():
    words = sr._words(sr._spans("geklingelt _hat_.", BASE, BOLD, ITALIC))
    assert words[-1] == [("hat", ITALIC[0]), (".", BASE)]


# --- rendering --------------------------------------------------------------------

def _render(text, width=1000):
    return sr.render_subtitle(text, width, font="Calibri-Bold", fontsize=60,
                              color="BlanchedAlmond", stroke_color="sienna4",
                              stroke_width=4, italic_colors=["#FFD700"],
                              bold_color="#FFD700")


def test_render_keeps_full_width_and_wraps():
    one = _render("Kurz.")
    two = _render("Ein ziemlich langer Satz, der ganz sicher auf zwei Zeilen umbrechen muss.")
    assert one.shape[1] == 1000 and two.shape[1] == 1000 and one.shape[2] == 4
    assert two.shape[0] > one.shape[0]


def test_plain_and_markup_lines_share_the_style():
    # Same words, one with a highlight: same size, same outline pixels.
    a, b = _render("Ich komme zu spät"), _render("Ich komme zu _spät_")
    assert a.shape == b.shape
    stroke = (139, 71, 38)
    count = lambda im: int(((im[..., :3] == stroke).all(-1) & (im[..., 3] > 0)).sum())
    assert count(a) > 0 and abs(count(a) - count(b)) < 0.05 * count(a)


def test_imagemagick_colour_names_resolve():
    assert sr.resolve_color("sienna4") == (139, 71, 38)
    assert sr.resolve_color("BlanchedAlmond") == (255, 235, 205)
