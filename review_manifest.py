"""Claude-powered review of a project's manifest.

Reads project_manifest.json, sends the German learning script (narration +
dialog + repetition subtitles) to Claude, and writes a structured proofreading
report back into the manifest under the "manifest_review" key so the UI can
render it. Run it after "Generate Script" and before generating audio/images —
catching a wrong case ending or an unnatural line here is far cheaper than
re-synthesising a voice clip for it later.

Requires ANTHROPIC_API_KEY in the environment (see .env.example). The Claude
model is configurable via config.ini [review] anthropic_model.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from core import report_progress
from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Subtitle markup used across the pipeline, explained to Claude so it doesn't
# flag the markers themselves as spelling errors:
#   _word_    vocabulary highlight (underline)
#   *word*    emphasis
#   -[label]- inline grammar/tense tag shown before the phrase
_MARKUP_NOTE = (
    "The text uses pipeline markup that is NOT part of the German and must not "
    "be reported as an error: `_word_` marks a vocabulary highlight, `*word*` "
    "marks emphasis, and `-[label]-` is an inline grammar/tense tag. Review the "
    "German inside and around the markup, never the markers themselves."
)

# JSON schema the model must fill. Structured-outputs rules: every object needs
# additionalProperties:false and all its properties in `required`.
_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-4 sentence overall assessment of the script's "
                           "German quality and fit for the target level.",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scene_id": {
                        "type": "string",
                        "description": "The id of the affected scene, or "
                                       "\"general\" for a script-wide remark.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["error", "warning", "suggestion"],
                        "description": "error = incorrect German; warning = "
                                       "unnatural or level-inappropriate; "
                                       "suggestion = optional improvement.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["grammar", "spelling", "naturalness",
                                 "level", "consistency", "other"],
                    },
                    "quote": {
                        "type": "string",
                        "description": "The exact problematic fragment from the "
                                       "scene text.",
                    },
                    "issue": {
                        "type": "string",
                        "description": "What is wrong, briefly.",
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "A corrected or improved version of the "
                                       "fragment (empty string if none).",
                    },
                },
                "required": ["scene_id", "severity", "category",
                             "quote", "issue", "suggestion"],
            },
        },
    },
    "required": ["summary", "issues"],
}


def _load_manifest(project_name: str):
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return cfg, manifest_path, json.load(f)


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomic manifest write (temp file + rename) so an interrupted run can't corrupt it."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)


def _scene_text(scene: dict) -> str:
    """The German line for a scene: prefer the on-screen subtitle, fall back to
    the spoken (TTS) text."""
    txt = (scene.get("subtitle_text") or "").strip()
    if txt:
        return txt
    return ((scene.get("audio") or {}).get("tts_text") or "").strip()


def _scene_role(scene: dict) -> str:
    if scene.get("_is_narration"):
        return "narration"
    if scene.get("_is_repetition") or scene.get("_is_repeat_prompt"):
        return "repetition"
    desc = (scene.get("description") or "")
    if desc.startswith("dialog"):
        return "dialog"
    return desc or "other"


def _collect_lines(manifest: dict) -> list[dict]:
    """Every scene that carries German text, as compact review records."""
    lines = []
    for scene in manifest.get("scenes", []):
        text = _scene_text(scene)
        if not text:
            continue
        chars = scene.get("characters") or []
        lines.append({
            "scene_id": scene.get("id"),
            "role":     _scene_role(scene),
            "speaker":  (chars[0] if len(chars) == 1 else None),
            "text":     text,
        })
    return lines


def _build_prompt(manifest: dict, lines: list[dict], level: str,
                  prompt_override: str | None) -> tuple[str, str]:
    """Return (system_prompt, user_content)."""
    gen  = manifest.get("generation_config") or {}
    info = manifest.get("video_info") or {}

    focus = prompt_override or (
        "Focus on: (1) grammatical errors (case, gender, agreement, verb "
        "conjugation, word order), (2) spelling and typos, (3) unnatural or "
        "non-idiomatic phrasing and wrong register for the situation, "
        f"(4) whether the language fits CEFR level {level} (flag lines that are "
        "clearly too hard or too trivial), and (5) consistency with the stated "
        "topic, learning points, and speakers."
    )

    system = (
        "You are a meticulous native-German editor and CEFR-certified German "
        "teacher reviewing the script of a German-learning video before it is "
        "voiced and animated. "
        f"{_MARKUP_NOTE} "
        f"{focus} "
        "Only report genuine problems — do not invent issues to fill the list. "
        "If the script is clean, return an empty issues array and say so in the "
        "summary. Quote the exact fragment for every issue and give a concrete "
        "corrected version in `suggestion` (use an empty string when no rewrite "
        "applies). Write `issue` and `summary` in English; keep `quote` and "
        "`suggestion` in German."
    )

    context = {
        "title":            info.get("title"),
        "target_level":     level,
        "provided_context": gen.get("provided_context"),
        "learning_points":  gen.get("provided_learning_points"),
        "words":            gen.get("words"),
        "characters":       gen.get("characters"),
    }
    user = (
        "Project context (JSON):\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\nScript lines to review (JSON array, in order):\n"
        + json.dumps(lines, ensure_ascii=False, indent=2)
    )
    return system, user


def review_manifest(project_name: str, prompt_override: str | None = None) -> dict:
    """Review the project's script with Claude and store the report in the manifest.

    Returns the review dict; also written to manifest["manifest_review"].
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "The 'anthropic' package is not installed. Run "
            "install_dependencies.bat (or `pip install anthropic`) and retry."
        ) from e

    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env "
            "(see .env.example) and restart the app."
        )

    cfg, manifest_path, manifest = _load_manifest(project_name)
    level = (manifest.get("generation_config") or {}).get("level") or cfg["level"]
    lines = _collect_lines(manifest)
    if not lines:
        raise RuntimeError(
            "No script text found to review. Run 'Generate Script' first."
        )

    report_progress(0, 1, f"Reviewing {len(lines)} lines with Claude…")

    system, user = _build_prompt(manifest, lines, level, prompt_override)
    model = cfg["review_model"]
    logger.info("Reviewing '%s' (%d lines) with %s …",
                project_name, len(lines), model)

    client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _REVIEW_SCHEMA},
        },
        messages=[{"role": "user", "content": user}],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude's review was cut off (too many issues for one pass). "
            "Split the project or review it in parts."
        )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to review this content.")

    # output_config.format guarantees the first text block is valid JSON.
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse Claude's review as JSON: {e}") from e

    issues = parsed.get("issues", []) or []
    counts = {"error": 0, "warning": 0, "suggestion": 0}
    for it in issues:
        counts[it.get("severity", "suggestion")] = \
            counts.get(it.get("severity", "suggestion"), 0) + 1

    review = {
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "model":       model,
        "level":       level,
        "lines_reviewed": len(lines),
        "summary":     parsed.get("summary", ""),
        "counts":      counts,
        "issues":      issues,
    }
    manifest["manifest_review"] = review
    _write_manifest(manifest_path, manifest)

    report_progress(1, 1, "Review complete")
    logger.info("Review of '%s' complete: %d error(s), %d warning(s), "
                "%d suggestion(s).", project_name,
                counts["error"], counts["warning"], counts["suggestion"])
    return review


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python review_manifest.py <project_name>")
        raise SystemExit(1)
    r = review_manifest(sys.argv[1])
    print(json.dumps(r, ensure_ascii=False, indent=2))
