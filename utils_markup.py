"""
utils_markup.py
===============
Converts WhatsApp-style inline markup to Pango markup for TextClip rendering,
and provides plain-text helpers for TTS and subtitle fallback.

Supported markers
-----------------
  _text_   -> italic + highlight colour  (use for learning features)
  *text*   -> bold                       (use for strong emphasis)
  -text-   -> silent: visible in subtitles, EXCLUDED from TTS audio

The -text- marker is intended for on-screen labels (e.g. speaker names,
section headings) that should appear in the subtitle but not be spoken by
the TTS voice.  Example:
    "-Sani:- Guten Morgen!"
  Subtitle shows : "Sani: Guten Morgen!"
  TTS receives   : "Guten Morgen!"

Multiple _italic_ spans cycle through a list of colours defined in config.ini
under [subtitles] -> markup_italic_colors (comma-separated hex values).
The first span gets the first colour, the second span the second, and so on.
If there are more spans than colours the list wraps around.

These markers are written by GPT into the dialog "text" field.
create_video.py calls to_pango() when rendering subtitles, with a safe
fallback to strip_markup() if the Pango TextClip call fails.
"""

import re

_BOLD_RE   = re.compile(r'\*([^*\n]+)\*')
_ITALIC_RE = re.compile(r'_([^_\n]+)_')
_SILENT_RE = re.compile(r'-([^-\n]+)-')


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
# PANGO RENDERING
# =============================================================================

def to_pango(text: str, italic_attrs: str, bold_attrs: str,
             italic_colors: list = None) -> str:
    """
    Convert _text_, *text*, and -text- markers to Pango <span> tags.

    -silent- spans: the content is shown as plain (unstyled) text; the dashes
    are stripped.  The content will appear in the subtitle but was not spoken.

    Each successive _italic_ span cycles through italic_colors.  If a colour
    is available it is appended as foreground="COLOR" to italic_attrs.
    If italic_colors is empty or None, italic_attrs is used as-is for every span.

    Properly escapes XML special characters (&, <, >) in the plain portions
    before inserting tags, so the result is always valid Pango markup.

    Parameters
    ----------
    text          : Raw text with _..._, *...*, and -...- markers.
    italic_attrs  : Pango span attribute string for italic/learning markup.
                    Example: 'font_style="italic"'
    bold_attrs    : Pango span attribute string for bold markup.
                    Example: 'weight="bold"'
    italic_colors : List of hex colour strings cycled across italic spans.
                    Example: ['#FFD700', '#DBB900', '#FFDD24', '#B89B00', '#FFE247']
                    Pass [] or None to use italic_attrs unchanged for every span.

    Returns
    -------
    Pango markup string ready for TextClip(method='pango').
    """
    colors = italic_colors or []

    combined = re.compile(r'(\*[^*\n]+\*|_[^_\n]+_|-[^-\n]+-)')
    parts = combined.split(text)

    out = []
    italic_index = 0
    for part in parts:
        if _BOLD_RE.fullmatch(part):
            inner = _xml_escape(part[1:-1])
            out.append('<span ' + bold_attrs + '>' + inner + '</span>')
        elif _ITALIC_RE.fullmatch(part):
            inner = _xml_escape(part[1:-1])
            if colors:
                color = colors[italic_index % len(colors)]
                attrs = italic_attrs + ' foreground="' + color + '"'
            else:
                attrs = italic_attrs
            out.append('<span ' + attrs + '>' + inner + '</span>')
            italic_index += 1
        elif _SILENT_RE.fullmatch(part):
            # Show content as plain unstyled text — no dashes, no special style
            inner = _xml_escape(part[1:-1])
            out.append(inner)
        else:
            out.append(_xml_escape(part))

    return "".join(out)


# =============================================================================
# PLAIN-TEXT FALLBACKS
# =============================================================================

def strip_markup(text: str) -> str:
    """
    Remove all markup markers, returning plain text suitable for display.

    -silent- markers: content is KEPT (the text remains visible in subtitles).
    *bold* and _italic_ markers: content is kept, markers stripped.

    Use this for subtitle display fallback when Pango rendering is unavailable.
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


def _xml_escape(text: str) -> str:
    """Escape characters that are special in XML/Pango markup."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text
