"""
utils_markup.py
===============
WhatsApp-style inline markup for dialog text: detection plus plain-text
helpers for TTS and quizzes (rendering lives in subtitle_render.py).

Supported markers
-----------------
  _text_   -> highlight colour, cycled    (use for learning features)
  *text*   -> highlight colour            (use for strong emphasis)
  -text-   -> silent: visible in subtitles, EXCLUDED from TTS audio

The -text- marker is intended for on-screen labels (e.g. speaker names,
section headings) that should appear in the subtitle but not be spoken by
the TTS voice.  Example:
    "-Sani:- Guten Morgen!"
  Subtitle shows : "Sani: Guten Morgen!"
  TTS receives   : "Guten Morgen!"

Multiple _italic_ spans cycle through a list of colours defined in config.ini
under [subtitles] -> markup_italic_colors (comma-separated hex values);
*bold* spans use [subtitles] -> markup_bold_color.
The first span gets the first colour, the second span the second, and so on.
If there are more spans than colours the list wraps around.

These markers are written by GPT into the dialog "text" field.
subtitle_render.py draws them in the single dialog-subtitle style (highlight
spans only change the colour of their words).
"""

import re

_BOLD_RE   = re.compile(r'\*([^*\n]+)\*')
_ITALIC_RE = re.compile(r'_([^_\n]+)_')
# A silent span must not touch letters/digits on the outside, so a hyphenated
# word ("Ja-Nein-Fragen", "U-Bahn-Station") is NOT mistaken for "-Nein-" and
# dropped from the audio; "-Sani:- Guten Morgen!" still matches.
_SILENT_RE = re.compile(r'(?<!\w)-([^-\n]+)-(?!\w)')

# All three markers in one alternation (bold first, so *____* stays one span).
SPAN_RE = re.compile(r'(\*[^*\n]+\*|_[^_\n]+_|(?<!\w)-[^-\n]+-(?!\w))')


def has_markup(text: str) -> bool:
    """Return True if text contains any _italic_, *bold*, or -silent- markers."""
    return bool(_BOLD_RE.search(text) or _ITALIC_RE.search(text) or _SILENT_RE.search(text))


# =============================================================================
# SILENT MARKER HELPERS
# =============================================================================

def strip_silent_for_tts(text: str) -> str:
    """
    Remove -silent- spans entirely, including their content.
    Use this before sending text to ElevenLabs so silent spans are not spoken.

    Example:
        "-Sani:- Guten Morgen!"  ->  "Guten Morgen!"
    """
    return _SILENT_RE.sub('', text).strip()


def strip_silent_markers(text: str) -> str:
    """
    Remove -markers- but keep the content inside them.
    Use this for subtitle display so the text is visible but the dashes are gone.

    Example:
        "-Sani:- Guten Morgen!"  ->  "Sani: Guten Morgen!"
    """
    return _SILENT_RE.sub(r'\1', text)


# =============================================================================
# PLAIN-TEXT FALLBACKS
# =============================================================================

def strip_markup(text: str) -> str:
    """
    Remove all markup markers, returning plain text suitable for display.

    -silent- markers: content is KEPT (the text remains visible in subtitles).
    *bold* and _italic_ markers: content is kept, markers stripped.

    For TTS audio, use strip_for_tts() instead.
    """
    text = _SILENT_RE.sub(r'\1', text)   # keep content, strip dashes
    text = _BOLD_RE.sub(r'\1', text)
    text = _ITALIC_RE.sub(r'\1', text)
    return text


def strip_for_tts(text: str) -> str:
    """
    Prepare text for TTS (ElevenLabs):
      1. Remove -silent- spans entirely (content excluded from speech).
      2. Strip *bold* and _italic_ markers (content kept — spoken normally).

    Example:
        "-Sani:- *Guten* _Morgen_!"  ->  "Guten Morgen!"
    """
    text = strip_silent_for_tts(text)   # remove silent spans + content
    text = _BOLD_RE.sub(r'\1', text)    # keep bold content
    text = _ITALIC_RE.sub(r'\1', text)  # keep italic content
    return text


# =============================================================================
# FILL-IN-THE-BLANK HELPERS  (blank_quiz / preposition_quiz)
# =============================================================================

def blank_the_answer(sentence_full: str, blank: str = "____") -> str:
    """
    Turn a completed quiz sentence into its "gap" form for the subtitle by replacing
    the *bold* answer span with a blank, KEEPING it bold so the gap sits in the same
    highlighted slot the answer will later fill on the reveal.

    The blank stays wrapped in *asterisks*; underscores inside a *bold* span are safe
    (subtitle_render matches the bold span first and never re-parses its contents as italic).

        "Ich habe Angst *vor* großen Spinnen."  ->  "Ich habe Angst *____* großen Spinnen."

    If no *bold* span is present (malformed input) the sentence is returned unchanged
    so the caller can fall back to another source (e.g. sentence_partial).
    """
    if _BOLD_RE.search(sentence_full):
        return _BOLD_RE.sub(lambda _m: f"*{blank}*", sentence_full, count=1)
    return sentence_full


def gap_reading_for_tts(sentence_full: str, gap: str = "…") -> str:
    """
    Spoken form of a quiz sentence for the PARTIAL scene: the *bold* answer is replaced
    by a short pause (an ellipsis, which TTS renders as a natural gap) and all remaining
    markup is stripped.

        "Ich habe Angst *vor* großen Spinnen."  ->  "Ich habe Angst … großen Spinnen."

    If no *bold* span is present, the whole sentence is returned (markup stripped).
    """
    if _BOLD_RE.search(sentence_full):
        text = _BOLD_RE.sub(gap, sentence_full, count=1)
    else:
        text = sentence_full
    return strip_for_tts(text)
