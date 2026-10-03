"""
db.py
=====
SQLite store for everything that is GLOBAL to the pipeline (data/pipeline.db):

  workspaces   one per language / channel (German "Brezel", a Spanish channel, …):
               its language, channel name, icon + mascot, and its own assets/ and
               projects/ folders.
  settings     per-workspace overrides of config.ini ({section: {key: value}}).
               config.ini keeps the defaults; load_config() layers these on top.
  assets       the asset catalog (characters, locations, project types, video clips,
               background music, SFX). One JSON document per asset. Music and SFX
               are a SHARED library (workspace = '') used by every workspace.
  projects     a cached index of each workspace's project_manifest.json files
               (rebuilt from disk whenever a manifest's mtime changes) + which
               assets every project uses.

Project manifests stay as JSON files inside each project folder — they remain the
source of truth; this DB only indexes them. Media files stay on disk; the DB only
stores paths RELATIVE to the workspace's assets dir (or the shared library dir).

Both the Flask app and the MCP server open this file, so every connection uses
WAL mode + a busy timeout: concurrent readers never block and writes are atomic.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "pipeline.db"

SCHEMA_VERSION = 1

# Asset kinds whose catalog (and files) are shared by every workspace.
SHARED_KINDS = {"background_audio", "sfx"}
ASSET_KINDS  = ("characters", "locations", "project_types", "video_clips",
                "background_audio", "sfx", "subtitle_profiles")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS workspaces (
    slug          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT 'de',
    channel_name  TEXT NOT NULL DEFAULT '',
    icon_path     TEXT,            -- relative to the workspace assets dir
    mascot_path   TEXT,            -- relative to the workspace assets dir
    assets_dir    TEXT NOT NULL,
    projects_dir  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    workspace TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE ON UPDATE CASCADE,
    section   TEXT NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    PRIMARY KEY (workspace, section, key)
);
CREATE TABLE IF NOT EXISTS assets (
    workspace  TEXT NOT NULL,      -- '' = shared library
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    data       TEXT NOT NULL,      -- JSON document
    position   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace, kind, key)
);
CREATE TABLE IF NOT EXISTS projects (
    workspace        TEXT NOT NULL,
    name             TEXT NOT NULL,
    manifest_mtime   REAL NOT NULL,
    created_at       TEXT,
    project_type_key TEXT,
    summary          TEXT NOT NULL, -- JSON card shown in the sidebar
    PRIMARY KEY (workspace, name)
);
CREATE TABLE IF NOT EXISTS asset_usage (
    workspace TEXT NOT NULL,
    project   TEXT NOT NULL,
    kind      TEXT NOT NULL,
    key       TEXT NOT NULL,
    PRIMARY KEY (workspace, project, kind, key)
);
CREATE INDEX IF NOT EXISTS asset_usage_by_asset ON asset_usage (kind, key);
"""

_init_lock = threading.Lock()
_initialised = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    return con


@contextmanager
def connect():
    """Yield a connection inside a transaction (commit on success, rollback on error)."""
    global _initialised
    con = _connect()
    try:
        if not _initialised:
            with _init_lock:
                if not _initialised:
                    con.executescript(_SCHEMA)
                    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)",
                                (str(SCHEMA_VERSION),))
                    con.commit()
                    _initialised = True
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def db_exists() -> bool:
    return DB_PATH.exists()


# =============================================================================
# meta (app-wide key/value)
# =============================================================================

def get_meta(key: str, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value) -> None:
    with connect() as con:
        con.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, None if value is None else str(value)))


# =============================================================================
# Workspaces
# =============================================================================

WORKSPACE_FIELDS = ("name", "language_code", "channel_name", "icon_path", "mascot_path",
                    "assets_dir", "projects_dir")


def list_workspaces() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM workspaces ORDER BY created_at, slug").fetchall()
    return [dict(r) for r in rows]


def get_workspace(slug: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM workspaces WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def active_workspace_slug() -> str | None:
    """The workspace the app is working in (shared by the web UI, CLI and MCP server)."""
    if not db_exists():
        return None
    slug = get_meta("active_workspace")
    if slug and get_workspace(slug):
        return slug
    ws = list_workspaces()
    return ws[0]["slug"] if ws else None


def active_workspace() -> dict | None:
    slug = active_workspace_slug()
    return get_workspace(slug) if slug else None


def set_active_workspace(slug: str) -> None:
    if not get_workspace(slug):
        raise KeyError(f"Workspace '{slug}' not found")
    set_meta("active_workspace", slug)


def create_workspace(slug: str, name: str, language_code: str, assets_dir: str,
                     projects_dir: str, channel_name: str = "") -> dict:
    now = _now()
    with connect() as con:
        if con.execute("SELECT 1 FROM workspaces WHERE slug = ?", (slug,)).fetchone():
            raise ValueError(f"Workspace '{slug}' already exists")
        con.execute(
            "INSERT INTO workspaces (slug, name, language_code, channel_name, assets_dir,"
            " projects_dir, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (slug, name, language_code, channel_name, assets_dir, projects_dir, now, now))
    return get_workspace(slug)


def update_workspace(slug: str, **fields) -> dict:
    fields = {k: v for k, v in fields.items() if k in WORKSPACE_FIELDS}
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with connect() as con:
            cur = con.execute(f"UPDATE workspaces SET {cols}, updated_at = ? WHERE slug = ?",
                              (*fields.values(), _now(), slug))
            if cur.rowcount == 0:
                raise KeyError(f"Workspace '{slug}' not found")
    return get_workspace(slug)


def delete_workspace(slug: str) -> None:
    """Remove a workspace's DB rows (settings, catalog, index). Files are left on disk."""
    with connect() as con:
        con.execute("DELETE FROM workspaces WHERE slug = ?", (slug,))
        for table in ("assets", "projects", "asset_usage"):
            con.execute(f"DELETE FROM {table} WHERE workspace = ?", (slug,))
    if get_meta("active_workspace") == slug:
        set_meta("active_workspace", None)


# =============================================================================
# Settings (per-workspace overrides of config.ini)
# =============================================================================

def get_settings(workspace: str) -> dict[str, dict[str, str]]:
    with connect() as con:
        rows = con.execute("SELECT section, key, value FROM settings WHERE workspace = ?",
                           (workspace,)).fetchall()
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out.setdefault(r["section"], {})[r["key"]] = r["value"]
    return out


def set_settings(workspace: str, updates: dict[str, dict[str, object]]) -> None:
    """Upsert {section: {key: value}}. A value of None removes the override
    (the key falls back to the config.ini default)."""
    with connect() as con:
        for section, kv in updates.items():
            for key, value in kv.items():
                sec, k = section.lower(), key.lower()
                if value is None:
                    con.execute("DELETE FROM settings WHERE workspace=? AND section=? AND key=?",
                                (workspace, sec, k))
                else:
                    con.execute(
                        "INSERT INTO settings VALUES (?,?,?,?) ON CONFLICT(workspace, section, key)"
                        " DO UPDATE SET value = excluded.value", (workspace, sec, k, str(value)))


def copy_settings(src: str, dst: str) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO settings SELECT ?, section, key, value FROM settings"
                    " WHERE workspace = ?", (dst, src))


# =============================================================================
# Asset catalog
# =============================================================================

def _scope(kind: str, workspace: str | None) -> str:
    if kind in SHARED_KINDS:
        return ""
    ws = workspace or active_workspace_slug()
    if not ws:
        raise RuntimeError("No workspace configured — run `python migrate_to_db.py` first.")
    return ws


def load_assets(kind: str, workspace: str | None = None) -> dict[str, dict]:
    """Return {key: document} for one asset kind, in catalog order."""
    scope = _scope(kind, workspace)
    with connect() as con:
        rows = con.execute("SELECT key, data FROM assets WHERE workspace=? AND kind=?"
                           " ORDER BY position, key", (scope, kind)).fetchall()
    return {r["key"]: json.loads(r["data"]) for r in rows}


def save_assets(kind: str, data: dict[str, dict], workspace: str | None = None) -> None:
    """Replace the whole catalog of one kind atomically (mirrors the old save-the-JSON
    semantics, so the manage_* modules keep their load → mutate → save flow)."""
    scope = _scope(kind, workspace)
    now = _now()
    with connect() as con:
        con.execute("DELETE FROM assets WHERE workspace=? AND kind=?", (scope, kind))
        con.executemany(
            "INSERT INTO assets (workspace, kind, key, data, position, updated_at) VALUES (?,?,?,?,?,?)",
            [(scope, kind, key, json.dumps(doc, ensure_ascii=False), i, now)
             for i, (key, doc) in enumerate(data.items())])


def copy_assets(kind: str, src: str, dst: str) -> int:
    if kind in SHARED_KINDS:
        return 0
    data = load_assets(kind, src)
    save_assets(kind, data, dst)
    return len(data)


# =============================================================================
# Project index + asset usage
# =============================================================================

def get_project_index(workspace: str) -> dict[str, dict]:
    with connect() as con:
        rows = con.execute("SELECT name, manifest_mtime, summary FROM projects WHERE workspace=?",
                           (workspace,)).fetchall()
    return {r["name"]: {"mtime": r["manifest_mtime"], "summary": json.loads(r["summary"])}
            for r in rows}


def upsert_project_index(workspace: str, name: str, mtime: float, summary: dict,
                         usage: list[tuple[str, str]]) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?)",
            (workspace, name, mtime, summary.get("created_at"), summary.get("project_type_key"),
             json.dumps(summary, ensure_ascii=False)))
        con.execute("DELETE FROM asset_usage WHERE workspace=? AND project=?", (workspace, name))
        con.executemany("INSERT OR IGNORE INTO asset_usage VALUES (?,?,?,?)",
                        [(workspace, name, kind, key) for kind, key in usage if key])


def prune_project_index(workspace: str, keep: set[str]) -> None:
    with connect() as con:
        for (name,) in con.execute("SELECT name FROM projects WHERE workspace=?", (workspace,)).fetchall():
            if name not in keep:
                con.execute("DELETE FROM projects WHERE workspace=? AND name=?", (workspace, name))
                con.execute("DELETE FROM asset_usage WHERE workspace=? AND project=?", (workspace, name))


def asset_usage(kind: str, workspace: str | None = None) -> dict[str, list[str]]:
    """{asset key: [project names]} — shared kinds count usage across all workspaces."""
    sql, args = "SELECT key, project FROM asset_usage WHERE kind=?", [kind]
    if kind not in SHARED_KINDS:
        sql += " AND workspace=?"
        args.append(workspace or active_workspace_slug())
    with connect() as con:
        rows = con.execute(sql + " ORDER BY project", args).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["key"], []).append(r["project"])
    return out
