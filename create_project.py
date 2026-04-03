"""
create_project.py

Creates a new project structure for the video pipeline.

Features:
- Creates project folder
- Stores scene + learning inputs
- Initializes project_manifest.json (single source of truth)
- Uses config.ini for global paths
- CLI support

Usage:
    python create_project.py my_project \
        --scene "Office conversation" \
        --learning "Practice formal requests"
"""

import json
import argparse
import logging
import configparser
from pathlib import Path
from datetime import datetime

# =========================
# 🔧 CONFIG
# =========================
LOG_LEVEL = logging.INFO

# =========================
# 🪵 LOGGING
# =========================
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# ⚙️ CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()

    if not Path(config_path).exists():
        raise FileNotFoundError("config.ini not found")

    config.read(config_path)

    projects_dir = Path(config["paths"]["projects_dir"])
    assets_dir = Path(config["paths"]["assets_dir"])

    return projects_dir, assets_dir


# =========================
# 📁 CREATE PROJECT
# =========================
def create_project(
    project_name: str,
    scene_text: str = None,
    learning_text: str = None,
    scene_file: str = None,
    learning_file: str = None
):
    """
    Create a new project.

    Args:
        project_name (str)
        scene_text (str)
        learning_text (str)
        scene_file (str)
        learning_file (str)
    """

    projects_dir, assets_dir = load_config()

    project_path = projects_dir / project_name

    if project_path.exists():
        raise FileExistsError(f"Project already exists: {project_path}")

    logger.info(f"Creating project: {project_name}")

    # ----------------------
    # 📁 Create folders
    # ----------------------
    project_path.mkdir(parents=True)
    (project_path / "audio").mkdir()
    (project_path / "images").mkdir()

    # ----------------------
    # 📄 Load inputs
    # ----------------------
    if scene_file:
        scene_text = Path(scene_file).read_text(encoding="utf-8")

    if learning_file:
        learning_text = Path(learning_file).read_text(encoding="utf-8")

    if not scene_text or not learning_text:
        raise ValueError("You must provide scene and learning inputs")

    # ----------------------
    # 💾 Save raw inputs
    # ----------------------
    (project_path / "scene.txt").write_text(scene_text, encoding="utf-8")
    (project_path / "learning_points.txt").write_text(learning_text, encoding="utf-8")

    # ----------------------
    # 🧠 INITIAL MANIFEST
    # ----------------------
    manifest = {
        "project": {
            "name": project_name,
            "created_at": datetime.utcnow().isoformat(),
        },
        "paths": {
            "project_root": str(project_path),
            "assets_root": str(assets_dir)
        },
        "inputs": {
            "scene": scene_text,
            "learning_points": learning_text
        },
        "script": {
            "insights": None,
            "context": None,
            "conversation": []
        },
        "scenes": []
    }

    manifest_path = project_path / "project_manifest.json"

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Project created at: {project_path}")
    logger.info(f"Manifest created: {manifest_path}")

    return project_path


# =========================
# 🧭 CLI
# =========================
def main():
    parser = argparse.ArgumentParser(
        description="Create a new project for the video generation pipeline"
    )

    parser.add_argument(
        "project_name",
        help="Name of the project"
    )

    parser.add_argument(
        "--scene",
        help="Scene description text"
    )

    parser.add_argument(
        "--learning",
        help="Learning points text"
    )

    parser.add_argument(
        "--scene-file",
        help="Path to scene.txt"
    )

    parser.add_argument(
        "--learning-file",
        help="Path to learning_points.txt"
    )

    args = parser.parse_args()

    create_project(
        project_name=args.project_name,
        scene_text=args.scene,
        learning_text=args.learning,
        scene_file=args.scene_file,
        learning_file=args.learning_file
    )


# =========================
# ▶️ ENTRYPOINT
# =========================
if __name__ == "__main__":
    create_project(
        project_name="coffee_convo_1",
        scene_text="Olena and Mario are talking in the coffee shop about finding a handyman to fix leaking in the kitchen sink. Two interaction per character",
        learning_text="use at least 3 advanced words of the b2 or c1 level.",
    )

