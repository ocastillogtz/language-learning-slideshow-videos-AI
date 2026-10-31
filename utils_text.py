"""
utils_text.py
=============
Plain-text helpers shared by the upload scripts.
"""

import re

# A sentence ends at . ! ? … (optionally followed by a closing quote/bracket).
_SENTENCE_END_RE = re.compile(r'[.!?…]["»“”\')\]]*(?=\s|$)')


def fit_text(text: str, limit: int) -> str:
    """
    Return *text* unchanged when it fits in *limit* characters; otherwise cut
    it after the last complete sentence (falling back to the last paragraph or
    word break) so a description never ends mid-sentence.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
    if ends:
        return head[:ends[-1]].rstrip()
    cut = max(head.rfind("\n"), head.rfind(" "))
    return (head[:cut] if cut > 0 else head).rstrip() + "…"
