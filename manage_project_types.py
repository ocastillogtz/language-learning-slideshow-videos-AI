"""
manage_project_types.py
=======================
CLI and importable functions for project type asset CRUD.

Commands
--------
  list
  show   --name
  add    --name --self-description --prompt-file --schema-file [--rules-file]
  edit   --name [--self-description] [--prompt-file] [--schema-file] [--rules-file]
  remove --name

Usage
-----
  python manage_project_types.py list
  python manage_project_types.py show --name shadowing
  python manage_project_types.py add \\
      --name quiz \\
      --self-description "A quiz where characters guess a word from clues." \\
      --prompt-file prompts/quiz_prompt.txt \\
      --schema-file schemas/quiz_output_schema.json
"""

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from utils_config import load_config

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _types_path(assets_dir: Path) -> Path:
    return assets_dir / "project_types" / "project_types.json"

def _registry_path(assets_dir: Path) -> Path:
    return assets_dir / "assets.json"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_project_types(assets_dir: Path) -> dict:
    path = _types_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_project_types(assets_dir: Path, data: dict) -> None:
    path = _types_path(assets_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_registry(assets_dir: Path) -> dict:
    path = _registry_path(assets_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_registry(assets_dir: Path, data: dict) -> None:
    with open(_registry_path(assets_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core functions (importable by Flask routes)
# ---------------------------------------------------------------------------

def list_project_types(assets_dir: Path) -> list[dict]:
    return [
        {"name": k, "self_description": v.get("self_description", "")}
        for k, v in load_project_types(assets_dir).items()
    ]


def get_project_type(assets_dir: Path, name: str) -> dict:
    types = load_project_types(assets_dir)
    if name not in types:
        raise ValueError(f"Project type '{name}' not found.")
    return types[name]


def add_project_type(
    assets_dir: Path,
    name: str,
    self_description: str,
    description_for_prompt: str,
    output_json_schema: dict,
    scene_builder_rules: dict | None = None,
) -> dict:
    types = load_project_types(assets_dir)
    if name in types:
        raise ValueError(f"Project type '{name}' already exists. Use edit to update.")

    entry = {
        "name": name,
        "self_description": self_description,
        "description_for_prompt": description_for_prompt,
        "output_json_schema": output_json_schema,
        "scene_builder_rules": scene_builder_rules or {
            "include_narration": True,
            "include_dialog": True,
            "include_repetition_section": False,
            "repetition_count": 0,
            "inter_pause_between_scenes": True,
            "bell_before_repetition": False,
        },
    }
    types[name] = entry
    save_project_types(assets_dir, types)

    registry = load_registry(assets_dir)
    registry.setdefault("project_types", {})[name] = {
        "config": f"project_types/project_types.json#{name}"
    }
    save_registry(assets_dir, registry)

    logger.info(f"Project type '{name}' added.")
    return entry


def edit_project_type(assets_dir: Path, name: str, **kwargs) -> dict:
    types = load_project_types(assets_dir)
    if name not in types:
        raise ValueError(f"Project type '{name}' not found.")

    allowed = {"self_description", "description_for_prompt", "output_json_schema", "scene_builder_rules"}
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            types[name][k] = v

    save_project_types(assets_dir, types)
    logger.info(f"Project type '{name}' updated.")
    return types[name]


def remove_project_type(assets_dir: Path, name: str) -> None:
    types = load_project_types(assets_dir)
    if name not in types:
        raise ValueError(f"Project type '{name}' not found.")
    del types[name]
    save_project_types(assets_dir, types)

    registry = load_registry(assets_dir)
    registry.get("project_types", {}).pop(name, None)
    save_registry(assets_dir, registry)
    logger.info(f"Project type '{name}' removed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    assets_dir = cfg["assets_dir"]

    p = argparse.ArgumentParser(description="Manage project type assets")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all project types")

    sh = sub.add_parser("show", help="Print full definition of a project type")
    sh.add_argument("--name", required=True)

    a = sub.add_parser("add", help="Add a new project type")
    a.add_argument("--name",             required=True)
    a.add_argument("--self-description", required=True, dest="self_description")
    a.add_argument("--prompt-file",      required=True, dest="prompt_file",
                   help="Path to a .txt file with the GPT prompt template")
    a.add_argument("--schema-file",      required=True, dest="schema_file",
                   help="Path to a .json file with the expected GPT output schema")
    a.add_argument("--rules-file",       dest="rules_file",
                   help="Optional .json file with scene_builder_rules")

    e = sub.add_parser("edit", help="Edit an existing project type")
    e.add_argument("--name",             required=True)
    e.add_argument("--self-description", dest="self_description")
    e.add_argument("--prompt-file",      dest="prompt_file")
    e.add_argument("--schema-file",      dest="schema_file")
    e.add_argument("--rules-file",       dest="rules_file")

    r = sub.add_parser("remove", help="Remove a project type")
    r.add_argument("--name", required=True)

    args = p.parse_args()

    if args.cmd == "list":
        for pt in list_project_types(assets_dir):
            print(f"  {pt['name']:20}  {pt['self_description'][:60]}")

    elif args.cmd == "show":
        pt = get_project_type(assets_dir, args.name)
        print(json.dumps(pt, indent=2, ensure_ascii=False))

    elif args.cmd == "add":
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
        schema = json.loads(Path(args.schema_file).read_text(encoding="utf-8"))
        rules = json.loads(Path(args.rules_file).read_text(encoding="utf-8")) if args.rules_file else None
        add_project_type(
            assets_dir,
            name=args.name,
            self_description=args.self_description,
            description_for_prompt=prompt_text,
            output_json_schema=schema,
            scene_builder_rules=rules,
        )
        print(f"Project type '{args.name}' added.")

    elif args.cmd == "edit":
        kwargs = {}
        if args.self_description:
            kwargs["self_description"] = args.self_description
        if args.prompt_file:
            kwargs["description_for_prompt"] = Path(args.prompt_file).read_text(encoding="utf-8")
        if args.schema_file:
            kwargs["output_json_schema"] = json.loads(Path(args.schema_file).read_text(encoding="utf-8"))
        if args.rules_file:
            kwargs["scene_builder_rules"] = json.loads(Path(args.rules_file).read_text(encoding="utf-8"))
        edit_project_type(assets_dir, args.name, **kwargs)
        print(f"Project type '{args.name}' updated.")

    elif args.cmd == "remove":
        remove_project_type(assets_dir, args.name)
        print(f"Project type '{args.name}' removed.")


if __name__ == "__main__":
    main()
