import io as _io
import json
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify

from core import PROJECTS_DIR, cfg, run_job

logger = logging.getLogger(__name__)
bp = Blueprint("images", __name__, url_prefix="")


@bp.route("/projects/<name>/run/image_single", methods=["POST"])
def run_single_image(name):
    try:
        data = request.get_json() or {}
        item_type = data.get("item_type", "dialog")
        dialog_index = int(data.get("dialog_index", 0))
        prompt_override = data.get("prompt_override", "").strip() or None

        def _regen():
            from create_images import (
                _generate, _upload, _save, _to_bytes, build_composite,
                _prompt_both, _prompt_over_shoulder, _prompt_cutaway,
                _prompt_narration,
            )
            from utils_config import load_characters, load_locations, get_all_locations_flat

            mp = PROJECTS_DIR / name / "project_manifest.json"
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)

            chars_data = load_characters(cfg["assets_dir"])
            all_locs = get_all_locations_flat(load_locations(cfg["assets_dir"]))
            images_dir = PROJECTS_DIR / name / "images"
            images_dir.mkdir(exist_ok=True)

            loc_key = m["location-key"]
            loc_data = all_locs[loc_key]
            loc_desc = loc_data["description"]
            loc_file = Path(cfg["assets_dir"]) / loc_data["file"]
            char_a = m["characters"][0]["name"]
            char_b = m["characters"][1]["name"]
            desc_a = chars_data[char_a].get("description", "")
            desc_b = chars_data[char_b].get("description", "")
            ref_desc_a = chars_data[char_a].get("ref_desc", desc_a)
            ref_desc_b = chars_data[char_b].get("ref_desc", desc_b)
            art_a = Path(cfg["assets_dir"]) / chars_data[char_a]["34left"]
            art_b = Path(cfg["assets_dir"]) / chars_data[char_b]["34left"]

            def _resolve_url(item: dict, make_default_bytes):
                rel = item.get("sample-image")
                if rel:
                    sp = PROJECTS_DIR / name / rel
                    if sp.exists():
                        logger.info(f"  Using sample image: {sp.name}")
                        return _upload(sp.read_bytes())
                    logger.warning(f"  Sample image missing ({rel}), using composite")
                return _upload(make_default_bytes())

            if item_type == "narration":
                narr = m["conversation"]["narration"]
                out_path = images_dir / "narration.png"
                prompt = prompt_override or _prompt_narration(char_a, char_b, loc_desc)
                url = _resolve_url(narr, lambda: _to_bytes(build_composite(art_a, art_b, loc_file)))
                data_b = _generate(prompt, url, cfg["fal_model"], cfg["fal_image_size"])
                _save(data_b, out_path)
                narr["image"] = "images/narration.png"
                narr["prompt-image"] = prompt
            else:
                item = m["conversation"]["dialog"][dialog_index]
                shot_type = item.get("shot_type", "both")
                out_path = images_dir / f"dialog_{dialog_index:02d}.png"

                if "cutaway" in item:
                    speaker = item["speaker"]
                    desc_sp = chars_data[speaker].get("description", "")
                    art_sp = Path(cfg["assets_dir"]) / chars_data[speaker]["34left"]
                    prompt = prompt_override or _prompt_cutaway(speaker, desc_sp, item["cutaway"])
                    url = _resolve_url(item, lambda: _to_bytes(build_composite(art_sp)))
                elif shot_type == "both":
                    prompt = prompt_override or _prompt_both(char_a, desc_a, char_b, desc_b, loc_desc)
                    url = _resolve_url(item, lambda: _to_bytes(build_composite(art_a, art_b, loc_file)))
                elif shot_type in ("over_shoulder_A", "over_shoulder_B"):
                    last_both = images_dir / "narration.png"
                    for j in range(dialog_index - 1, -1, -1):
                        prev = m["conversation"]["dialog"][j]
                        p = images_dir / f"dialog_{j:02d}.png"
                        if prev.get("shot_type") == "both" and p.exists():
                            last_both = p
                            break
                    if shot_type == "over_shoulder_A":
                        prompt = prompt_override or _prompt_over_shoulder(ref_desc_a, char_b, desc_b, loc_desc)
                    else:
                        prompt = prompt_override or _prompt_over_shoulder(ref_desc_b, char_a, desc_a, loc_desc)
                    url = _resolve_url(item, lambda: last_both.read_bytes())
                else:
                    prompt = prompt_override or _prompt_both(char_a, desc_a, char_b, desc_b, loc_desc)
                    url = _resolve_url(item, lambda: _to_bytes(build_composite(art_a, art_b, loc_file)))

                data_b = _generate(prompt, url, cfg["fal_model"], cfg["fal_image_size"])
                _save(data_b, out_path)
                item["image"] = f"images/dialog_{dialog_index:02d}.png"
                item["prompt-image"] = prompt

            with open(mp, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=2, ensure_ascii=False)

        step_key = f"image_{item_type}_{dialog_index}"
        run_job(name, step_key, _regen)
        return jsonify({"message": f"Re-generating {item_type} image", "step_key": step_key})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

        images_dir = PROJECTS_DIR / name / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        from PIL import Image as PILImage
        img = PILImage.open(_io.BytesIO(f.read())).convert("RGB")
        save_name = f"sample_{slot}.png"
        img.save(images_dir / save_name, format="PNG")
        rel_path = f"images/{save_name}"

        mp = PROJECTS_DIR / name / "project_manifest.json"
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
        mp = PROJECTS_DIR / name / "project_manifest.json"
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
            fp = PROJECTS_DIR / name / rel
            if fp.exists():
                fp.unlink()
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
        return jsonify({"message": "Sample image removed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
