"""
mcp_server.py
=============
MCP bridge between a Claude chat session (Claude Code / Claude Desktop) and the
language-learning video pipeline (the active workspace's language).

This is the **brief seam**: you refine a video idea in chat, and Claude calls
these tools to (1) create the project from that refined brief and (2) write its
script. Through the MCP the script is written by Claude itself, locally, with no
OpenAI call: get_script_instructions returns the exact instructions GPT would
get, and submit_script hands Claude's finished script to the same scene-building
code the GPT path uses (create_script.create_script(script=...)). The web UI
keeps using OpenAI. generate_script (GPT) stays available as an explicit opt-in.

Tools
-----
Discovery (so Claude can fill a valid brief):
  list_project_types   — available video types + which need a word list
  list_characters      — castable characters + descriptions
  list_locations       — location keys + descriptions

Action:
  create_project       — create the project folder + manifest from the brief
  get_script_instructions — the type's script instructions + JSON format (no API call)
  submit_script        — build the scenes from a script Claude wrote (no API call)
  generate_script      — OPT-IN: let GPT write the script instead (OpenAI call)
  get_project_status   — inspect a project's current pipeline state
  set_podcast_shorts   — (podcast type) save hand-chosen Short ranges / titles (no API call)
  pick_podcast_shorts  — OPT-IN (podcast type): let GPT re-pick the Shorts (OpenAI call)

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
from platform_audio import any_variant_exists

mcp = MCPServer(
    name="language-video-pipeline",
    instructions=(
        "Tools to turn a refined language-learning-video idea into a pipeline "
        "project in the ACTIVE WORKSPACE (one per language/channel — call get_workspace "
        "to see which language is being taught; write every learner-facing line in it). "
        "Typical flow: call list_project_types / list_characters to see "
        "valid options, then create_project with the refined brief (project name, "
        "type, level, scene description, optional learning points, optional visual "
        "guidelines).\n"
        "\n"
        "SCRIPT WRITING — DO IT YOURSELF, LOCALLY (the default when working through this MCP):\n"
        "1. get_script_instructions(project_name, char_a, char_b) returns the exact instructions "
        "and JSON output format the pipeline would give GPT, plus any extra fields the type needs.\n"
        "2. YOU write the script following them (title, tags, insights, dialog, ... — same JSON).\n"
        "3. submit_script(project_name, char_a, char_b, script) builds the scenes. No OpenAI call.\n"
        "Only use generate_script (GPT writes the script) or pick_podcast_shorts when the user "
        "explicitly asks for GPT/OpenAI. Both cost OpenAI credits.\n"
        "\n"
        "By default no pre-made location is used — the scene's environment and the "
        "characters' attire come from the scene description and the visual_guidelines "
        "field. list_locations + the location_key parameter remain available only "
        "as an opt-in override to reuse a hand-made location.\n"
        "\n"
        "AUTHORING CONVENTIONS (bake these into context + visual_guidelines):\n"
        "- Natural, native target language: the example sentences must sound like a real speaker "
        "in that situation, not a textbook or a literal translation. Natural word order, real "
        "politeness (German e.g. 'Könnten Sie bitte ...?'), factually correct (e.g. German school "
        "grades are 1–6, real prices/units/procedures), and phrased from the point of view of whichever "
        "character is speaking (a customer must not utter the provider's line).\n"
        "- Visuals must depict the SENTENCE, not just the word, so the image reinforces meaning. "
        "The speaker is the one performing the action.\n"
        "- Only depict characters the scene actually provides: each illustration is drawn ONLY "
        "from the reference art of the characters that scene includes. So a scene_visual must "
        "never name, describe or imply a character who is not present in that scene — including "
        "the other speaker merely reacting, listening, watching or nodding. If the other "
        "character should be in frame, mark the line so BOTH characters are present (two-person "
        "types: scene_characters=\"both\"; multi-character types: list them in present_characters); "
        "otherwise keep the visual to the single speaker only. A mentioned-but-absent character "
        "renders with the wrong face and clothes.\n"
        "- Dress the actor for the job: when a word/scene needs role clothing or equipment "
        "(hairdresser's apron, mechanic's overall, builder's hard hat + hi-vis vest, courier "
        "uniform, chef's jacket...), the visual_guidelines / scene description must say the "
        "SPEAKING character is wearing that gear and holding the trade's tools — even as a "
        "costume outside their usual role. The render honours a costume only when the text "
        "names it. Avoid relying on readable text/labels on props (the illustrator can't draw "
        "words).\n"
        "\n"
        "PODCAST TYPE (project_type_key=\"podcast\", the channel's podcast):\n"
        "- A horizontal episode where char_a and char_b are the two hosts talking in a fixed podcast "
        "studio. context = the episode topic; learning_points = what the episode must teach. "
        "visual_guidelines (optional) only art-direct the EXAMPLE cut-aways, never the studio.\n"
        "- The WHOLE episode is in the target language: the hosts explain, react and joke in it, with no "
        "English sentences or translations.\n"
        "- Each line is 'studio' (shared studio image, cached per host pair in "
        "assets/studios/podcast — free after the first episode) or 'example' (the hosts act out a "
        "real situation, which gets its own illustration; each new example_id = one paid image). "
        "Default length 30-40 lines.\n"
        "- Put the best moments for vertical Shorts in the script as podcast_shorts (dialog-line "
        "ranges) or set them later with set_podcast_shorts; they are rendered in the web UI's "
        "'Build Shorts' step."
    ),
)


# =============================================================================
# Discovery tools
# =============================================================================

@mcp.tool()
def get_workspace() -> dict:
    """The active workspace: the language being taught and the channel it is for.

    Every learner-facing line (dialog, narration, titles) must be written in
    `language`; scene_visual descriptions stay in English. Switch workspaces in the
    web UI (Settings → Workspaces).
    """
    cfg = load_config()
    return {
        "workspace":       cfg["workspace"],
        "name":            cfg["workspace_name"],
        "language":        cfg["language_name"],
        "language_native": cfg["language_native"],
        "language_code":   cfg["language_code"],
        "channel":         cfg["channel_name"],
        "default_level":   cfg["level"],
    }


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
    call get_script_instructions + submit_script afterwards for that.

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
        "next_step": "call get_script_instructions with char_a and char_b, write the script "
                     "yourself, then submit_script (no location_key needed — the look comes "
                     "from visual_guidelines)",
    }


def _script_summary(project_name: str, manifest: dict, source: str) -> dict:
    """What a chat needs after a script step: title, counts, podcast Shorts."""
    scenes = manifest.get("scenes", [])
    dialog_scenes = [s for s in scenes if (s.get("description") or "").startswith("dialog_")]
    vi = manifest.get("video_info", {})
    gen = manifest.get("generation_config", {})
    extra = {}
    if "podcast" in manifest or any("_podcast_setting" in s for s in scenes):
        examples = [s for s in scenes if s.get("_podcast_setting") == "example"]
        extra = {
            "studio_lines":  sum(1 for s in scenes if s.get("_podcast_setting") == "studio"),
            "example_lines": len(examples),
            "example_images": sum(1 for s in examples if s.get("image")),
            "podcast_shorts": _shorts_summary(manifest),
        }
    return {
        "status": "script_generated",
        "script_source": source,
        "project_name": project_name,
        "title": vi.get("title"),
        "level": gen.get("level"),
        "location_key": gen.get("location_key"),
        "cast": gen.get("characters", []),
        "dialog_lines": len(dialog_scenes),
        "total_scenes": len(scenes),
        "next_step": "review, then run audio/images from the web UI or pipeline",
        **extra,
    }


@mcp.tool()
def get_script_instructions(
    project_name: str,
    char_a: str,
    char_b: str,
    location_key: str = "",
    project_type_key: str = "",
    dialog_count: int = 0,
    words: list[str] | None = None,
    characters: list[str] | None = None,
) -> dict:
    """Get the script instructions for a project, to write the script YOURSELF. No API call.

    Returns the exact prompt the pipeline would send to GPT for this project's type,
    brief, level and cast — including the required JSON output structure — plus
    extra_fields the type needs besides the dialog (e.g. "repetitions" for shadowing
    types, "podcast_shorts" for the podcast). Follow it, then pass the finished JSON
    object to submit_script with the same arguments.

    Parameters are the same as submit_script / generate_script.
    """
    from create_script import script_prompt

    if not char_a.strip() or not char_b.strip():
        raise ValueError("char_a and char_b are required")
    out = script_prompt(
        project_name.strip(), char_a.strip(), char_b.strip(),
        (location_key or "").strip() or None,
        project_type_key=(project_type_key or "").strip() or None,
        words=words or None,
        dialog_count=dialog_count or None,
        characters=[c for c in (characters or []) if c] or None,
    )
    out["language"] = load_config()["language_name"]
    out["next_step"] = ("write the script as ONE JSON object following the prompt (and extra_fields), "
                        "then call submit_script with it")
    return out


@mcp.tool()
def submit_script(
    project_name: str,
    char_a: str,
    char_b: str,
    script: dict,
    location_key: str = "",
    project_type_key: str = "",
    words: list[str] | None = None,
    characters: list[str] | None = None,
) -> dict:
    """Build the project's scenes from a script YOU wrote. No OpenAI call.

    script: the JSON object described by get_script_instructions — at least
    "title", "tags", "insights" and a non-empty "dialog" list whose items follow the
    type's format ("text", "speaker", "scene_visual", "scene_characters", ... ; podcast
    lines also "setting" and "example_id"). Every speaker must be in the cast.
    Shadowing types also need "repetitions" (3 dialog texts); the podcast may include
    "podcast_shorts" ([{start, end, title, description}], 0-based inclusive dialog
    indices) — otherwise set them later with set_podcast_shorts.

    The scenes, image prompts, voices and pauses are built exactly as for a GPT script,
    and script.txt is written. Returns the same summary as generate_script.
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
        characters=[c for c in (characters or []) if c] or None,
        script=script,
    )
    return _script_summary(project_name.strip(), manifest, "claude (local, no OpenAI call)")


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
    """OPT-IN: let GPT write the script instead of writing it yourself.

    Only use this when the user explicitly asks for GPT/OpenAI — the default through
    this MCP is get_script_instructions + submit_script (no API cost).
    Expands the project's brief into a full title, tags, description, dialog and
    scene list by calling GPT, then writes the scenes back into the manifest.
    This calls the OpenAI API (script + grammar evaluation, and for the podcast the
    Shorts pick) and can take a while for long dialogs.

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

    return _script_summary(project_name.strip(), manifest, "gpt (OpenAI)")


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
        "has_video": any_variant_exists(cfg["projects_dir"] / project_name.strip()
                                        / f"final_{project_name.strip()}.mp4"),
        **({"podcast_shorts": _shorts_summary(m)} if "podcast" in m else {}),
    }


# =============================================================================
# Podcast tools
# =============================================================================

def _shorts_summary(manifest: dict) -> list[dict]:
    """The chosen Shorts with the first/last line text so a chat can judge them."""
    lines = {s["_dialog_index"]: f"{(s.get('characters') or ['?'])[0]}: {s.get('subtitle_text') or ''}"
             for s in manifest.get("scenes", []) if "_dialog_index" in s}
    out = []
    for n, sh in enumerate((manifest.get("podcast") or {}).get("shorts") or [], start=1):
        out.append({
            "short": n, "start": sh.get("start"), "end": sh.get("end"),
            "title": sh.get("title"), "why": sh.get("why"),
            "first_line": lines.get(sh.get("start")), "last_line": lines.get(sh.get("end")),
            "file": sh.get("file"),
        })
    return out


@mcp.tool()
def pick_podcast_shorts(project_name: str, count: int = 0) -> dict:
    """OPT-IN (podcast type): ask GPT to re-pick the best moments for vertical Shorts.

    Only when the user explicitly asks for GPT — otherwise choose the moments yourself
    and save them with set_podcast_shorts (no API cost).

    Replaces the current list. Calls the OpenAI API once (short request).
    count = how many Shorts (0 = config.ini [podcast] shorts_count).
    Returns the new Shorts (dialog-line ranges, titles, first/last line).
    """
    import json
    from podcast import select_shorts
    select_shorts(project_name.strip(), count or None)
    cfg = load_config()
    mp = cfg["projects_dir"] / project_name.strip() / "project_manifest.json"
    return {"podcast_shorts": _shorts_summary(json.loads(mp.read_text(encoding="utf-8")))}


@mcp.tool()
def set_podcast_shorts(project_name: str, shorts: list[dict]) -> dict:
    """(podcast type) Save hand-chosen Shorts. No API calls.

    shorts: [{"start": int, "end": int, "title": str, "description": str}] — start/end are
    0-based dialog line indices (inclusive), as returned in podcast_shorts. Overlapping ranges
    are dropped; the list is stored sorted by start. Descriptions may contain {LINK}, which
    is replaced by config.ini [podcast] full_episode_url in shorts.txt.
    """
    import json
    from podcast import save_shorts
    save_shorts(project_name.strip(), shorts)
    cfg = load_config()
    mp = cfg["projects_dir"] / project_name.strip() / "project_manifest.json"
    return {"podcast_shorts": _shorts_summary(json.loads(mp.read_text(encoding="utf-8")))}


if __name__ == "__main__":
    mcp.run("stdio")
