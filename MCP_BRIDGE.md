# Claude ↔ Pipeline MCP Bridge

Lets you refine a video idea in a Claude chat (Claude Code / Claude Desktop) and
have Claude drive the pipeline directly — no copy-pasting into the web UI.

This is the **brief seam**: Claude fills in the project brief and kicks off the
existing GPT script step ([`create_script.py`](create_script.py)). All heavy
generation still runs through the normal pipeline.

## Tools exposed

| Tool | What it does |
|------|--------------|
| `list_project_types` | Video types + which need a word list |
| `list_characters` | Castable speakers + descriptions |
| `list_locations` | Location keys + descriptions |
| `create_project` | Create the project folder + manifest from the brief |
| `generate_script` | Run the GPT script step (title, dialog, scenes) |
| `get_project_status` | Inspect a project's pipeline state |

Typical flow Claude follows: `list_*` to see valid options → `create_project`
with the refined brief → `generate_script` with `char_a` / `char_b` / a
`location_key`.

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

`generate_script` calls the OpenAI API, so `OPENAI_API_KEY` must be set in `.env`
(the pipeline already loads it). The MCP SDK is installed with:

```bash
python -m pip install "mcp[cli]"
```

## Notes

- The server `chdir`s to its own directory on startup, so relative pipeline
  paths (`config.ini`, `projects/`, `assets/`) resolve regardless of launch cwd.
- `generate_script` mirrors the web route `POST /projects/<name>/run/script`
  exactly, so behavior matches the UI.
- Audio, images and final assembly are intentionally **not** exposed — run those
  from the web UI once the script looks right.
