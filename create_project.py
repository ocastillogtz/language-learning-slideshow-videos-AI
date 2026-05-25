"""
create_project.py
=================
Creates the project folder and the initial project_manifest.json skeleton.

The manifest uses the new scene-first architecture:
  project_metadata  — name, dates, project_type_key
  video_info        — title, tags, video_format, insights (filled by create_script)
  generation_config — location, characters, prompts (filled by create_script)
  pipeline_config   — timing parameters
  scenes            — flat list of universal scene objects (filled by create_script)
"""

import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
from utils_config import load_config, load_project_types

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


VALID_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

# Project type keys (or their base types) that treat learning_points as a word list
_WORD_LEARNING_TYPES = {"word_learning"}


def _parse_words(project_type: dict, learning_points: str) -> list[str]:
    """
    For word_learning projects, parse the learning_points string into a word list
    so it is immediately available in generation_config.words without the user
    having to re-enter the words on the script step.

    Returns an empty list for all other project types.
    """
    effective_name = project_type.get("base_type") or project_type.get("name", "")
    if effective_name not in _WORD_LEARNING_TYPES:
        return []
    words = [w.strip() for w in learning_points.split(",") if w.strip()]
    return words


def create_project(
    project_name: str,
    project_type_key: str,
    context: str,
    learning_points: str = "",
    level: str | None = None,
) -> Path:
    """
    Create the project folder structure and initial manifest.

    Parameters
    ----------
    project_name     : Unique folder name for the project.
    project_type_key : Key from assets/project_types/project_types.json
                       (e.g. "shadowing", "story", "word_learning").
    context          : Free-text description of the scene / video topic.
    learning_points  : Optional learning objectives or word list.
    level            : Target language level (A1–C2). Defaults to config value.
    """
    cfg          = load_config()
    project_path = cfg["projects_dir"] / project_name

    if project_path.exists():
        raise FileExistsError(f"Project already exists: {project_path}")

    # Validate project type
    project_types = load_project_types(cfg["assets_dir"])
    if project_type_key not in project_types:
        available = sorted(project_types.keys())
        raise ValueError(
            f"Unknown project_type_key '{project_type_key}'. "
            f"Available: {available}"
        )

    # Resolve the effective project type (inherit from base_type if set)
    project_type = project_types[project_type_key]
    base_type_key = project_type.get("base_type")
    if base_type_key and base_type_key in project_types:
        base = project_types[base_type_key]
        project_type = {**base, **project_type}  # long type fields override base

    # Resolve level — explicit arg wins, falls back to config default
    resolved_level = (level or "").strip().upper() or cfg["level"]
    if resolved_level not in VALID_LEVELS:
        raise ValueError(f"Invalid level '{resolved_level}'. Must be one of {VALID_LEVELS}")

    logger.info(f"Creating project: {project_name} (type: {project_type_key}, level: {resolved_level})")

    for d in ["audio", "images", "videos"]:
        (project_path / d).mkdir(parents=True, exist_ok=True)

    now = datetime.utcnow().isoformat()

    manifest = {
        "project_metadata": {
            "name":             project_name,
            "creation_date":    now,
            "update_date":      now,
            "project_type_key": project_type_key,
        },

        # Filled by create_script
        "video_info": {
            "title":        None,
            "tags":         None,
            "video_format": project_type.get("format", "vertical"),
            "insights":     None,
        },

        # Partially filled now, rest by create_script
        "generation_config": {
            "location_key":             None,
            "characters":               [],
            "level":                    resolved_level,
            "provided_context":         context,
            "provided_learning_points": learning_points,
            "words": _parse_words(project_type, learning_points),
            "prompt_script":            None,
            "prompt_repetitions":       None,
        },

        "pipeline_config": {
            "inter_pause_ms":          cfg["inter_pause_ms"],
            "repetition_pause_factor": cfg["repetition_pause_factor"],
        },

        # Filled by create_script — flat list of universal scene objects
        "scenes": [],
    }

    manifest_path = project_path / "project_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Manifest created: {manifest_path}")
    return project_path


def main() -> None:
    p = argparse.ArgumentParser(description="Create a new video project")
    p.add_argument("project_name")
    p.add_argument("--type",     required=True, dest="project_type_key",
                   help="Project type key (e.g. shadowing, story, word_learning)")
    p.add_argument("--context",  required=True,
                   help="Scene description / video topic")
    p.add_argument("--learning", default="", dest="learning_points",
                   help="Learning objectives or word list")
    p.add_argument("--level", default=None,
                   help=f"Target language level, e.g. B1 (default: config value). One of {VALID_LEVELS}")
    a = p.parse_args()
    create_project(a.project_name, a.project_type_key, a.context, a.learning_points, a.level)


if __name__ == "__main__":
    main()
