"""
utils_markup.py
===============
Converts WhatsApp-style inline markup to Pango markup for TextClip rendering,
and provides a plain-text fallback that strips the markers.

Supported markers
-----------------
  _text_   -> italic + highlight colour  (use for learning features)
  *text*   -> bold                       (use for strong emphasis)

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


def has_markup(text: str) -> bool:
    """Return True if text contains any _italic_ or *bold* markers."""
    return bool(_BOLD_RE.search(text) or _ITALIC_RE.search(text))


def to_pango(text: str, italic_attrs: str, bold_attrs: str,
             italic_colors: list = None) -> str:
    """
    Convert _text_ and *text* markers to Pango <span> tags.

    Each successive _italic_ span cycles through italic_colors.  If a colour
    is available it is appended as foreground="COLOR" to italic_attrs.
    If italic_colors is empty or None, italic_attrs is used as-is for every span.

    Properly escapes XML special characters (&, <, >) in the plain portions
    before inserting tags, so the result is always valid Pango markup.

    Parameters
    ----------
    text          : Raw text with _..._ and *...* markers.
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

    combined = re.compile(r'(\*[^*\n]+\*|_[^_\n]+_)')
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
        else:
            out.append(_xml_escape(part))

    return "".join(out)


def strip_markup(text: str) -> str:
    """
    Remove *bold* and _italic_ markers, returning plain text.
    Used as the fallback when Pango rendering fails, and to clean text
    before sending to TTS (ElevenLabs).
    """
    text = _BOLD_RE.sub(r'\1', text)
    text = _ITALIC_RE.sub(r'\1', text)
    return text


def _xml_escape(text: str) -> str:
    """Escape characters that are special in XML/Pango markup."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text
