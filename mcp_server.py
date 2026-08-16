"""
mcp_server.py
=============
MCP bridge between a Claude chat session (Claude Code / Claude Desktop) and the
German-learning video pipeline.

This is the **brief seam**: you refine a video idea in chat, and Claude calls
these tools to (1) create the project from that refined brief and (2) kick off
the existing GPT script step. The heavy creative generation still runs through
create_script.py — these tools just let Claude drive it directly instead of you
copy-pasting into the web UI.

Tools
-----
Discovery (so Claude can fill a valid brief):
  list_project_types   — available video types + which need a word list
  list_characters      — castable characters + descriptions
  list_locations       — location keys + descriptions

Action:
  create_project       — create the project folder + manifest from the brief
  generate_script      — run the GPT script step (title, dialog, scenes)
  get_project_status   — inspect a project's current pipeline state

The server chdir's to its own directory on startup so the pipeline's relative
config paths (config.ini, projects/, assets/) resolve no matter how the MCP
client launches it.

Run standalone (stdio):  python mcp_server.py
Registered via .mcp.json for Claude Code — see MCP_BRIDGE.md.
"""

import os
from pathlib import Path

# The pipeline reads config.ini and resolves projects/ + assets/ relative to the
# current working directory (see utils_config.load_config). MCP clients launch
# the server from an arbitrary cwd, so pin it to this file's directory first.
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

from mcp.server.mcpserver import MCPServer

from utils_config import (
    load_config,
    load_project_types,
    load_new_characters,
    load_new_locations,
    get_new_locations_flat,
)

mcp = MCPServer(
    name="german-video-pipeline",
    instructions=(
        "Tools to turn a refined German-learning-video idea into a pipeline "
        "project. Typical flow: call list_project_types / list_characters to see "
        "valid options, then create_project with the refined brief (project name, "
        "type, level, scene description, optional learning points, optional visual "
        "guidelines), then generate_script to produce the dialog and scenes. "
        "By default no pre-made location is used — the scene's environment and the "
        "characters' attire come from the scene description and the visual_guidelines "
        "field. list_locations + generate_script's location_key remain available only "
        "as an opt-in override to reuse a hand-made location. generate_script calls "
        "GPT and may take a while.\n"
        "\n"
        "AUTHORING CONVENTIONS (bake these into context + visual_guidelines):\n"
        "- Natural, native German: the example sentences must sound like a real speaker in "
        "that situation, not a textbook or a literal translation. Natural word order, real "
        "politeness ('Könnten Sie bitte ...?'), factually correct (German school grades are "
        "1–6, real prices/units/procedures), and phrased from the point of view of whichever "
        "character is speaking (a customer must not utter the provider's line).\n"
        "- Visuals must depict the SENTENCE, not just the word, so the image reinforces meaning. "
        "The speaker is the one performing the action.\n"
        "- Dress the actor for the job: when a word/scene needs role clothing or equipment "
        "(hairdresser's apron, mechanic's overall, builder's hard hat + hi-vis vest, courier "
        "uniform, chef's jacket...), the visual_guidelines / scene description must say the "
        "SPEAKING character is wearing that gear and holding the trade's tools — even as a "
        "costume outside their usual role. The render honours a costume only when the text "
        "names it. Avoid relying on readable text/labels on props (the illustrator can't draw "
        "words)."
    ),
)


# =============================================================================
# Discovery tools
# =============================================================================

def _resolve_type(project_types: dict, key: str) -> dict:
    """Merge a project type over its base_type, mirroring create_project.py."""
    pt = project_types[key]
    base_key = pt.get("base_type")
    if base_key and base_key in project_types:
        pt = {**project_types[base_key], **pt}
    return pt


@mcp.tool()
def list_project_types() -> list[dict]:
    """List the available video project types.

    Returns one entry per type with:
      key                    — pass this as project_type_key
      description            — what the type produces
      default_dialog_count   — suggested dialog length (e.g. "4-6")
      format                 — "vertical" or "horizontal"
      supports_multi_character — true if more than 2 speakers are allowed
      is_word_learning       — true if learning_points is a comma-separated word
                               list (create_project parses it into words)
    """
    cfg = load_config()
    types = load_project_types(cfg["assets_dir"])
    out = []
    for key in sorted(types):
        eff = _resolve_type(types, key)
        base = eff.get("base_type") or eff.get("name", key)
        out.append({
            "key": key,
            "description": types[key].get("self_description") or eff.get("self_description"),
            "default_dialog_count": eff.get("default_dialog_count"),
            "format": eff.get("format", "vertical"),
            "supports_multi_character": bool(eff.get("supports_multi_character")),
            "is_word_learning": base == "word_learning",
        })
    return out


@mcp.tool()
def list_characters() -> list[dict]:
    """List characters that can be cast as speakers.

    Returns name + a short description for each. Use the `name` values for
    char_a / char_b (and the optional `characters` cast) in generate_script.
    """
    cfg = load_config()
    chars = load_new_characters(cfg["assets_dir"])
    out = []
    for name, c in chars.items():
        fixed = (c.get("fixed_description") or "").strip()
        var = (c.get("variable_description") or "").strip()
        desc = " ".join(p for p in (fixed, var) if p) or None
        out.append({"name": name, "description": desc})
    return out


@mcp.tool()
def list_locations() -> list[dict]:
    """List location keys usable as location_key in generate_script.

    Includes top-level locations and their sub-locations, each with a short
    description and how many characters the scene art is built for.
    """
    cfg = load_config()
    flat = get_new_locations_flat(cfg["assets_dir"])
    top = load_new_locations(cfg["assets_dir"])
    top_keys = set(top.keys())
    out = []
    for key in sorted(flat):
        loc = flat[key]
        out.append({
            "key": key,
            "description": (loc.get("description") or "").strip() or None,
            "characters_amount": loc.get("characters_amount"),
            "is_sub_location": key not in top_keys,
        })
    return out


# =============================================================================
# Action tools
# =============================================================================

@mcp.tool()
def create_project(
    project_name: str,
    project_type_key: str,
    context: str,
    learning_points: str = "",
    level: str = "",
    visual_guidelines: str = "",
) -> dict:
    """Create a new video project folder + manifest from a refined brief.

    This is step 1 of the brief seam. It does NOT generate any dialog yet —
    call generate_script afterwards for that.

    Parameters
    ----------
    project_name      : Folder name (spaces are converted to underscores).
    project_type_key  : A key from list_project_types (e.g. "shadowing",
                        "story", "word_learning").
    context           : The refined scene description / scenario.
    learning_points   : Learning objectives. For word_learning types this must
                        be a comma-separated word list.
    level             : Target CEFR level (A1-C2). Empty = pipeline default.
    visual_guidelines : Optional art-direction brief applied to every scene —
                        the setting/environment, the characters' clothing and
                        props, and the mood/style. This is the default way to
                        control the look now: with no location_key on
                        generate_script, the images are driven entirely by this
                        field plus the scene description, so you no longer need a
                        pre-made location for a custom environment or outfit.
                        For job/role videos, name the professional's uniform and
                        tools here (e.g. mechanic's overall + wrench, courier
                        uniform + scanner) so the speaker is dressed for the job;
                        the render only wears a costume the text explicitly names.
                        Don't rely on readable text/labels on props.

    Returns the project name and manifest path on success.
    """
    from create_project import create_project as _create

    name = project_name.strip().replace(" ", "_")
    if not name or not context.strip():
        raise ValueError("project_name and context are required")

    path = _create(
        name,
        project_type_key.strip(),
        context.strip(),
        learning_points.strip(),
        (level or "").strip() or None,
        (visual_guidelines or "").strip(),
    )
    return {
        "status": "created",
        "project_name": name,
        "manifest_path": str(path / "project_manifest.json"),
        "next_step": "call generate_script with char_a and char_b (no location_key "
                     "needed — the look comes from visual_guidelines)",
    }


@mcp.tool()
def generate_script(
    project_name: str,
    char_a: str,
    char_b: str,
    location_key: str = "",
    project_type_key: str = "",
    dialog_count: int = 0,
    words: list[str] | None = None,
    characters: list[str] | None = None,
) -> dict:
    """Run the GPT script step for an existing project (brief seam, step 2).

    Expands the project's brief into a full title, tags, description, dialog and
    scene list by calling GPT, then writes the scenes back into the manifest.
    This calls the OpenAI API and can take a while for long dialogs.

    Parameters
    ----------
    project_name     : Existing project (created via create_project).
    char_a, char_b   : Two speaker names from list_characters (both required).
    location_key     : Empty (default) = do NOT use a pre-made location; the
                       environment and attire come from the scene description and
                       the project's visual_guidelines. Pass a key from
                       list_locations only to opt into reusing a hand-made
                       location (its description + reference art).
    project_type_key : Override the type stored on the manifest. Empty = keep it.
    dialog_count     : Force a specific number of dialog lines. 0 = type default.
    words            : Word list for word_learning types (overrides the brief).
    characters       : Extra speakers for multi-character types (beyond a/b).

    Returns a summary of the generated script (title, scene/dialog counts).
    """
    from create_script import create_script

    if not char_a.strip() or not char_b.strip():
        raise ValueError("char_a and char_b are required")

    manifest = create_script(
        project_name.strip(),
        char_a.strip(),
        char_b.strip(),
        (location_key or "").strip() or None,
        project_type_key=(project_type_key or "").strip() or None,
        words=words or None,
        dialog_count=dialog_count or None,
        characters=[c for c in (characters or []) if c] or None,
    )

    scenes = manifest.get("scenes", [])
    dialog_scenes = [s for s in scenes if s.get("type") == "dialog"]
    vi = manifest.get("video_info", {})
    gen = manifest.get("generation_config", {})
    return {
        "status": "script_generated",
        "project_name": project_name.strip(),
        "title": vi.get("title"),
        "level": gen.get("level"),
        "location_key": gen.get("location_key"),
        "cast": gen.get("characters", []),
        "dialog_lines": len(dialog_scenes),
        "total_scenes": len(scenes),
        "next_step": "review, then run audio/images from the web UI or pipeline",
    }


@mcp.tool()
def get_project_status(project_name: str) -> dict:
    """Report a project's current pipeline state from its manifest.

    Returns title, type, level, location, cast and which stages have run
    (script / audio / images / final video). Use to confirm what exists before
    or after generate_script.
    """
    import json

    cfg = load_config()
    mp = cfg["projects_dir"] / project_name.strip() / "project_manifest.json"
    if not mp.exists():
        raise FileNotFoundError(f"Project '{project_name}' not found")

    with open(mp, encoding="utf-8") as f:
        m = json.load(f)

    meta = m.get("project_metadata", {})
    vi = m.get("video_info", {})
    gen = m.get("generation_config", {})
    scenes = m.get("scenes", [])

    tts = [s for s in scenes
           if isinstance(s.get("audio"), dict) and s["audio"].get("type") == "tts"]
    imgs = [s for s in scenes
            if isinstance(s.get("image"), dict) and s["image"].get("file_path")]

    return {
        "project_name": project_name.strip(),
        "project_type_key": meta.get("project_type_key"),
        "title": vi.get("title"),
        "level": gen.get("level"),
        "location_key": gen.get("location_key"),
        "cast": gen.get("characters", []),
        "scene_count": len(scenes),
        "has_script": bool(tts),
        "has_audio": any(s["audio"].get("file_path") for s in tts),
        "has_images": bool(imgs),
        "has_video": (cfg["projects_dir"] / project_name.strip()
                      / f"final_{project_name.strip()}.mp4").exists(),
    }


if __name__ == "__main__":
    mcp.run("stdio")
