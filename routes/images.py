import io as _io
import json
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify

from core import projects_dir, get_cfg, run_job

logger = logging.getLogger(__name__)
bp = Blueprint("images", __name__, url_prefix="")


@bp.route("/projects/<name>/upload/sample_image", methods=["POST"])
def upload_sample_image(name):
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        slot = request.form.get("slot", "").strip()
        if not slot:
            return jsonify({"error": "slot required (narration | dialog_N)"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "Empty filename"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            return jsonify({"error": f"Unsupported type {ext}. Use PNG/JPG/WEBP."}), 400

        images_dir = projects_dir() / name / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        from PIL import Image as PILImage
        img = PILImage.open(_io.BytesIO(f.read())).convert("RGB")
        save_name = f"sample_{slot}.png"
        img.save(images_dir / save_name, format="PNG")
        rel_path = f"images/{save_name}"

        mp = projects_dir() / name / "project_manifest.json"
        with open(mp, encoding="utf-8") as fh:
            m = json.load(fh)

        if slot == "narration":
            narr = m.get("conversation", {}).get("narration") or {}
            narr["sample-image"] = rel_path
            m["conversation"]["narration"] = narr
        elif slot.startswith("dialog_"):
            sidx = int(slot.split("_", 1)[1])
            m["conversation"]["dialog"][sidx]["sample-image"] = rel_path
        else:
            return jsonify({"error": f"Unknown slot: {slot}"}), 400

        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=2, ensure_ascii=False)
        return jsonify({"message": "Sample image saved", "path": rel_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/projects/<name>/upload/sample_image/<slot>", methods=["DELETE"])
def delete_sample_image(name, slot):
    try:
        mp = projects_dir() / name / "project_manifest.json"
        with open(mp, encoding="utf-8") as f:
            m = json.load(f)
        if slot == "narration":
            rel = (m.get("conversation", {}).get("narration") or {}).pop("sample-image", None)
        elif slot.startswith("dialog_"):
            sidx = int(slot.split("_", 1)[1])
            rel = m["conversation"]["dialog"][sidx].pop("sample-image", None)
        else:
            return jsonify({"error": f"Unknown slot: {slot}"}), 400
        if rel:
            fp = projects_dir() / name / rel
            if fp.exists():
                fp.unlink()
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
        return jsonify({"message": "Sample image removed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
