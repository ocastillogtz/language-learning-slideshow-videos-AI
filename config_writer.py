"""
config_writer.py
================
In-place, comment-preserving updater for config.ini.

utils_config.load_config() is read-only; this is the write side used by the
frontend "Subtitles" styling page to persist tweaked overlay parameters.

Unlike configparser.write() (which drops every comment and rewrites the whole
file), this edits ONLY the value portion of the specific `key = value` lines it
is asked to change, leaving all comments, blank lines, ordering, and untouched
keys exactly as they were. Any inline `; comment` on an edited line is kept.
"""

import re
from pathlib import Path

CONFIG_PATH = Path("config.ini")

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
# A `key = value` line. `eq` keeps the key-side spacing + '='; `after` is everything
# past '=' (value, alignment padding, and any inline comment). Keys are simple idents.
_KV_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_]+)(?P<eq>\s*=)(?P<after>.*)$")


def _parse_after(after: str) -> tuple[str, str]:
    """Split the text after '=' into (value, comment).

    value   — the value with surrounding whitespace stripped (may be "").
    comment — the inline comment normalised to start at ';' (no leading whitespace),
              or "" if the line has none. An inline comment is a ';' that is the first
              non-space char or is preceded by whitespace (utils_config's rule). This
              correctly treats `key =        ; note` as value "" with a kept comment.
    """
    lstripped = after.lstrip()
    if lstripped.startswith(";"):
        return "", lstripped
    m = re.search(r"\s;", after)
    if m:
        return after[: m.start()].strip(), after[m.start():].lstrip()
    return after.strip(), ""


def update_config_values(updates: dict[str, dict[str, object]],
                         config_path: Path = CONFIG_PATH) -> None:
    """Apply `updates` = {section: {key: value}} to config.ini in place.

    - Existing keys have only their value replaced (inline comments preserved).
    - A key not found in its (existing) section is appended to the end of that
      section's body.
    - Section and key matching is case-insensitive (config keys are lowercased
      by configparser at read time, so this stays consistent).
    Values are written via str(); pass already-formatted strings for full control.
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)

    # Normalise the requested updates to lowercase section/key for matching, but
    # keep the original key casing to write new keys with a sensible name.
    want: dict[str, dict[str, tuple[str, str]]] = {}
    for section, kv in updates.items():
        sec = section.lower()
        want.setdefault(sec, {})
        for key, value in kv.items():
            want[sec][key.lower()] = (key, "" if value is None else str(value))

    # Split the file into blocks: (section_name | None, [lines...]).
    blocks: list[tuple[str | None, list[str]]] = []
    cur_name: str | None = None
    cur_lines: list[str] = []
    for ln in lines:
        m = _SECTION_RE.match(ln)
        if m:
            blocks.append((cur_name, cur_lines))
            cur_name = m.group("name")
            cur_lines = [ln]
        else:
            cur_lines.append(ln)
    blocks.append((cur_name, cur_lines))

    for name, blk in blocks:
        if name is None:
            continue
        pending = want.get(name.lower())
        if not pending:
            continue
        seen: set[str] = set()
        for i, ln in enumerate(blk):
            kv = _KV_RE.match(ln)
            if not kv:
                continue
            key = kv.group("key").lower()
            if key in pending:
                seen.add(key)
                _orig_key, new_val = pending[key]
                old_val, comment = _parse_after(kv.group("after"))
                if old_val == new_val:
                    continue          # unchanged → leave the line (and its formatting) as-is
                # One space after '='; re-append the inline comment (padded) if there was one.
                tail = f"  {comment}" if comment else ""
                blk[i] = f"{kv.group('indent')}{kv.group('key')}{kv.group('eq')} {new_val}{tail}"
        missing = [(orig, val) for lk, (orig, val) in pending.items() if lk not in seen]
        if missing:
            insert_at = len(blk)
            while insert_at > 0 and blk[insert_at - 1].strip() == "":
                insert_at -= 1
            for orig, val in missing:
                blk.insert(insert_at, f"{orig} = {val}")
                insert_at += 1

    flat: list[str] = []
    for _name, blk in blocks:
        flat.extend(blk)
    path.write_text(newline.join(flat), encoding="utf-8")
