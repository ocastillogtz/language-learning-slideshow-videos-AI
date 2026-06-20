"""Shared state and utilities for the Flask app."""
import threading
from pathlib import Path
from utils_config import load_config

cfg = load_config()
PROJECTS_DIR = Path(cfg["projects_dir"])

# Job status store: { "project__step": { status, log, progress } }
# progress is either None or {"current": int, "total": int, "label": str}.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()

# Per-thread progress sink. run_job binds this in the worker thread so the
# pipeline functions can call report_progress() without changing their
# signatures; when those same functions run from the CLI it stays unbound and
# report_progress() is a no-op.
_current = threading.local()


def jkey(project: str, step: str) -> str:
    return f"{project}__{step}"


def set_job(project: str, step: str, status: str, log: str = ""):
    with _lock:
        # A status change always clears the progress bar except while running,
        # where set_progress() keeps it up to date.
        prev = _jobs.get(jkey(project, step), {})
        progress = prev.get("progress") if status == "running" else None
        _jobs[jkey(project, step)] = {"status": status, "log": log, "progress": progress}


def set_progress(project: str, step: str, current: int, total: int, label: str = ""):
    """Update the progress bar of a running job (current of total elements)."""
    with _lock:
        job = _jobs.get(jkey(project, step)) or {"status": "running", "log": ""}
        job["progress"] = {"current": current, "total": total, "label": label}
        _jobs[jkey(project, step)] = job


def report_progress(current: int, total: int, label: str = ""):
    """Called from inside a pipeline function's loop to report progress.

    Reports to whichever job owns the current worker thread. No-op when there is
    no bound job (e.g. the function was invoked directly from the CLI).
    """
    cb = getattr(_current, "cb", None)
    if cb:
        try:
            cb(current, total, label)
        except Exception:
            pass


def get_job(project: str, step: str) -> dict:
    with _lock:
        return dict(_jobs.get(jkey(project, step), {"status": "idle", "log": "", "progress": None}))


def run_job(project: str, step: str, fn, *args, **kwargs):
    """Run fn in a background thread and track status."""
    # Set "running" BEFORE the thread starts so the UI poll never sees
    # a stale "done" from a previous run during the startup race window.
    set_job(project, step, "running")
    with _lock:                       # reset any progress carried over from a prior run
        _jobs[jkey(project, step)]["progress"] = None

    def worker():
        _current.cb = lambda c, t, label="": set_progress(project, step, c, t, label)
        try:
            fn(*args, **kwargs)
            set_job(project, step, "done", "Completed successfully.")
        except Exception as e:
            set_job(project, step, "error", str(e))
        finally:
            _current.cb = None

    threading.Thread(target=worker, daemon=True).start()
