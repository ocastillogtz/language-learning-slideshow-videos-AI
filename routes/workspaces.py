"""
routes/workspaces.py
====================
Workspaces = one per language / channel (see db.py).

  GET    /workspaces                        → {active, workspaces, languages}
  POST   /workspaces                        → create (optionally cloning another workspace)
  PUT    /workspaces/<slug>                 → name / language_code / channel_name
  POST   /workspaces/<slug>/activate        → switch the whole app (UI, CLI, MCP) to it
  DELETE /workspaces/<slug>                 → forget it (its folders stay on disk)
  POST   /workspaces/<slug>/image/<kind>    → upload the icon or mascot (multipart "file")
  GET    /workspaces/<slug>/image/<kind>    → serve it
"""

import json
import re
import shutil
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

import db
from core import any_job_running
from languages import LANGUAGES, language

bp = Blueprint("workspaces", __name__, url_prefix="")

IMAGE_KINDS = {"icon": "icon_path", "mascot": "mascot_path"}
IMAGE_EXTS  = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
# Created in every new workspace's assets folder (see migrate_to_db.py for the layout).
ASSET_SUBDIRS = ("branding", "characters", "locations", "studios/podcast", "icons", "samples", "cache")


def _view(ws: dict) -> dict:
    lang = language(ws["language_code"])
    out = {**ws, "language": lang}
    for kind, field in IMAGE_KINDS.items():
        out[f"{kind}_url"] = (f"/workspaces/{ws['slug']}/image/{kind}?v={ws['updated_at']}"
                              if ws.get(field) else None)
    return out


@bp.route("/workspaces")
def list_workspaces():
    try:
        return jsonify({
            "active":     db.active_workspace_slug(),
            "workspaces": [_view(w) for w in db.list_workspaces()],
            "languages":  [{"code": c, **v} for c, v in LANGUAGES.items()],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s or "workspace"


def _copy_tree(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _referenced_dirs(docs: dict, fields: tuple[str, ...]) -> set[str]:
    """Top two path segments (e.g. characters/Zahra) of every file a catalog references."""
    out = set()
    for doc in docs.values():
        for f in fields:
            rel = (doc.get(f) or "").replace("\\", "/")
            parts = rel.split("/")
            if len(parts) >= 3:
                out.add("/".join(parts[:2]))
    return out


@bp.route("/workspaces", methods=["POST"])
def create_workspace():
    """Body: {name, language_code, channel_name?, clone_from?, copy?: [settings,
    characters, locations]}. Project types always come along (from clone_from, else
    the shipped defaults) so the new workspace can make videos straight away."""
    try:
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        code = data.get("language_code") or ""
        if not name:
            return jsonify({"error": "Name required"}), 400
        if code not in LANGUAGES:
            return jsonify({"error": "Pick a language"}), 400
        slug = _slugify(name)
        n = 2
        while db.get_workspace(slug):
            slug = f"{_slugify(name)}_{n}"
            n += 1

        src = db.get_workspace(data.get("clone_from") or "") or db.active_workspace()
        copy = set(data.get("copy") or [])

        root = Path("workspaces") / slug
        assets = root / "assets"
        for sub in ASSET_SUBDIRS:
            (assets / sub).mkdir(parents=True, exist_ok=True)
        (root / "projects").mkdir(parents=True, exist_ok=True)

        db.create_workspace(slug, name, code, assets.as_posix(), (root / "projects").as_posix(),
                            channel_name=(data.get("channel_name") or "").strip())

        if src:
            src_assets = Path(src["assets_dir"])
            # Render-time essentials: overlay icons + subtitle preview backgrounds.
            _copy_tree(src_assets / "icons", assets / "icons")
            _copy_tree(src_assets / "samples", assets / "samples")
            db.copy_assets("project_types", src["slug"], slug)
            db.copy_assets("subtitle_profiles", src["slug"], slug)
            if "settings" in copy:
                db.copy_settings(src["slug"], slug)
            for kind, fields in (("characters", ("artwork_file_path", "art_34left_file_path",
                                                 "thumbnail_file_path", "concept_art_file_path",
                                                 "ref_image_file_path", "ref_drawing_file_path")),
                                 ("locations", ("artwork_file_path",))):
                if kind in copy:
                    docs = db.load_assets(kind, src["slug"])
                    for d in _referenced_dirs(docs, fields):
                        _copy_tree(src_assets / d, assets / d)
                    db.save_assets(kind, docs, slug)
        else:
            from routes.settings import DEFAULT_TYPES
            if DEFAULT_TYPES.exists():
                db.save_assets("project_types", json.loads(DEFAULT_TYPES.read_text(encoding="utf-8")), slug)

        return jsonify({"ok": True, "workspace": _view(db.get_workspace(slug))})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/workspaces/<slug>", methods=["PUT"])
def update_workspace(slug):
    try:
        data = request.get_json(force=True) or {}
        fields = {k: (data[k] or "").strip() for k in ("name", "channel_name") if k in data}
        if "language_code" in data:
            if data["language_code"] not in LANGUAGES:
                return jsonify({"error": "Unknown language"}), 400
            fields["language_code"] = data["language_code"]
        if fields.get("name") == "":
            return jsonify({"error": "Name required"}), 400
        return jsonify({"ok": True, "workspace": _view(db.update_workspace(slug, **fields))})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/workspaces/<slug>/activate", methods=["POST"])
def activate_workspace(slug):
    try:
        if any_job_running():
            return jsonify({"error": "A pipeline job is still running — wait for it to finish before switching."}), 409
        db.set_active_workspace(slug)
        return jsonify({"ok": True, "active": slug})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404


@bp.route("/workspaces/<slug>", methods=["DELETE"])
def delete_workspace(slug):
    try:
        if slug == db.active_workspace_slug():
            return jsonify({"error": "Switch to another workspace before removing this one."}), 400
        ws = db.get_workspace(slug)
        if not ws:
            return jsonify({"error": "Not found"}), 404
        db.delete_workspace(slug)
        return jsonify({"ok": True, "kept_folders": [ws["assets_dir"], ws["projects_dir"]]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/workspaces/<slug>/image/<kind>", methods=["POST"])
def upload_image(slug, kind):
    try:
        ws = db.get_workspace(slug)
        if not ws or kind not in IMAGE_KINDS:
            return jsonify({"error": "Not found"}), 404
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "No file"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in IMAGE_EXTS:
            return jsonify({"error": f"Unsupported image type {ext}"}), 400
        branding = Path(ws["assets_dir"]) / "branding"
        branding.mkdir(parents=True, exist_ok=True)
        for old in branding.glob(f"{kind}.*"):          # one icon / one mascot per workspace
            old.unlink()
        f.save(branding / f"{kind}{ext}")
        updated = db.update_workspace(slug, **{IMAGE_KINDS[kind]: f"branding/{kind}{ext}"})
        return jsonify({"ok": True, "workspace": _view(updated)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/workspaces/<slug>/image/<kind>")
def serve_image(slug, kind):
    ws = db.get_workspace(slug)
    if not ws or kind not in IMAGE_KINDS or not ws.get(IMAGE_KINDS[kind]):
        abort(404)
    path = Path(ws["assets_dir"]) / ws[IMAGE_KINDS[kind]]
    if not path.is_file():
        abort(404)
    return send_file(path.resolve())
