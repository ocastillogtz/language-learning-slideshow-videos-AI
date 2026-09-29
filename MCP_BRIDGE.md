# Claude ↔ Pipeline MCP Bridge

Lets you refine a video idea in a Claude chat (Claude Code / Claude Desktop) and
have Claude drive the pipeline directly — no copy-pasting into the web UI.

This is the **brief seam**: Claude fills in the project brief and **writes the
script itself, locally** (no OpenAI call). The scenes are then built by the normal
script step ([`create_script.py`](create_script.py)), exactly as for a GPT script.
The web UI keeps using OpenAI.

## Tools exposed

| Tool | What it does |
|------|--------------|
| `list_project_types` | Video types + which need a word list |
| `list_characters` | Castable speakers + descriptions |
| `list_locations` | Location keys + descriptions |
| `create_project` | Create the project folder + manifest from the brief |
| `get_script_instructions` | Script instructions + JSON format for this project (no API call) |
| `submit_script` | Build the scenes from the script Claude wrote (no API call) |
| `generate_script` | **Opt-in:** GPT writes the script instead (OpenAI call) |
| `get_project_status` | Inspect a project's pipeline state (podcast: also its Shorts) |
| `set_podcast_shorts` | Podcast: save hand-chosen Short ranges and titles (no API call) |
| `pick_podcast_shorts` | **Opt-in**, podcast: GPT re-picks the moments for the vertical Shorts |

Typical flow Claude follows: `list_*` to see valid options → `create_project`
with the refined brief → `get_script_instructions` with `char_a` / `char_b` →
Claude writes the script → `submit_script`. `generate_script` and
`pick_podcast_shorts` are only used when you explicitly ask for GPT.

**Who writes the script.** Through the MCP, Claude writes the script itself, locally, with no OpenAI call:
1. `get_script_instructions` returns the exact prompt the pipeline would send to GPT for this project (type, brief, level, cast, and the JSON output format), plus any extra fields the type needs: `repetitions` for shadowing types, `podcast_shorts` for the podcast.
2. Claude writes the script as that JSON object.
3. `submit_script` passes it to `create_script.create_script(script=...)`. That builds the scenes, image prompts, voices, pauses and `script.txt` with the same code as the GPT path.

With a supplied script, the pipeline skips every OpenAI call of the script step: the script itself, the grammar auto-evaluation, the shadowing repetition pick and the podcast Shorts pick. The manifest records `generation_config.script_source` = `supplied` (or `gpt`). The script is checked first: every speaker must be in the cast, `title`/`tags`/`insights` are required, and shadowing types need `repetitions`.

The **web UI keeps using OpenAI**. Through the MCP, `generate_script` and `pick_podcast_shorts` remain as an explicit opt-in, used only when you ask for GPT.

**Podcast** (`project_type_key="podcast"`): `char_a` / `char_b` are the two hosts,
`context` is the episode topic, and the whole episode is in German. Claude can put the
Shorts in the script (`podcast_shorts`, dialog-line ranges) or set them later with
`set_podcast_shorts`, then render them in the web UI's **Build Shorts** step.

## Registration

The server runs under the **Anaconda base** interpreter (same env as the
pipeline: `C:\Users\Omar\anaconda3\python.exe`), not the repo `.venv`.

### Claude Code

Already wired via [`.mcp.json`](.mcp.json) in the project root. Open Claude Code
in this directory and approve the server when prompted. Verify with `/mcp`.

### Claude Desktop

Add this to `claude_desktop_config.json`
(`%APPDATA%\Claude\claude_desktop_config.json`) and restart the app:

```json
{
  "mcpServers": {
    "german-video-pipeline": {
      "command": "C:\\Users\\Omar\\anaconda3\\python.exe",
      "args": ["C:\\Users\\Omar\\Documents\\germanLearningVidsAIPowered\\mcp_server.py"]
    }
  }
}
```

## Requirements

Only the opt-in `generate_script` / `pick_podcast_shorts` call the OpenAI API, so
`OPENAI_API_KEY` must be set in `.env` for those (the pipeline already loads it).
The local path (`get_script_instructions` + `submit_script`) needs no API key. The MCP SDK is installed with:

```bash
python -m pip install "mcp[cli]"
```

## Notes

- The server `chdir`s to its own directory on startup, so relative pipeline
  paths (`config.ini`, `projects/`, `assets/`) resolve regardless of launch cwd.
- `generate_script` mirrors the web route `POST /projects/<name>/run/script`
  exactly, so behavior matches the UI. `submit_script` runs the same function with
  `script=...`, so the scenes are built identically.
- After editing pipeline code, restart the MCP server (reconnect it in Claude):
  it keeps the modules it loaded at startup.
- Audio, images and final assembly are intentionally **not** exposed — run those
  from the web UI once the script looks right.
