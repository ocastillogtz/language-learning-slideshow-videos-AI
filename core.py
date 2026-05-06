"""Shared state and utilities for the Flask app."""
import threading
from pathlib import Path
from utils_config import load_config

cfg = load_config()
PROJECTS_DIR = Path(cfg["projects_dir"])

# Job status store: { "project__step": { status, log } }
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def jkey(project: str, step: str) -> str:
    return f"{project}__{step}"


def set_job(project: str, step: str, status: str, log: str = ""):
    with _lock:
        _jobs[jkey(project, step)] = {"status": status, "log": log}


def get_job(project: str, step: str) -> dict:
    with _lock:
        return dict(_jobs.get(jkey(project, step), {"status": "idle", "log": ""}))


def run_job(project: str, step: str, fn, *args, **kwargs):
    """Run fn in a background thread and track status."""
    # Set "running" BEFORE the thread starts so the UI poll never sees
    # a stale "done" from a previous run during the startup race window.
    set_job(project, step, "running")

    def worker():
        try:
            fn(*args, **kwargs)
            set_job(project, step, "done", "Completed successfully.")
        except Exception as e:
            set_job(project, step, "error", str(e))

    threading.Thread(target=worker, daemon=True).start()
