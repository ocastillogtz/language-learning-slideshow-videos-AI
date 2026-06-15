"""
create_images.py
================
Generates images for every scene in manifest["scenes"] that has a non-null
image object with file_path == null.

The prompt is already fully built and stored in scene.image.prompt_to_create
by create_script.py. This module only needs to:
  1. Build the reference composite image for fal.ai (character art + location)
  2. Upload the composite
  3. Call fal.ai with the stored prompt
  4. Save the result and fill scene.image.file_path

Reference composite types (scene.image.reference_type)
-------------------------------------------------------
  "both"          → char_a art + char_b art + location background
  "single_speaker"→ speaker art + location background

Flags
-----
  overwrite — regenerate even if file already exists in project/images/
"""

import io
import json
import logging
import argparse
import urllib.request
from pathlib import Path
from typing import Any

import fal_client
from PIL import Image
from dotenv import load_dotenv

from utils_config import load_config, load_new_characters, get_new_locations_flat

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _write_manifest(manifest_path, manifest):
    """Atomic manifest write so an interrupted run can't corrupt or lose it."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)

COMPOSITE_HEIGHT = 768
SEPARATOR_PX     = 4
SEPARATOR_COLOR  = (220, 220, 220)


# =============================================================================
# COMPOSITING
# =============================================================================

def _scale_to_height(img: Image.Image, h: int) -> Image.Image:
    w0, h0 = img.size
    return img.resize((int(w0 * h / h0), h), Image.LANCZOS)


def build_composite(*paths: Path, height: int = COMPOSITE_HEIGHT) -> Image.Image:
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Image not found: {p}")
    panels = [_scale_to_height(Image.open(p).convert("RGB"), height) for p in paths]
    sep    = Image.new("RGB", (SEPARATOR_PX, height), SEPARATOR_COLOR)
    pieces: list[Image.Image] = []
    for i, panel in enumerate(panels):
        pieces.append(panel)
        if i < len(panels) - 1:
            pieces.append(sep)
    total_w = sum(p.width for p in pieces)
    out = Image.new("RGB", (total_w, height), (255, 255, 255))
    x = 0
    for piece in pieces:
        out.paste(piece, (x, 0))
        x += piece.width
    return out


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# =============================================================================
# FAL.AI
# =============================================================================

def _log_progress(update: Any) -> None:
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            logger.info(f"  [fal] {log['message']}")


def _upload(image_bytes: bytes) -> str:
    logger.info(f"  Uploading {len(image_bytes)//1024} KB …")
    url: str = fal_client.upload(image_bytes, content_type="image/png")
    logger.info(f"  Uploaded → {url}")
    return url


def _call_fal(prompt: str, image_url: str, model: str, image_size: str) -> bytes:
    result = fal_client.subscribe(
        model,
        arguments={"prompt": prompt, "image_size": image_size, "image_urls": [image_url]},
        with_logs=True,
        on_queue_update=_log_progress,
    )
    url: str = result["images"][0]["url"]
    with urllib.request.urlopen(url, timeout=60) as resp:
        data: bytes = resp.read()
    logger.info(f"  Downloaded {len(data)//1024} KB")
    return data


def _call_fal_text_only(prompt: str, model: str, image_size: str) -> bytes:
    """Generate an image from text only — no reference composite."""
    result = fal_client.subscribe(
        model,
        arguments={"prompt": prompt, "image_size": image_size},
        with_logs=True,
        on_queue_update=_log_progress,
    )
    url: str = result["images"][0]["url"]
    with urllib.request.urlopen(url, timeout=60) as resp:
        data: bytes = resp.read()
    logger.info(f"  Downloaded {len(data)//1024} KB")
    return data


def _save(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info(f"  Saved → {path}")



# =============================================================================
# REFERENCE RESOLUTION (single-ref / animal characters)
# =============================================================================

def _char_ref_path(char_data: dict, assets_dir: Path):
    """Reference image for a character: single-ref image if set, else 3/4-left art."""
    rel = None
    if char_data.get("single_ref"):
        rel = char_data.get("ref_image_file_path")
    rel = rel or char_data.get("art_34left_file_path") or char_data.get("ref_image_file_path")
    return (assets_dir / rel) if rel else None


def _reading_cast_paths(img: dict, chars_data: dict, assets_dir: Path) -> list:
    """Resolve reference images for the cast present in a reading scene."""
    paths = []
    for nm in (img.get("_cast") or []):
        cd = chars_data.get(nm)
        if not cd:
            continue
        p = _char_ref_path(cd, assets_dir)
        if p and p.exists():
            paths.append(p)
    return paths


# =============================================================================
# MAIN
# =============================================================================

def create_images(
    project_name: str,
    overwrite: bool = False,
    ignore_cache: bool = False,   # kept for API compat; has no effect (caching removed)
    use_location_ref: bool = True,
) -> None:
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    chars_data = load_new_characters(cfg["assets_dir"])
    all_locs   = get_new_locations_flat(cfg["assets_dir"])

    images_dir = project_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    model      = cfg["fal_model"]
    t2i_model  = cfg["fal_t2i_model"]
    image_size = cfg["fal_image_size"]
    assets_dir = cfg["assets_dir"]

    # Override image_size for horizontal (Full HD 16:9) projects
    video_format = manifest.get("video_info", {}).get("video_format", "vertical")
    if video_format == "horizontal":
        image_size = "landscape_16_9"
        logger.info("Horizontal format detected — using landscape_16_9 image size")

    # Resolve character names and location from generation_config.
    # reading_together projects may have no fixed characters -> guard against it.
    gen        = manifest["generation_config"]
    char_names = gen.get("characters") or []
    char_a     = char_names[0] if len(char_names) > 0 else None
    char_b     = char_names[1] if len(char_names) > 1 else None
    loc_key    = gen.get("location_key") or ""
    loc_file   = None
    if loc_key and loc_key in all_locs:
        loc_data = all_locs[loc_key]
        loc_file = assets_dir / loc_data["artwork_file_path"]

    # Character art paths (None when the project has no fixed cast)
    art_a = _char_ref_path(chars_data[char_a], assets_dir) if char_a and char_a in chars_data else None
    art_b = _char_ref_path(chars_data[char_b], assets_dir) if char_b and char_b in chars_data else None

    for scene in manifest["scenes"]:
        img = scene.get("image")
        if not img:
            continue  # pause, sfx, video_clip scenes have no image

        dest = images_dir / f"{scene['id']}.png"

        if not overwrite and dest.exists():
            logger.info(f"  Exists: {dest.name} — skipping")
            img["file_path"] = f"images/{scene['id']}.png"
            _write_manifest(manifest_path, manifest)
            continue

        prompt         = img.get("prompt_to_create", "")
        reference_type = img.get("reference_type", "both")

        logger.info(f"Generating [{scene['id']}] reference_type={reference_type}")

        try:
            if reference_type == "none":
                # Text-only generation — no reference composite
                data = _call_fal_text_only(prompt, t2i_model, image_size)
            elif reference_type == "reading_cast":
                # reading_together: composite whatever cast members appear in the scene
                ref_paths = _reading_cast_paths(img, chars_data, assets_dir)
                if ref_paths:
                    url  = _upload(_to_bytes(build_composite(*ref_paths)))
                    data = _call_fal(prompt, url, model, image_size)
                else:
                    data = _call_fal_text_only(prompt, t2i_model, image_size)
            elif reference_type == "multi":
                # multi-character dialog scene: composite every character present in
                # this line (img["_cast"]) plus the optional location background.
                ref_paths = _reading_cast_paths(img, chars_data, assets_dir)
                comp_inputs = list(ref_paths)
                if use_location_ref and loc_file:
                    comp_inputs.append(loc_file)
                if comp_inputs:
                    url  = _upload(_to_bytes(build_composite(*comp_inputs)))
                    data = _call_fal(prompt, url, model, image_size)
                else:
                    data = _call_fal_text_only(prompt, t2i_model, image_size)
            elif reference_type == "single_speaker":
                speaker = img.get("speaker") or (scene.get("characters") or [char_a])[0]
                art_spk = _char_ref_path(chars_data[speaker], assets_dir) if speaker in chars_data else None
                if art_spk and use_location_ref and loc_file:
                    comp = build_composite(art_spk, loc_file)
                elif art_spk:
                    comp = build_composite(art_spk)
                else:
                    comp = None
                if comp is not None:
                    url  = _upload(_to_bytes(comp))
                    data = _call_fal(prompt, url, model, image_size)
                else:
                    data = _call_fal_text_only(prompt, t2i_model, image_size)
            elif art_a and art_b:
                # "both" — use both characters + optional location
                if use_location_ref and loc_file:
                    comp = build_composite(art_a, art_b, loc_file)
                else:
                    comp = build_composite(art_a, art_b)
                url  = _upload(_to_bytes(comp))
                data = _call_fal(prompt, url, model, image_size)
            else:
                # no usable references — fall back to text-only
                data = _call_fal_text_only(prompt, t2i_model, image_size)

            _save(data, dest)
            img["file_path"] = f"images/{scene['id']}.png"
            _write_manifest(manifest_path, manifest)

        except Exception as e:
            logger.error(f"  Failed to generate image for {scene['id']}: {e}")
            continue

    _write_manifest(manifest_path, manifest)
    logger.info("Image generation complete.")


def create_image_single(
    project_name: str,
    scene_id: str,
    prompt_override: str | None = None,
    use_location_ref: bool = True,
    characters_override: str | None = None,
    cast_override: list | None = None,
) -> None:
    """Regenerate the image for a single scene by ID.

    Generates only the target scene directly, without touching any other scene.
    When use_location_ref=False the location artwork is omitted from the
    reference composite, letting the model invent its own background.
    characters_override can be "none" (text-only), "single_speaker", or "both".
    When None, the scene's stored reference_type is used.
    """
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    target = next((s for s in manifest["scenes"] if s["id"] == scene_id), None)
    if not target:
        raise ValueError(f"Scene '{scene_id}' not found in manifest.")
    if not target.get("image"):
        raise ValueError(f"Scene '{scene_id}' has no image.")

    chars_data = load_new_characters(cfg["assets_dir"])
    all_locs   = get_new_locations_flat(cfg["assets_dir"])

    images_dir = project_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    model      = cfg["fal_model"]
    t2i_model  = cfg["fal_t2i_model"]
    image_size = cfg["fal_image_size"]
    assets_dir = cfg["assets_dir"]

    # Override image_size for horizontal (Full HD 16:9) projects
    video_format = manifest.get("video_info", {}).get("video_format", "vertical")
    if video_format == "horizontal":
        image_size = "landscape_16_9"

    gen        = manifest["generation_config"]
    char_names = gen.get("characters") or []
    char_a     = char_names[0] if len(char_names) > 0 else None
    char_b     = char_names[1] if len(char_names) > 1 else None
    loc_key    = gen.get("location_key") or ""
    loc_file   = None
    if loc_key and loc_key in all_locs:
        loc_data = all_locs[loc_key]
        loc_file = assets_dir / loc_data["artwork_file_path"]

    art_a = _char_ref_path(chars_data[char_a], assets_dir) if char_a and char_a in chars_data else None
    art_b = _char_ref_path(chars_data[char_b], assets_dir) if char_b and char_b in chars_data else None

    img = target["image"]

    if prompt_override:
        img["prompt_to_create"] = prompt_override

    prompt = img.get("prompt_to_create", "")
    stored_ref = img.get("reference_type", "both")
    # Use characters_override if provided, otherwise fall back to stored reference_type
    reference_type = characters_override if characters_override else stored_ref
    # Reading_together scenes always composite their stored cast (the rt_* single-image
    # characters from the cast step). Don't let a stale both/single override drop them;
    # only an explicit "none" downgrades a reading scene to text-only. Multi-character
    # dialog scenes (stored_ref == "multi") keep their own mode instead.
    if (target.get("_reading") or stored_ref == "reading_cast") and reference_type != "none":
        reference_type = "reading_cast"
    # Explicit per-scene cast selection from the UI applies to both cast-based modes
    # (reading_together and multi-character dialog).
    if cast_override is not None and reference_type in ("reading_cast", "multi"):
        img["_cast"] = list(cast_override)
        target["_cast"] = list(cast_override)
    dest           = images_dir / f"{scene_id}.png"

    logger.info(f"Re-generating [{scene_id}] reference_type={reference_type}")

    if reference_type == "none":
        # Text-only generation — no reference composite
        data = _call_fal_text_only(prompt, t2i_model, image_size)
    elif reference_type == "reading_cast":
        ref_paths = _reading_cast_paths(img, chars_data, assets_dir)
        if ref_paths:
            url  = _upload(_to_bytes(build_composite(*ref_paths)))
            data = _call_fal(prompt, url, model, image_size)
        else:
            data = _call_fal_text_only(prompt, t2i_model, image_size)
    elif reference_type == "multi":
        # multi-character dialog scene: present cast (img["_cast"]) + optional location
        ref_paths   = _reading_cast_paths(img, chars_data, assets_dir)
        comp_inputs = list(ref_paths)
        if use_location_ref and loc_file:
            comp_inputs.append(loc_file)
        if comp_inputs:
            url  = _upload(_to_bytes(build_composite(*comp_inputs)))
            data = _call_fal(prompt, url, model, image_size)
        else:
            data = _call_fal_text_only(prompt, t2i_model, image_size)
    elif reference_type == "single_speaker":
        speaker = img.get("speaker") or (target.get("characters") or [char_a])[0]
        art_spk = _char_ref_path(chars_data[speaker], assets_dir) if speaker in chars_data else None
        if art_spk and use_location_ref and loc_file:
            comp = build_composite(art_spk, loc_file)
        elif art_spk:
            comp = build_composite(art_spk)
        else:
            comp = None
        if comp is not None:
            url  = _upload(_to_bytes(comp))
            data = _call_fal(prompt, url, model, image_size)
        else:
            data = _call_fal_text_only(prompt, t2i_model, image_size)
    elif art_a and art_b:
        # "both" — use both characters + optional location
        if use_location_ref and loc_file:
            comp = build_composite(art_a, art_b, loc_file)
        else:
            comp = build_composite(art_a, art_b)
        url  = _upload(_to_bytes(comp))
        data = _call_fal(prompt, url, model, image_size)
    else:
        data = _call_fal_text_only(prompt, t2i_model, image_size)

    _save(data, dest)

    img["file_path"] = f"images/{scene_id}.png"

    # Invalidate the rendered video clip so the next render pass rebuilds it
    video_clip = project_path / "videos" / f"{scene_id}.mp4"
    if video_clip.exists():
        video_clip.unlink()
        logger.info(f"Deleted stale video clip: {video_clip.name}")

    _write_manifest(manifest_path, manifest)

    logger.info(f"Single image regeneration complete for scene '{scene_id}'.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project_name")
    p.add_argument("--overwrite",    action="store_true")
    p.add_argument("--scene-id",     dest="scene_id",
                   help="Regenerate a single scene by ID")
    p.add_argument("--prompt-override", dest="prompt_override")
    a = p.parse_args()

    if a.scene_id:
        create_image_single(a.project_name, a.scene_id,
                            prompt_override=a.prompt_override)
    else:
        create_images(a.project_name, overwrite=a.overwrite)


if __name__ == "__main__":
    main()
