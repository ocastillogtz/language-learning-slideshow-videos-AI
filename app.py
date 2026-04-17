"""
app.py — Project Overview & Re-generation Server
=================================================

Run:
    pip install flask
    python app.py

Open: http://localhost:5000

API surface
-----------
GET  /api/projects
GET  /api/projects/<name>
GET  /api/projects/<name>/asset/<path>
GET  /api/projects/<name>/dialog/<index>/image
GET  /api/projects/<name>/dialog/<index>/audio
GET  /api/projects/<name>/narration/image
GET  /api/projects/<name>/narration/audio

PATCH /api/projects/<name>/dialog/<index>/prompt-image   body: {"prompt": "..."}
PATCH /api/projects/<name>/dialog/<index>/prompt-audio   body: {"prompt": "..."}
PATCH /api/projects/<name>/narration/prompt-image        body: {"prompt": "..."}
PATCH /api/projects/<name>/narration/prompt-audio        body: {"prompt": "..."}

POST  /api/projects/<name>/dialog/<index>/regenerate-image
POST  /api/projects/<name>/dialog/<index>/regenerate-audio
POST  /api/projects/<name>/narration/regenerate-image
POST  /api/projects/<name>/narration/regenerate-audio
POST  /api/projects/<name>/repetition/<index>/regenerate-audio

POST  /api/projects/<name>/cost          body: {"step": "images", "amount": 0.12, "note": "..."}
"""

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort
from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")


# =========================
# MANIFEST HELPERS
# =========================
def _projects_dir() -> Path:
    return load_config()["projects_dir"]


def _project_path(name: str) -> Path:
    return _projects_dir() / name


def _manifest_path(name: str) -> Path:
    return _project_path(name) / "project_manifest.json"


def _read(name: str) -> dict:
    p = _manifest_path(name)
    if not p.exists():
        abort(404, f"Manifest not found: {name}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(name: str, manifest: dict) -> None:
    with open(_manifest_path(name), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def _dialog_item(manifest: dict, index: int) -> dict:
    items = manifest.get("conversation", {}).get("dialog", [])
    if index < 0 or index >= len(items):
        abort(404, f"Dialog index {index} out of range")
    return items[index]


def _narration(manifest: dict) -> dict:
    n = manifest.get("conversation", {}).get("narration")
    if not n:
        abort(404, "No narration in manifest")
    return n


def _file_exists(project_name: str, rel: str | None) -> bool:
    if not rel:
        return False
    return (_project_path(project_name) / rel).exists()


def _run(script: str, *args: str) -> tuple[bool, str, str]:
    """Run a pipeline script as subprocess. Returns (ok, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, script, *args],
        capture_output=True, text=True,
    )
    return result.returncode == 0, result.stdout, result.stderr


# =========================
# PROJECT LIST
# =========================
@app.route("/api/projects")
def list_projects():
    pd = _projects_dir()
    if not pd.exists():
        return jsonify([])
    projects = sorted(
        d.name for d in pd.iterdir()
        if d.is_dir() and (d / "project_manifest.json").exists()
    )
    return jsonify(projects)


# =========================
# PROJECT DETAIL
# =========================
@app.route("/api/projects/<name>")
def get_project(name: str):
    manifest = _read(name)
    pp       = _project_path(name)

    # Annotate narration
    nar = manifest.get("conversation", {}).get("narration") or {}
    nar["_image_exists"] = _file_exists(name, nar.get("image"))
    nar["_audio_exists"] = _file_exists(name, nar.get("audio-file"))

    # Annotate dialog items
    for i, item in enumerate(manifest.get("conversation", {}).get("dialog", [])):
        item["_index"]          = i
        item["_image_exists"]   = _file_exists(name, item.get("image"))
        item["_audio_exists"]   = _file_exists(name, item.get("audio-file"))

    # Annotate repetitions
    for i, rep in enumerate(manifest.get("repetitions", [])):
        rep["_index"]        = i
        rep["_audio_exists"] = _file_exists(name, rep.get("audio-file"))

    # Total cost
    history = manifest.get("cost_history", [])
    manifest["_total_cost"] = round(sum(e.get("amount", 0) for e in history), 4)

    return jsonify(manifest)


# =========================
# ASSET SERVING
# =========================
@app.route("/api/projects/<name>/asset/<path:rel>")
def serve_asset(name: str, rel: str):
    full = _project_path(name) / rel
    if not full.exists():
        abort(404)
    return send_file(str(full))


# Convenience shortcuts so the UI can reference images/audio directly
@app.route("/api/projects/<name>/dialog/<int:idx>/image")
def dialog_image(name: str, idx: int):
    item = _dialog_item(_read(name), idx)
    rel  = item.get("image")
    if not rel:
        abort(404, "No image assigned")
    return send_file(str(_project_path(name) / rel))


@app.route("/api/projects/<name>/dialog/<int:idx>/audio")
def dialog_audio(name: str, idx: int):
    item = _dialog_item(_read(name), idx)
    rel  = item.get("audio-file")
    if not rel:
        abort(404, "No audio assigned")
    return send_file(str(_project_path(name) / rel))


@app.route("/api/projects/<name>/dialog/<int:idx>/cutaway-image")
def dialog_cutaway(name: str, idx: int):
    item = _dialog_item(_read(name), idx)
    rel  = item.get("cutaway-image")
    if not rel:
        abort(404, "No cutaway image")
    return send_file(str(_project_path(name) / rel))


@app.route("/api/projects/<name>/narration/image")
def narration_image(name: str):
    nar = _narration(_read(name))
    rel = nar.get("image")
    if not rel:
        abort(404, "No narration image")
    return send_file(str(_project_path(name) / rel))


@app.route("/api/projects/<name>/narration/audio")
def narration_audio(name: str):
    nar = _narration(_read(name))
    rel = nar.get("audio-file")
    if not rel:
        abort(404, "No narration audio")
    return send_file(str(_project_path(name) / rel))


@app.route("/api/projects/<name>/repetition/<int:idx>/audio")
def repetition_audio(name: str, idx: int):
    reps = _read(name).get("repetitions", [])
    if idx < 0 or idx >= len(reps):
        abort(404)
    rel = reps[idx].get("audio-file")
    if not rel:
        abort(404, "No audio assigned")
    return send_file(str(_project_path(name) / rel))


# =========================
# PROMPT EDITING
# =========================
def _patch_prompt(name: str, field: str, key: str):
    """Generic helper: save an edited prompt string to manifest[field][key]."""
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    if not prompt:
        abort(400, "prompt field required")
    manifest = _read(name)

    parts = field.split(".")   # e.g. "conversation.narration" or "conversation.dialog.0"
    node = manifest
    for part in parts:
        if part.isdigit():
            node = node[int(part)]
        else:
            node = node[part]

    node[key] = prompt
    _write(name, manifest)
    return jsonify({"ok": True})


@app.route("/api/projects/<name>/dialog/<int:idx>/prompt-image", methods=["PATCH"])
def patch_dialog_prompt_image(name: str, idx: int):
    return _patch_prompt(name, f"conversation.dialog.{idx}", "prompt-image")


@app.route("/api/projects/<name>/dialog/<int:idx>/prompt-audio", methods=["PATCH"])
def patch_dialog_prompt_audio(name: str, idx: int):
    return _patch_prompt(name, f"conversation.dialog.{idx}", "prompt-audio")


@app.route("/api/projects/<name>/narration/prompt-image", methods=["PATCH"])
def patch_narration_prompt_image(name: str):
    return _patch_prompt(name, "conversation.narration", "prompt-image")


@app.route("/api/projects/<name>/narration/prompt-audio", methods=["PATCH"])
def patch_narration_prompt_audio(name: str):
    return _patch_prompt(name, "conversation.narration", "prompt-audio")


# =========================
# REGENERATION
# =========================
def _delete_file(project_name: str, rel: str | None) -> None:
    if rel:
        p = _project_path(project_name) / rel
        if p.exists():
            p.unlink()
            logger.info(f"Deleted: {p}")


@app.route("/api/projects/<name>/dialog/<int:idx>/regenerate-image", methods=["POST"])
def regen_dialog_image(name: str, idx: int):
    manifest = _read(name)
    item     = _dialog_item(manifest, idx)

    _delete_file(name, item.get("image"))
    item["image"] = None
    _write(name, manifest)

    ok, out, err = _run("create_images.py", name)
    if not ok:
        logger.error(f"create_images failed:\n{err}")
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "stdout": out})


@app.route("/api/projects/<name>/dialog/<int:idx>/regenerate-audio", methods=["POST"])
def regen_dialog_audio(name: str, idx: int):
    manifest = _read(name)
    item     = _dialog_item(manifest, idx)

    _delete_file(name, item.get("audio-file"))
    item["audio-file"]  = None
    item["duration-ms"] = None
    _write(name, manifest)

    ok, out, err = _run("create_audio.py", name)
    if not ok:
        logger.error(f"create_audio failed:\n{err}")
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "stdout": out})


@app.route("/api/projects/<name>/narration/regenerate-image", methods=["POST"])
def regen_narration_image(name: str):
    manifest = _read(name)
    nar      = _narration(manifest)

    _delete_file(name, nar.get("image"))
    nar["image"] = None
    _write(name, manifest)

    ok, out, err = _run("create_images.py", name)
    if not ok:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "stdout": out})


@app.route("/api/projects/<name>/narration/regenerate-audio", methods=["POST"])
def regen_narration_audio(name: str):
    manifest = _read(name)
    nar      = _narration(manifest)

    _delete_file(name, nar.get("audio-file"))
    nar["audio-file"]  = None
    nar["duration-ms"] = None
    _write(name, manifest)

    ok, out, err = _run("create_audio.py", name)
    if not ok:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "stdout": out})


@app.route("/api/projects/<name>/repetition/<int:idx>/regenerate-audio", methods=["POST"])
def regen_repetition_audio(name: str, idx: int):
    manifest = _read(name)
    reps     = manifest.get("repetitions", [])
    if idx < 0 or idx >= len(reps):
        abort(404)
    rep = reps[idx]

    _delete_file(name, rep.get("audio-file"))
    rep["audio-file"]  = None
    rep["duration-ms"] = None
    _write(name, manifest)

    ok, out, err = _run("create_audio.py", name)
    if not ok:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "stdout": out})


# =========================
# COST TRACKING
# =========================
@app.route("/api/projects/<name>/cost", methods=["POST"])
def add_cost(name: str):
    """
    Record a cost entry to manifest["cost_history"].
    Body: {"step": "images", "amount": 0.12, "note": "dialog_00 regen"}
    """
    body   = request.get_json(silent=True) or {}
    step   = body.get("step", "unknown")
    amount = float(body.get("amount", 0))
    note   = body.get("note", "")

    manifest = _read(name)
    if "cost_history" not in manifest:
        manifest["cost_history"] = []

    manifest["cost_history"].append({
        "ts":     datetime.now(timezone.utc).isoformat(),
        "step":   step,
        "amount": amount,
        "note":   note,
    })
    _write(name, manifest)

    total = round(sum(e["amount"] for e in manifest["cost_history"]), 4)
    return jsonify({"ok": True, "total": total})


# =========================
# PIPELINE RUNNER
# =========================
# Pipeline step definitions — order matters
PIPELINE_STEPS: list[dict] = [
    {"id": "script",   "label": "Generate script",  "script": "create_script.py",  "args": []},
    {"id": "audio",    "label": "Generate audio",   "script": "create_audio.py",   "args": []},
    {"id": "images",   "label": "Generate images",  "script": "create_images.py",  "args": []},
    {"id": "video",    "label": "Render clips",     "script": "create_video.py",   "args": []},
    {"id": "assemble", "label": "Assemble video",   "script": "assemble_video.py", "args": []},
    {"id": "upload",   "label": "Upload to YouTube","script": "upload_video.py",   "args": ["--project"]},
]


@app.route("/api/pipeline/steps")
def pipeline_steps():
    """Return the ordered list of pipeline steps."""
    return jsonify(PIPELINE_STEPS)


@app.route("/api/projects/<n>/pipeline/status")
def pipeline_status(name: str):
    """
    Return the completion status of each pipeline step for a project,
    inferred from what files exist on disk.
    """
    manifest = _read(name)
    pp       = _project_path(name)
    conv     = manifest.get("conversation", {})
    dialog   = conv.get("dialog", [])
    reps     = manifest.get("repetitions", [])

    def _any_exists(paths):
        return any(Path(p).exists() for p in paths if p)

    script_done   = bool(conv.get("narration", {}).get("text"))
    audio_done    = all(_file_exists(name, d.get("audio-file")) for d in dialog) and bool(dialog)
    images_done   = all(_file_exists(name, d.get("image")) for d in dialog) and bool(dialog)
    video_done    = all((pp/"videos"/f"{s['id']}.mp4").exists()
                        for s in manifest.get("scenes", []))
    assemble_done = (pp / f"final_{name}.mp4").exists()
    upload_done   = bool(manifest.get("youtube_id"))

    return jsonify({
        "script":   {"done": script_done},
        "audio":    {"done": audio_done},
        "images":   {"done": images_done},
        "video":    {"done": video_done},
        "assemble": {"done": assemble_done},
        "upload":   {"done": upload_done,
                     "youtube_id": manifest.get("youtube_id")},
    })


@app.route("/api/projects/<n>/pipeline/run", methods=["POST"])
def run_pipeline(name: str):
    """
    Run pipeline steps for a project, streaming log lines via SSE.

    Body JSON:
    {
      "steps":     ["script","audio","images","video","assemble","upload"],
      "stop_after": "images",    // optional — pause after this step
      "extra_args": {            // optional per-step extra CLI args
          "assemble": ["--branding","intro"],
          "upload":   ["--privacy","public"]
      }
    }

    Response: text/event-stream
      data: {"type":"step_start","step":"audio","label":"Generate audio"}
      data: {"type":"log","step":"audio","line":"..."}
      data: {"type":"step_done","step":"audio","ok":true}
      data: {"type":"pipeline_done","stopped_at":"images"}
    """
    import threading, queue as Q

    body       = request.get_json(silent=True) or {}
    steps_req  = body.get("steps", [s["id"] for s in PIPELINE_STEPS])
    stop_after = body.get("stop_after")     # step id to pause at (inclusive)
    extra_args = body.get("extra_args", {})

    # Filter to requested steps in order
    ordered = [s for s in PIPELINE_STEPS if s["id"] in steps_req]

    q: Q.Queue = Q.Queue()

    def _run():
        stopped_at = None
        for step in ordered:
            sid = step["id"]
            q.put({"type": "step_start", "step": sid, "label": step["label"]})

            # Build args
            script = step["script"]
            args   = [sys.executable, script, name]
            args  += step["args"]
            args  += extra_args.get(sid, [])
            if sid == "upload":
                args += ["--project", name]

            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                for line in proc.stdout:
                    q.put({"type": "log", "step": sid, "line": line.rstrip()})
                proc.wait()
                ok = proc.returncode == 0
            except Exception as e:
                q.put({"type": "log", "step": sid, "line": f"ERROR: {e}"})
                ok = False

            q.put({"type": "step_done", "step": sid, "ok": ok})

            if not ok:
                q.put({"type": "pipeline_done", "stopped_at": sid, "error": True})
                q.put(None)
                return

            if stop_after and sid == stop_after:
                stopped_at = sid
                break

        q.put({"type": "pipeline_done", "stopped_at": stopped_at, "error": False})
        q.put(None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    def _stream():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    from flask import Response, stream_with_context
    return Response(stream_with_context(_stream()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/projects/<n>/youtube-id", methods=["POST"])
def set_youtube_id(name: str):
    """Store the YouTube video ID in the manifest after upload."""
    body = request.get_json(silent=True) or {}
    vid  = body.get("youtube_id", "").strip()
    if not vid:
        abort(400, "youtube_id required")
    manifest = _read(name)
    manifest["youtube_id"] = vid
    _write(name, manifest)
    return jsonify({"ok": True})


# =========================
# FRONTEND
# =========================
@app.route("/")
def index():
    return app.send_static_file("index.html")


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    Path("static").mkdir(exist_ok=True)
    app.run(debug=True, port=5000)
