"""
create_images_local.py

Generate images per scene using a local ComfyUI instance (Flux + LoRA).

Each dialogue scene uses its own visual_context field from the manifest
(written by create_script.py) to drive a scene-specific image:
  - Narrator / establishing scenes: room composition from global visual_context
  - Dialogue scenes: illustrate what the character is talking ABOUT.
    e.g. if they mention going to the movies → show that character at a cinema.
    If no per-scene context is set, falls back to a standard room shot.

The full scene description is sent as the t5xxl prompt (long-text encoder).
The clip_l prompt is always the short style tag from config.

LoRA chain (always in this order):
  1. brezelstyle  — style lora, strength from config (default 0.5)
  2. speaker lora — character lora for the speaking character, strength from config (default 0.5)
  3. other loras  — remaining scene characters with a lora, strength from config (default 0.2)

Characters without a lora entry (empty string) are included only in the
text prompt, not the LoRA chain.

Saves RELATIVE (posix) paths in manifest, same as the OpenAI provider.
"""

import io
import json
import copy
import uuid
import time
import logging
import argparse
import configparser
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional
import random

from PIL import Image
from dotenv import load_dotenv

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
random.seed()

CHARACTER_MAPPING = {
    "Zahra":"ZahraBrezel",
    "Olena":"OlenaBrezel",
    "Amir":"AmirBrezel",
    "Mario":"MarioBrezel",
    "Sani":"SaniBrezel",
    "Wiebke":"WiebkeBrezel",
}

# =========================
# COMFYUI BASE WORKFLOW
# Fixed nodes that never change between renders.
# =========================
BASE_WORKFLOW = {
    "8": {
        "inputs": {"samples": ["31", 0], "vae": ["39", 0]},
        "class_type": "VAEDecode",
        "_meta": {"title": "VAE Decode"}
    },
    "9": {
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
        "class_type": "SaveImage",
        "_meta": {"title": "Save Image"}
    },
    "27": {
        "inputs": {"width": 1024, "height": 1536, "batch_size": 1},
        "class_type": "EmptySD3LatentImage",
        "_meta": {"title": "EmptySD3LatentImage"}
    },
    "31": {
        "inputs": {
            "seed": 0,               # overwritten per render
            "steps": 20,
            "cfg": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1,
            "model": ["LAST_LORA", 0],   # placeholder — replaced in build_workflow
            "positive": ["41", 0],
            "negative": ["42", 0],
            "latent_image": ["27", 0]
        },
        "class_type": "KSampler",
        "_meta": {"title": "KSampler"}
    },
    "38": {
        "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"},
        "class_type": "UNETLoader",
        "_meta": {"title": "Load Diffusion Model"}
    },
    "39": {
        "inputs": {"vae_name": "ae.safetensors"},
        "class_type": "VAELoader",
        "_meta": {"title": "Load VAE"}
    },
    "40": {
        "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp16.safetensors",
            "type": "flux",
            "device": "default"
        },
        "class_type": "DualCLIPLoader",
        "_meta": {"title": "DualCLIPLoader"}
    },
    "41": {
        "inputs": {
            "clip_l": "",            # overwritten per render
            "t5xxl": "",             # overwritten per render
            "guidance": 4,
            "clip": ["LAST_LORA", 1]     # placeholder — replaced in build_workflow
        },
        "class_type": "CLIPTextEncodeFlux",
        "_meta": {"title": "CLIPTextEncodeFlux"}
    },
    "42": {
        "inputs": {"conditioning": ["41", 0]},
        "class_type": "ConditioningZeroOut",
        "_meta": {"title": "ConditioningZeroOut"}
    },
}


# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)

    assets_dir   = Path(config["paths"]["assets_dir"])
    projects_dir = Path(config["paths"]["projects_dir"])
    extend_pad   = config.getfloat("images", "extend_pad_ratio", fallback=0.12)
    log_level    = config.get("images", "log_level", fallback="INFO")

    comfyui_host   = config.get("comfyui", "host",                fallback="127.0.0.1")
    comfyui_port   = config.getint("comfyui", "port",             fallback=8188)
    style_lora     = config.get("comfyui", "style_lora",          fallback="brezelstyle_pytorch_lora_weights.safetensors")
    style_strength = config.getfloat("comfyui", "style_lora_strength", fallback=0.5)
    char_strength  = config.getfloat("comfyui", "char_lora_strength",  fallback=0.5)
    bg_strength    = config.getfloat("comfyui", "bg_lora_strength",    fallback=0.2)
    clip_l_tag     = config.get("comfyui", "clip_l_tag",
                                 fallback="brezelstyle watercolor soft colors thick lining minimal detail")
    poll_interval  = config.getfloat("comfyui", "poll_interval_s", fallback=2.0)
    timeout_s      = config.getfloat("comfyui", "timeout_s",       fallback=300.0)

    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return {
        "assets_dir":     assets_dir,
        "projects_dir":   projects_dir,
        "extend_pad":     extend_pad,
        "host":           comfyui_host,
        "port":           comfyui_port,
        "style_lora":     style_lora,
        "style_strength": style_strength,
        "char_strength":  char_strength,
        "bg_strength":    bg_strength,
        "clip_l_tag":     clip_l_tag,
        "poll_interval":  poll_interval,
        "timeout_s":      timeout_s,
    }


# =========================
# LOAD CHARACTERS
# =========================
def load_characters(assets_dir: Path) -> dict:
    path = assets_dir / "characters.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# RELATIVE PATH HELPER
# =========================
def to_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# =========================
# IMAGE UTIL
# =========================
def extend_image_vertical(input_path: Path, pad_ratio: float = 0.12):
    img = Image.open(input_path).convert("RGB")
    width, height = img.size
    pad = int(height * pad_ratio)
    new_img = Image.new("RGB", (width, height + pad), (255, 255, 255))
    new_img.paste(img, (0, pad // 2))
    new_img.save(input_path)


# =========================
# STYLE BLOCK (mirrors openai version exactly)
# =========================
STYLE_BLOCK = """Style:
- watercolor
- soft tones
- minimal facial detail, minimal clothing detail
- clean thicker outlines
- NEVER render text on images. no subtitles, no speech bubbles, no text.
- no anime eyes
- no blush cheeks

Framing:
- vertical 9:16 composition
- central 80% contains important elements
- leave at least 8% margin on all sides
- no faces near edges
- characters centered
- background softly fades into white at the bottom

Consistency:
- clothing, colors, facial features must remain consistent
- characters must appear only once per image"""


# =========================
# NARRATOR / ESTABLISHING SHOT PROMPT
# =========================
def build_narrator_prompt(
    global_visual_context: str,
    scene_visual_context: str,
    character_details: str,
    characters: List[str],
) -> str:
    scene_note = f"\nScene action: {scene_visual_context}" if scene_visual_context else ""
    return f"""Create a vertical illustration for a YouTube Shorts video.

Setting:
{global_visual_context}{scene_note}

Character details (STRICT consistency required):
{character_details}

{STYLE_BLOCK}

Scene composition:
Wide cinematic establishing shot showing: {', '.join(characters)}.
- Environment clearly visible
- Characters smaller in frame
- Storytelling mood"""


# =========================
# DIALOGUE SCENE PROMPT
# =========================
def build_scene_prompt(
    global_visual_context: str,
    scene_visual_context: str,
    character_details: str,
    speaker: str,
    text: str,
    others: List[str],
) -> str:
    """
    When scene_visual_context is set, it drives the scene completely —
    the image shows what the character is talking ABOUT (cinema, street, etc.).
    The global_visual_context is still referenced for character style anchoring.
    Falls back to a standard room two-shot when scene_visual_context is empty.
    """
    if scene_visual_context:
        scene_description = scene_visual_context
        composition_note  = (
            f"{speaker} is the visual focus. "
            + (f"Other character(s) may appear if relevant: {', '.join(others)}." if others else "")
        )
    else:
        shot_type = random.choice(["over_shoulder", "two_shot"])
        if shot_type == "over_shoulder":
            composition_note = (
                f"Shot: over-the-shoulder. Focus on {speaker}. "
                f"Show {', '.join(others) if others else 'environment'} softly in background."
            )
        else:
            composition_note = (
                f"Shot: two-shot. Show {speaker} and "
                f"{', '.join(others) if others else speaker}. Natural interaction."
            )
        scene_description = global_visual_context

    return f"""Create a vertical illustration for a YouTube Shorts video.

Character style reference (appearance must match these descriptions):
{global_visual_context}

Character details (STRICT consistency required):
{character_details}

{STYLE_BLOCK}

Scene to illustrate (This overrides any previous description of the scene of it doesn't match):
{scene_description}


Composition: {composition_note}"""


# =========================
# LORA LIST BUILDER
# =========================
def build_lora_list(
    speaker: str,
    others: List[str],
    characters_data: dict,
    style_lora: str,
) -> List[str]:
    """
    Build ordered LoRA list:
      [style_lora, speaker_lora (if any), ...other_loras (if any)]

    Characters with an empty or missing lora field are skipped silently —
    they are still described in the text prompt.
    """
    loras = [style_lora]

    def get_lora(name: str) -> Optional[str]:
        lora = characters_data.get(name, {}).get("lora", "")
        return lora if lora else None

    if speaker:
        speaker_lora = get_lora(speaker)
        if speaker_lora:
            loras.append(speaker_lora)

    for other in others:
        other_lora = get_lora(other)
        if other_lora and other_lora not in loras:
            loras.append(other_lora)

    return loras


# =========================
# WORKFLOW BUILDER
# =========================
def build_workflow(
    clip_l: str,
    t5xxl: str,
    lora_names: List[str],
    cfg: dict,
) -> dict:
    """
    Dynamically build a ComfyUI workflow dict.

    lora_names: ordered list of lora filenames to chain.
      [0] = style lora  (always brezelstyle)
      [1] = speaker lora
      [2..] = background character loras

    Strengths assigned by position:
      index 0  → style_strength
      index 1  → char_strength
      index 2+ → bg_strength

    LoRA nodes start at ID 100 to avoid collisions with fixed node IDs.
    """
    workflow = copy.deepcopy(BASE_WORKFLOW)

    prev_model_ref = ["38", 0]   # UNETLoader output
    prev_clip_ref  = ["40", 0]   # DualCLIPLoader output
    last_lora_id   = None

    for i, lora_name in enumerate(lora_names):
        if i == 0:
            strength = cfg["style_strength"]
        elif i == 1:
            strength = cfg["char_strength"]
        else:
            strength = cfg["bg_strength"]

        node_id = str(100 + i)
        workflow[node_id] = {
            "inputs": {
                "lora_name": lora_name,
                "strength_model": strength,
                "strength_clip": strength,
                "model": list(prev_model_ref),
                "clip":  list(prev_clip_ref),
            },
            "class_type": "LoraLoader",
            "_meta": {"title": f"LoRA {i}: {lora_name}"}
        }
        prev_model_ref = [node_id, 0]
        prev_clip_ref  = [node_id, 1]
        last_lora_id   = node_id

    # Wire last LoRA (or UNETLoader if no loras) into KSampler and CLIPTextEncodeFlux
    final_model = last_lora_id if last_lora_id else "38"
    final_clip  = last_lora_id if last_lora_id else "40"
    workflow["31"]["inputs"]["model"] = [final_model, 0]
    workflow["41"]["inputs"]["clip"]  = [final_clip,  1]

    for chara, charabrezel in CHARACTER_MAPPING.items():
        clip_l = clip_l.replace(chara + " ",charabrezel + " ")
        t5xxl = t5xxl.replace(chara + " ",charabrezel  + " ")
        clip_l = clip_l.replace(chara + ",",charabrezel + ",")
        t5xxl = t5xxl.replace(chara + ",",charabrezel  + ",")
        clip_l = clip_l.replace(chara + ".",charabrezel  + ".")
        t5xxl = t5xxl.replace(chara + ".",charabrezel  + ".")
        clip_l = clip_l.replace(chara + ":" ,charabrezel  + ":")
        t5xxl = t5xxl.replace(chara + ":",charabrezel  + ":")

    # Inject prompts and random seed
    workflow["41"]["inputs"]["clip_l"] = clip_l
    workflow["41"]["inputs"]["t5xxl"]  = t5xxl
    logger.info("clip_l: " + clip_l + "\n\n")
    logger.info("t5xxl: " + t5xxl + "\n\n")
    workflow["31"]["inputs"]["seed"]   = 899916076476193

    return workflow


# =========================
# COMFYUI API CLIENT
# =========================
def _comfyui_url(host: str, port: int, path: str) -> str:
    return f"http://{host}:{port}{path}"


def queue_prompt(workflow: dict, client_id: str, host: str, port: int) -> str:
    """POST workflow to /prompt, return prompt_id."""
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    req = urllib.request.Request(
        _comfyui_url(host, port, "/prompt"),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return result["prompt_id"]


def fetch_history(prompt_id: str, host: str, port: int) -> dict:
    url = _comfyui_url(host, port, f"/history/{prompt_id}")
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def fetch_image(filename: str, subfolder: str, folder_type: str, host: str, port: int) -> bytes:
    url = (
        _comfyui_url(host, port, "/view")
        + f"?filename={filename}&subfolder={subfolder}&type={folder_type}"
    )
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def wait_for_image(
    prompt_id: str,
    host: str,
    port: int,
    poll_interval: float,
    timeout_s: float,
) -> bytes:
    """Poll /history until done, then download the first output image."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        history = fetch_history(prompt_id, host, port)
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            for node_output in outputs.values():
                images = node_output.get("images", [])
                if images:
                    img_info = images[0]
                    return fetch_image(
                        img_info["filename"],
                        img_info.get("subfolder", ""),
                        img_info.get("type", "output"),
                        host, port,
                    )
            raise RuntimeError(f"Prompt {prompt_id} finished but no images found in output")
        time.sleep(poll_interval)
    raise TimeoutError(f"ComfyUI did not finish prompt {prompt_id} within {timeout_s}s")


# =========================
# GENERATE ONE IMAGE (ComfyUI)
# =========================
def generate_image_local(
    clip_l: str,
    t5xxl: str,
    lora_names: List[str],
    cfg: dict,
) -> bytes:
    """Build workflow, submit to ComfyUI, wait for result, return PNG bytes."""
    client_id = str(uuid.uuid4())
    workflow  = build_workflow(clip_l, t5xxl, lora_names, cfg)

    logger.info(f"Submitting to ComfyUI | LoRAs: {lora_names}")
    logger.debug(f"t5xxl prompt:\n{t5xxl}")

    prompt_id = queue_prompt(workflow, client_id, cfg["host"], cfg["port"])
    logger.info(f"Prompt queued: {prompt_id}")

    image_bytes = wait_for_image(
        prompt_id,
        cfg["host"], cfg["port"],
        cfg["poll_interval"], cfg["timeout_s"],
    )
    logger.info(f"Image received ({len(image_bytes)} bytes)")
    return image_bytes


# =========================
# SHARED SETUP HELPER
# =========================
def _setup(project_name: str):
    cfg             = load_config()
    assets_dir      = cfg["assets_dir"]
    projects_dir    = cfg["projects_dir"]
    characters_data = load_characters(assets_dir)

    project_path  = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("Missing project_manifest.json")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    global_visual_context = manifest["script"].get("visual_context", "")
    scenes = manifest["scenes"]

    all_characters = list({
        s["character"] for s in scenes
        if s["type"] == "dialogue" and not s.get("is_narrator", False)
    })
    char_descriptions = "\n".join(
        f"{c}: {characters_data.get(c, {}).get('description', '')}"
        for c in all_characters
    )

    return (
        cfg, assets_dir, projects_dir, characters_data,
        project_path, manifest_path, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    )


# =========================
# TEST FUNCTION
# =========================
def test_image_generation(project_name: str, output_path: str = "test_image_local.png"):
    """Generate a single narrator image for quick sanity-check."""
    (
        cfg, assets_dir, _, characters_data,
        _, _, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    ) = _setup(project_name)

    first_narrator = next(
        (s for s in scenes if s.get("is_narrator") and s.get("visual_context")), None
    )
    scene_vc = first_narrator["visual_context"] if first_narrator else ""

    t5xxl      = build_narrator_prompt(global_visual_context, scene_vc, char_descriptions, all_characters)
    lora_names = build_lora_list("", all_characters, characters_data, cfg["style_lora"])

    logger.info("Test generation (narrator, ComfyUI local)")
    image_bytes = generate_image_local(cfg["clip_l_tag"], t5xxl, lora_names, cfg)

    out = Path(output_path)
    with open(out, "wb") as f:
        f.write(image_bytes)
    extend_image_vertical(out, cfg["extend_pad"])
    logger.info(f"Test image saved: {out}")


# =========================
# MAIN
# =========================
def generate_images(project_name: str, format_type: str = "shorts"):
    (
        cfg, assets_dir, projects_dir, characters_data,
        project_path, manifest_path, manifest,
        global_visual_context, scenes, all_characters, char_descriptions,
    ) = _setup(project_name)

    images_dir = project_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # ---- NARRATOR / ESTABLISHING IMAGE ----
    narrator_path = images_dir / "scene_narrator.png"

    if not narrator_path.exists():
        logger.info("Generating narrator image...")

        first_narrator = next(
            (s for s in scenes if s.get("is_narrator") and s.get("visual_context")), None
        )
        scene_vc   = first_narrator["visual_context"] if first_narrator else ""
        t5xxl      = build_narrator_prompt(global_visual_context, scene_vc, char_descriptions, all_characters)
        lora_names = build_lora_list("", all_characters, characters_data, cfg["style_lora"])

        image_bytes = generate_image_local(cfg["clip_l_tag"], t5xxl, lora_names, cfg)

        with open(narrator_path, "wb") as f:
            f.write(image_bytes)
        extend_image_vertical(narrator_path, cfg["extend_pad"])
        logger.info("Narrator image saved.")
    else:
        logger.info("Narrator image already exists, skipping.")

    manifest["narrator_image"] = to_relative(narrator_path, project_path)

    # ---- SCENE IMAGES ----
    for scene in scenes:
        if scene["type"] != "dialogue":
            continue

        if scene.get("is_narrator", False):
            scene["image"] = manifest["narrator_image"]
            continue

        scene_id    = scene["id"]
        speaker     = scene["character"]
        text        = scene["text"]
        scene_vc    = scene.get("visual_context", "")
        output_path = images_dir / f"{scene_id}.png"

        if output_path.exists():
            logger.info(f"Skipping existing {scene_id}")
            scene["image"] = to_relative(output_path, project_path)
            continue

        logger.info(f"Generating {scene_id} ({speaker}): {scene_vc[:80]}...")

        others          = [c for c in all_characters if c != speaker]
        selected_others = random.sample(others, min(2, len(others)))

        t5xxl      = build_scene_prompt(
            global_visual_context, scene_vc, char_descriptions,
            speaker, text, selected_others,
        )
        lora_names = build_lora_list(speaker, selected_others, characters_data, cfg["style_lora"])

        logger.debug(f"LoRA chain: {lora_names}")
        image_bytes = generate_image_local(cfg["clip_l_tag"], t5xxl, lora_names, cfg)

        with open(output_path, "wb") as f:
            f.write(image_bytes)
        extend_image_vertical(output_path, cfg["extend_pad"])
        scene["image"] = to_relative(output_path, project_path)

    # ---- SAVE MANIFEST ----
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info("Local image generation completed.")


# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Generate images for project (local ComfyUI)")
    parser.add_argument("project_name")
    parser.add_argument("--format", choices=["shorts", "landscape"], default="shorts")
    parser.add_argument("--test", action="store_true", help="Generate a single test image and exit")
    parser.add_argument("--test-output", default="test_image_local.png")
    args = parser.parse_args()

    if args.test:
        test_image_generation(args.project_name, args.test_output)
    else:
        generate_images(args.project_name, args.format)

if __name__ == "__main__":
    generate_images("office_convo_4")
