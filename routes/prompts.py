import json
from flask import Blueprint, request, jsonify

from core import PROJECTS_DIR, cfg
from utils_config import load_new_characters, load_project_types, get_new_locations_flat

bp = Blueprint("prompts", __name__, url_prefix="")


@bp.route("/projects/<name>/prompt/script", methods=["POST"])
def preview_script_prompt(name):
    """
    Build and return the GPT prompt that would be used for script generation,
    WITHOUT actually calling GPT.  Lets the user inspect/edit it before running.

    Accepts JSON body:
      char_a           — character A name
      char_b           — character B name
      location_key     — location key
      project_type_key — project type key (defaults to manifest value)
    """
    try:
        data             = request.get_json() or {}
        char_a           = (data.get("char_a") or "").strip()
        char_b           = (data.get("char_b") or "").strip()
        extra_chars      = data.get("characters") or []   # full/extra cast (multi-character types)
        location_key     = (data.get("location_key") or "").strip() or None
        project_type_key = (data.get("project_type_key") or "").strip()
        words            = data.get("words") or None   # list[str] for word_learning type
        raw_count        = data.get("dialog_count")
        dialog_count     = int(raw_count) if raw_count not in (None, "") else None

        if not char_a or not char_b:
            return jsonify({"error": "char_a and char_b are required"}), 400

        # Full cast: A + B first, then any extras, de-duplicated.
        cast = []
        for nm in [char_a, char_b, *extra_chars]:
            nm = (nm or "").strip()
            if nm and nm not in cast:
                cast.append(nm)

        # Load assets
        assets_dir    = cfg["assets_dir"]
        chars_data    = load_new_characters(assets_dir)
        project_types = load_project_types(assets_dir)
        all_locs      = get_new_locations_flat(assets_dir)

        # Validate inputs
        for cname in cast:
            if cname not in chars_data:
                return jsonify({"error": f"Character '{cname}' not found"}), 400
        if location_key and location_key not in all_locs:
            return jsonify({"error": f"Location '{location_key}' not found"}), 400

        # Load manifest and temporarily patch generation_config with the preview values
        mp = PROJECTS_DIR / name / "project_manifest.json"
        if not mp.exists():
            return jsonify({"error": "Project not found"}), 404

        with open(mp, encoding="utf-8") as f:
            manifest = json.load(f)

        # Use the project_type_key from the request, or fall back to manifest
        pt_key = project_type_key or manifest.get("project_metadata", {}).get("project_type_key", "shadowing")
        if pt_key not in project_types:
            return jsonify({"error": f"Project type '{pt_key}' not found"}), 400

        # Patch manifest's generation_config with the preview selections
        # (we do NOT write this to disk — it's just for building the prompt)
        manifest.setdefault("generation_config", {})
        manifest["generation_config"]["characters"]   = cast
        manifest["generation_config"]["location_key"] = location_key or ""
        if "level" not in manifest["generation_config"]:
            manifest["generation_config"]["level"] = cfg.get("level", "B1")
        if words is not None:
            manifest["generation_config"]["words"] = words
        if dialog_count is not None:
            manifest["generation_config"]["dialog_count"] = dialog_count

        # Resolve base_type inheritance so _long types get description_for_prompt
        project_type = dict(project_types[pt_key])
        base_key = project_type.get("base_type")
        if base_key and base_key in project_types:
            project_type = {**project_types[base_key], **project_type}

        from create_script import _build_prompt, MAX_SCENE_CHARACTERS
        prompt = _build_prompt(project_type, manifest, chars_data, all_locs,
                               max_scene_chars=int(cfg.get("max_scene_characters") or MAX_SCENE_CHARACTERS))
        return jsonify({"prompt": prompt})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
