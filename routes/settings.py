"""
routes/settings.py
==================
Settings view backend: every config.ini value with its per-workspace override,
plus the project types (script prompts) of the active workspace.

  GET    /settings                          → all sections/keys: value, default, overridden, help
  PUT    /settings                          → {updates: {section: {key: value|null}}}
                                              (null or a value equal to the default = reset)
  GET    /settings/project-types            → {key: document}
  PUT    /settings/project-types/<key>      → replace one type's document
  POST   /settings/project-types/<key>/duplicate → {new_key}
  DELETE /settings/project-types/<key>
  POST   /settings/project-types/reset/<key> → restore the shipped prompt (defaults/project_types.json)

config.ini keeps the defaults every workspace starts from; edits are stored as
overrides of the ACTIVE workspace in data/pipeline.db (db.set_settings).
"""

import json
import re
from pathlib import Path

from flask import Blueprint, jsonify, request

import db
from languages import language
from utils_config import CONFIG_PATH

bp = Blueprint("settings", __name__, url_prefix="")

DEFAULT_TYPES = Path(db.ROOT) / "defaults" / "project_types.json"

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_KV_RE      = re.compile(r"^\s*(?P<key>[A-Za-z0-9_]+)\s*=(?P<after>.*)$")
_HIDDEN     = {"paths", "comfyui"}      # folders come from the workspace; comfyui is legacy


def _split_inline(after: str) -> tuple[str, str]:
    """Value and inline comment of a `key = value  ; note` line (utils_config's rule:
    a ';' only starts a comment when it is first or preceded by whitespace)."""
    stripped = after.lstrip()
    if stripped.startswith(";"):
        return "", stripped[1:].strip()
    m = re.search(r"\s;", after)
    if m:
        return after[:m.start()].strip(), after[m.end():].strip()
    return after.strip(), ""


def _parse_config() -> list[dict]:
    """config.ini as [{name, help, keys: [{key, default, help}]}], keeping the file's
    order and turning its comments into help text."""
    sections: list[dict] = []
    cur = None
    pending: list[str] = []
    for line in Path(CONFIG_PATH).read_text(encoding="utf-8").splitlines():
        m = _SECTION_RE.match(line)
        if m:
            cur = {"name": m["name"].strip().lower(), "help": "", "keys": []}
            sections.append(cur)
            pending = []
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith(";") or s.startswith("#"):
            pending.append(s.lstrip(";#").strip())
            continue
        if not s:
            # A comment block right under the header describes the whole section.
            if pending and not cur["keys"] and not cur["help"]:
                cur["help"] = " ".join(pending)
            pending = []
            continue
        kv = _KV_RE.match(line)
        if kv:
            value, inline = _split_inline(kv["after"])
            help_text = " ".join(p for p in pending + [inline] if p)
            cur["keys"].append({"key": kv["key"].lower(), "default": value, "help": help_text})
            pending = []
    return sections


@bp.route("/settings")
def get_settings():
    try:
        ws = db.active_workspace()
        overrides = db.get_settings(ws["slug"]) if ws else {}
        out = []
        for sec in _parse_config():
            if sec["name"] in _HIDDEN:
                continue
            ov = overrides.get(sec["name"], {})
            keys = []
            for k in sec["keys"]:
                if ws and (sec["name"], k["key"]) == ("song", "stt_language"):
                    k = {**k, "default": language(ws["language_code"])["stt"]}
                value = ov.get(k["key"], k["default"])
                keys.append({**k, "value": value, "overridden": k["key"] in ov})
            out.append({**sec, "keys": keys})
        return jsonify({"workspace": ws, "sections": out})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/settings", methods=["PUT"])
def put_settings():
    try:
        ws = db.active_workspace_slug()
        if not ws:
            return jsonify({"error": "No workspace configured"}), 400
        updates = (request.get_json(force=True) or {}).get("updates") or {}
        defaults = {s["name"]: {k["key"]: k["default"] for k in s["keys"]} for s in _parse_config()}
        defaults.setdefault("song", {})["stt_language"] = language(db.get_workspace(ws)["language_code"])["stt"]
        clean: dict[str, dict] = {}
        for section, kv in updates.items():
            for key, value in (kv or {}).items():
                sec, k = section.lower(), key.lower()
                if sec in _HIDDEN:
                    continue
                # Same as the default → drop the override so the workspace follows config.ini.
                if value is not None and str(value) == defaults.get(sec, {}).get(k):
                    value = None
                clean.setdefault(sec, {})[k] = None if value is None else str(value)
        db.set_settings(ws, clean)
        return jsonify({"ok": True, "saved": sum(len(v) for v in clean.values())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Project types (script prompts)
# =============================================================================

@bp.route("/settings/project-types")
def list_types():
    try:
        shipped = json.loads(DEFAULT_TYPES.read_text(encoding="utf-8")) if DEFAULT_TYPES.exists() else {}
        types = db.load_assets("project_types")
        return jsonify({"types": types, "shipped": sorted(shipped)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _save_type(key: str, doc: dict) -> None:
    types = db.load_assets("project_types")
    types[key] = doc
    db.save_assets("project_types", types)


@bp.route("/settings/project-types/<key>", methods=["PUT"])
def put_type(key):
    try:
        doc = request.get_json(force=True)
        if not isinstance(doc, dict):
            return jsonify({"error": "Body must be the project type JSON object"}), 400
        prompt = doc.get("description_for_prompt")
        if prompt is not None and not isinstance(prompt, str):
            return jsonify({"error": "description_for_prompt must be text"}), 400
        if isinstance(prompt, str):
            try:
                # Literal braces must be doubled ({{ }}): catch broken templates on save,
                # not when a script is generated.
                prompt.format_map(_AnyPlaceholder())
            except (ValueError, IndexError) as e:
                return jsonify({"error": f"Prompt template error: {e}. Write literal braces as {{{{ and }}}}."}), 400
        _save_type(key, doc)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


class _AnyPlaceholder(dict):
    def __missing__(self, key):
        return ""


@bp.route("/settings/project-types/<key>/duplicate", methods=["POST"])
def duplicate_type(key):
    try:
        new_key = re.sub(r"[^a-z0-9_]+", "_", ((request.get_json(force=True) or {}).get("new_key") or "").strip().lower()).strip("_")
        types = db.load_assets("project_types")
        if key not in types:
            return jsonify({"error": f"Project type '{key}' not found"}), 404
        if not new_key or new_key in types:
            return jsonify({"error": "Pick a new, unused key"}), 400
        doc = json.loads(json.dumps(types[key]))
        doc["name"] = new_key
        types[new_key] = doc
        db.save_assets("project_types", types)
        return jsonify({"ok": True, "key": new_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/settings/project-types/<key>", methods=["DELETE"])
def delete_type(key):
    try:
        types = db.load_assets("project_types")
        if types.pop(key, None) is None:
            return jsonify({"error": f"Project type '{key}' not found"}), 404
        db.save_assets("project_types", types)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/settings/project-types/reset/<key>", methods=["POST"])
def reset_type(key):
    try:
        shipped = json.loads(DEFAULT_TYPES.read_text(encoding="utf-8"))
        if key not in shipped:
            return jsonify({"error": f"No shipped default for '{key}'"}), 404
        _save_type(key, shipped[key])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

