"""
annotation_store.py
===================
Read / edit / regenerate the grammar annotation of a single scene, backed by the
same per-scene cache the renderer uses (``videos/**/_annot/<scene_id>.json``,
keyed by sentence text + ``generate_annotations.CACHE_VERSION``).

This powers the annotation viewer/editor in the Generated Items tab:

  read_scene_annotation(project, scene_id)        -> {exists, text, tokens, spans, annotatable}
  save_scene_annotation(project, scene_id, t, s)  -> persist an EDITED structure
  regenerate_scene_annotation(project, scene_id)  -> re-prompt OpenAI (force)

Saving / regenerating writes the annotation into every ``_annot`` directory (so the
vertical and horizontal passes agree) and deletes the scene's rendered clip(s) so a
normal re-render rebuilds them with the new annotation. Lightweight on purpose
(no moviepy import) so the web routes stay fast.
"""

import json
from pathlib import Path

from utils_config import load_config
from utils_markup import strip_markup
import generate_annotations as ga


def _paths(project_name: str):
    cfg = load_config()
    pp = cfg["projects_dir"] / project_name
    return pp, pp / "project_manifest.json"


def _load_manifest(project_name: str):
    pp, mp = _paths(project_name)
    if not mp.exists():
        return None, pp
    with open(mp, encoding="utf-8") as f:
        return json.load(f), pp


def _find_scene(manifest: dict, scene_id: str):
    return next((s for s in (manifest or {}).get("scenes", []) if s.get("id") == scene_id), None)


def scene_annotation_text(scene: dict) -> str:
    """Canonical text the annotation is keyed by, or '' if the scene isn't annotatable
    (matches what create_video._prerender_annotations feeds the generator)."""
    if not scene or scene.get("_is_narration") or scene.get("_is_repetition"):
        return ""
    audio = scene.get("audio") or {}
    if audio.get("type") != "tts":
        return ""
    return strip_markup((audio.get("tts_text") or "").strip()).strip()


def _annot_cache_files(project_path: Path, scene_id: str, create_primary: bool = False):
    """All ``_annot/<scene_id>.json`` cache files under videos/ (vertical + any
    sub-pass like videos/h/). The primary (videos/_annot) is first."""
    videos  = project_path / "videos"
    primary = videos / "_annot"
    if create_primary:
        primary.mkdir(parents=True, exist_ok=True)
    files = []
    if primary.exists():
        files.append(primary / f"{scene_id}.json")
    if videos.exists():
        for d in videos.rglob("_annot"):
            if d.resolve() == primary.resolve():
                continue
            files.append(d / f"{scene_id}.json")
    # de-dup preserving order
    seen, out = set(), []
    for f in files:
        key = str(f)
        if key not in seen:
            seen.add(key); out.append(f)
    return out


def read_scene_annotation(project_name: str, scene_id: str) -> dict:
    manifest, pp = _load_manifest(project_name)
    scene = _find_scene(manifest, scene_id) if manifest else None
    text = scene_annotation_text(scene)
    if not text:
        return {"exists": False, "annotatable": False, "text": ""}
    for f in _annot_cache_files(pp, scene_id, create_primary=False):
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("text") == text and d.get("_cache_version") == ga.CACHE_VERSION \
                and isinstance(d.get("tokens"), list):
            return {"exists": True, "annotatable": True, "text": text,
                    "tokens": d.get("tokens", []), "spans": d.get("spans", [])}
    # no usable cache yet (never rendered, or the sentence text changed)
    return {"exists": False, "annotatable": True, "text": text}


def _write_all(project_path: Path, scene_id: str, annotation: dict) -> int:
    payload = dict(annotation, _cache_version=ga.CACHE_VERSION)
    written = 0
    for f in _annot_cache_files(project_path, scene_id, create_primary=True):
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(f)
            written += 1
        except Exception:
            pass
    return written


def _delete_clips(project_path: Path, scene_id: str) -> int:
    videos = project_path / "videos"
    n = 0
    if videos.exists():
        for clip in videos.rglob(f"{scene_id}.mp4"):
            try:
                clip.unlink(); n += 1
            except Exception:
                pass
    return n


def save_scene_annotation(project_name: str, scene_id: str, tokens, spans) -> dict:
    """Persist an edited annotation. Tokens/spans are sanitised through the same
    validators the generator uses, so the stored structure is always renderable."""
    manifest, pp = _load_manifest(project_name)
    if manifest is None:
        raise ValueError("Project not found")
    scene = _find_scene(manifest, scene_id)
    text = scene_annotation_text(scene)
    if not text:
        raise ValueError("Scene is not annotatable")

    clean_tokens = ga._clean_tokens(tokens or [])
    if not clean_tokens:
        clean_tokens = [{"text": w} for w in text.split()]
    clean_spans = ga._clean_spans(spans or [], len(clean_tokens))
    annotation = {"text": text, "tokens": clean_tokens, "spans": clean_spans}

    _write_all(pp, scene_id, annotation)
    clips = _delete_clips(pp, scene_id)
    return {"exists": True, "annotatable": True, **annotation, "removed_clips": clips}


def regenerate_scene_annotation(project_name: str, scene_id: str, force: bool = True) -> dict:
    """Re-prompt OpenAI for this scene and store the fresh annotation. Falls back to
    a plain token list (not cached) if the API call fails."""
    manifest, pp = _load_manifest(project_name)
    if manifest is None:
        raise ValueError("Project not found")
    scene = _find_scene(manifest, scene_id)
    text = scene_annotation_text(scene)
    if not text:
        raise ValueError("Scene is not annotatable")

    primary = pp / "videos" / "_annot" / f"{scene_id}.json"
    primary.parent.mkdir(parents=True, exist_ok=True)
    ann = ga.generate_annotations(text, cache_path=primary, force=force)

    # generate_annotations only writes the cache on a real (non-fallback) result.
    # If it did, propagate that file to the other _annot dirs; otherwise don't cache.
    cached = primary.exists()
    if cached:
        try:
            data = json.loads(primary.read_text(encoding="utf-8"))
            for f in _annot_cache_files(pp, scene_id, create_primary=True):
                if f.resolve() == primary.resolve():
                    continue
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    clips = _delete_clips(pp, scene_id)
    return {"exists": cached, "annotatable": True,
            "text": ann.get("text", text),
            "tokens": ann.get("tokens", []), "spans": ann.get("spans", []),
            "removed_clips": clips}
