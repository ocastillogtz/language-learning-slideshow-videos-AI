"""
migrate_to_db.py
================
One-time move from the JSON asset registries to data/pipeline.db (see db.py) and
to the organised asset folder layout. Safe to re-run: catalogs already in the DB
are left alone and files already in place are skipped.

  python migrate_to_db.py --dry-run     # show what would happen, change nothing
  python migrate_to_db.py               # back up, import, reorganise
  python migrate_to_db.py --export      # dump every catalog to data/exports/<ts>/ (JSON)

What it does
------------
1. Backs up every registry JSON + config.ini to data/backups/<timestamp>/.
2. Creates the first workspace ("german") using the existing assets/ and projects/
   folders in place (project folders are never moved or rewritten).
3. Imports characters, locations, project types, video clips, background music,
   SFX and subtitle looks into the DB.
4. Reorganises the files and rewrites the stored paths:

   assets/                           (per workspace)
     branding/                       icon, mascot, intro/outro clips
     characters/<name>/              art.png, 34left.png, thumbnail.png, ref.png …
     locations/<key>/background.png
     studios/podcast/                cached podcast studio images
     icons/  samples/                overlay icons, subtitle-preview backgrounds
     cache/                          regenerable caches
     _unsorted/                      files no catalog entry referenced (review & delete)
   library/                          (shared by every workspace)
     music/                          background music (unregistered files get registered)
     sfx/
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import db

ROOT = Path(__file__).resolve().parent
OLD = ROOT / "assets"
LIB = ROOT / "library"
AUDIO_EXTS = {".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".aac", ".flac"}

REGISTRIES = {          # kind -> legacy JSON file (relative to assets/)
    "characters":        "characters/characters.json",
    "locations":         "locations/locations.json",
    "project_types":     "project_types/project_types.json",
    "video_clips":       "video_clips/video_clips.json",
    "background_audio":  "background_audio/background_audio.json",
    "sfx":               "sfx/sfx.json",
    "subtitle_profiles": "subtitle_profiles.json",
}
LEGACY_FILES = ["assets.json", "characters.json", "locations.json", "assets.example.json"]

# character field -> canonical file name inside characters/<name>/
CHAR_FILES = {
    "artwork_file_path":     "art",
    "art_34left_file_path":  "34left",
    "thumbnail_file_path":   "thumbnail",
    "concept_art_file_path": "concept",
    "ref_image_file_path":   "ref",
    "ref_drawing_file_path": "ref_drawing",
}

DRY = False
_log: list[str] = []


def say(msg: str) -> None:
    _log.append(msg)
    print(("[dry-run] " if DRY else "") + msg)


def move(src: Path, dst: Path) -> Path:
    """Move src to dst and return where it landed. If dst already holds a DIFFERENT
    file, the source gets a free name (art_2.png …) so nothing is overwritten and a
    catalog entry keeps pointing at the same image; identical duplicates collapse."""
    if not src.exists() or src.resolve() == dst.resolve():
        return dst
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            say(f"  duplicate of {dst.relative_to(ROOT)} — dropping {src.relative_to(ROOT)}")
            if not DRY:
                src.unlink()
            return dst
        n = 2
        while (alt := dst.with_name(f"{dst.stem}_{n}{dst.suffix}")).exists():
            n += 1
        dst = alt
    say(f"  move {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    if not DRY:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return dst


def char_folder(name: str) -> str:
    return name.replace(" ", "_")


def load_json(rel: str) -> dict | None:
    p = OLD / rel
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------

def backup() -> Path:
    dest = ROOT / "data" / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    say(f"Backing up registries + config.ini to {dest.relative_to(ROOT)}")
    if DRY:
        return dest
    for rel in list(REGISTRIES.values()) + LEGACY_FILES:
        src = OLD / rel
        if src.exists():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    shutil.copy2(ROOT / "config.ini", dest / "config.ini")
    # The shipped project-type prompts stay versioned in git as the seed for new workspaces.
    seed = ROOT / "defaults" / "project_types.json"
    if not seed.exists() and (OLD / REGISTRIES["project_types"]).exists():
        seed.parent.mkdir(exist_ok=True)
        shutil.copy2(OLD / REGISTRIES["project_types"], seed)
    return dest


def ensure_workspace() -> str:
    ws = db.list_workspaces() if db.db_exists() else []
    if ws:
        say(f"Workspace already present: {ws[0]['slug']}")
        return ws[0]["slug"]
    say("Creating workspace 'german' (assets/ + projects/ stay where they are)")
    if not DRY:
        db.create_workspace("german", "German", "de", "assets", "projects", channel_name="Brezel")
        db.set_active_workspace("german")
    return "german"


def reorganise_characters(chars: dict) -> None:
    say("Characters -> characters/<name>/")
    moved: dict[str, str] = {}                       # old rel -> new rel (shared files move once)
    for key, c in chars.items():
        for field, stem in CHAR_FILES.items():
            rel = c.get(field)
            if not rel:
                continue
            rel = rel.replace("\\", "/")
            if rel in moved:
                c[field] = moved[rel]
                continue
            if rel.startswith("characters/"):        # already organised
                if not (OLD / rel).exists():
                    say(f"  ! {key}.{field}: missing file {rel}")
                continue
            src = OLD / rel
            if not src.exists():
                say(f"  ! {key}.{field}: missing file {rel} (left as is)")
                continue
            dst = move(src, OLD / f"characters/{char_folder(key)}/{stem}{src.suffix.lower()}")
            new_rel = dst.relative_to(OLD).as_posix()
            moved[rel] = new_rel
            c[field] = new_rel


def reorganise_locations(locs: dict) -> None:
    say("Locations -> locations/<key>/background.png")

    def walk(d: dict):
        for key, loc in d.items():
            rel = loc.get("artwork_file_path")
            if rel and not rel.endswith("/background" + Path(rel).suffix):
                dst = move(OLD / rel, OLD / f"locations/{key}/background{Path(rel).suffix.lower()}")
                loc["artwork_file_path"] = dst.relative_to(OLD).as_posix()
            walk(loc.get("sub_locations") or {})
    walk(locs)


def reorganise_library(music: dict, sfx: dict) -> None:
    say("Background music -> library/music/ ; SFX -> library/sfx/")
    for entry in music.values():
        rel = (entry.get("full_path") or "").replace("\\", "/")
        if rel.startswith("background_audio/"):
            dst = move(OLD / rel, LIB / "music" / Path(rel).name)
            entry["full_path"] = dst.relative_to(LIB).as_posix()
    for entry in sfx.values():
        rel = (entry.get("full_path") or "").replace("\\", "/")
        if rel.startswith("sfx/"):
            move(OLD / rel, LIB / rel)               # sfx/x.mp3 keeps its name

    # Audio files nobody registered: move + register so they show up in the UI.
    known = {Path(e.get("full_path", "")).name for e in music.values()}
    old_dir = OLD / "background_audio"
    if old_dir.exists():
        for f in sorted(old_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS and f.name not in known:
                dst = move(f, LIB / "music" / f.name)
                key = f.stem
                while key in music:
                    key += "_2"
                music[key] = {"name": key, "description": "", "full_path": dst.relative_to(LIB).as_posix()}
                say(f"  registered unlisted track '{key}'")
    sfx_dir = OLD / "sfx"
    if sfx_dir.exists():
        for f in sorted(sfx_dir.iterdir()):
            if f.is_file() and f.suffix != ".json":
                move(f, LIB / "sfx" / f.name)


def reorganise_misc() -> None:
    say("Studios, caches, leftovers")
    for src, dst in (("podcast_studio", "studios/podcast"),
                     ("character_art_cache", "cache/character_art"),
                     ("audio_cache", "cache/audio")):
        d = OLD / src
        if d.exists():
            for f in sorted(d.iterdir()):
                move(f, OLD / dst / f.name)
    # Whatever is left in character_art/ is referenced by no catalog entry.
    d = OLD / "character_art"
    if d.exists():
        for f in sorted(d.rglob("*")):
            if f.is_file():
                move(f, OLD / "_unsorted" / "character_art" / f.relative_to(d))


def cleanup(backup_dir: Path) -> None:
    say("Removing legacy registry files (copies are in the backup)")
    for rel in list(REGISTRIES.values()) + LEGACY_FILES:
        p = OLD / rel
        if p.exists():
            say(f"  remove {p.relative_to(ROOT)}")
            if not DRY:
                p.unlink()
    for p in sorted(OLD.rglob("*.example.json")):
        say(f"  remove {p.relative_to(ROOT)}")
        if not DRY:
            p.unlink()
    # empty folders left behind
    for d in sorted((p for p in OLD.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            say(f"  rmdir {d.relative_to(ROOT)}")
            if not DRY:
                d.rmdir()


def bootstrap_fresh_install() -> str | None:
    """First start without any data: create the default workspace with the shipped
    project types. Returns None (does nothing) if a workspace exists or legacy JSON
    registries are waiting to be migrated — those need an explicit `migrate_to_db.py`."""
    if db.db_exists() and db.list_workspaces():
        return None
    if any((OLD / rel).exists() for rel in REGISTRIES.values()):
        return None
    db.create_workspace("german", "German", "de", "assets", "projects")
    db.set_active_workspace("german")
    seed = ROOT / "defaults" / "project_types.json"
    if seed.exists():
        db.save_assets("project_types", json.loads(seed.read_text(encoding="utf-8")), "german")
    for d in ("assets", "projects", "library/music", "library/sfx"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    return "german"


def export() -> None:
    dest = ROOT / "data" / "exports" / datetime.now().strftime("%Y%m%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for ws in db.list_workspaces():
        for kind in db.ASSET_KINDS:
            if kind in db.SHARED_KINDS:
                continue
            data = db.load_assets(kind, ws["slug"])
            (dest / ws["slug"]).mkdir(exist_ok=True)
            (dest / ws["slug"] / f"{kind}.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        (dest / ws["slug"] / "settings.json").write_text(
            json.dumps({"workspace": ws, "settings": db.get_settings(ws["slug"])},
                       indent=2, ensure_ascii=False), encoding="utf-8")
    for kind in db.SHARED_KINDS:
        (dest / f"{kind}.json").write_text(
            json.dumps(db.load_assets(kind), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported to {dest}")


def main() -> None:
    global DRY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    if a.export:
        export()
        return
    DRY = a.dry_run

    backup_dir = backup()
    slug = ensure_workspace()

    catalogs = {kind: load_json(rel) for kind, rel in REGISTRIES.items()}
    already = {kind for kind in REGISTRIES
               if db.db_exists() and db.list_workspaces()
               and db.load_assets(kind, None if kind in db.SHARED_KINDS else slug)}

    if catalogs["characters"] is not None:
        reorganise_characters(catalogs["characters"])
    if catalogs["locations"] is not None:
        reorganise_locations(catalogs["locations"])
    reorganise_library(catalogs["background_audio"] or {}, catalogs["sfx"] or {})
    reorganise_misc()

    for kind, data in catalogs.items():
        if data is None:
            continue
        if kind in already:
            say(f"Catalog '{kind}' already in DB — not re-imported")
            continue
        say(f"Import {len(data):3} {kind}")
        if not DRY:
            db.save_assets(kind, data, None if kind in db.SHARED_KINDS else slug)

    cleanup(backup_dir)
    if not DRY:
        (backup_dir / "migration.log").write_text("\n".join(_log), encoding="utf-8")
    print("\nDone." if not DRY else "\nDry run finished — nothing was changed.")


if __name__ == "__main__":
    main()
