"""OpenAI-powered rule-based review (and fix) of a project's manifest.

Reads project_manifest.json, checks the German learning script against a set of
named rules, and writes a structured report back into the manifest under the
"manifest_review" key so the UI can render it. Each fixable finding carries a
full corrected value; `apply_review_fixes()` writes the accepted ones back.

Run it after "Generate Script" and before generating audio/images — catching a
wrong case ending, a missing vocabulary highlight or a thin visual prompt here
is far cheaper than re-synthesising a voice clip or re-rendering an image later.

Rules
-----
Correctness
  grammar        Case/gender/agreement, verb conjugation, word order.
  spelling       Typos, ß/ss, noun capitalization, punctuation.
Highlighting / pedagogy
  highlight      Every dialog line highlights >=1 word with _word_ or *word*.
  highlight_qual Highlighted words are meaningful vocabulary (not filler) and,
                 when a learning-points/word list exists, relate to it.
  level          Language fits the target CEFR level (not too hard / trivial).
Naturalness / coherence
  coherence      Each line follows logically; clear thread, natural open/close.
  register       Idiomatic German; Sie/du stays consistent and fits the setting.
  speaker_flow   Speakers alternate sensibly; no near-duplicate lines.
Visuals
  visual_detail  scene_visual is present and detailed (setting/characters/action).
  visual_match   The described image fits the line; no on-image text/bubbles.
Meta
  narration      The intro narration frames the topic and learning points.
  length         A subtitle isn't too long to read on one screen.

Requires OPENAI_API_KEY in the environment (see .env.example). The GPT model is
configurable via config.ini [review] openai_model.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from core import report_progress
from utils_config import load_config

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Deterministic thresholds for the rules we check in code (exact, no LLM needed).
_VISUAL_MIN_CHARS   = 60    # scene_visual shorter than this is "thin" (visual_detail)
_SUBTITLE_MAX_CHARS = 120   # subtitle longer than this is hard to read (length)

# A vocabulary highlight: _word_ or *word* with non-space content inside.
_HIGHLIGHT_RE = re.compile(r"_[^_\s][^_]*_|\*[^*\s][^*]*\*")

# Subtitle markup used across the pipeline, explained to GPT so it doesn't flag
# the markers themselves as spelling errors:
#   _word_    vocabulary highlight (underline)
#   *word*    emphasis
#   -[label]- inline grammar/tense tag shown before the phrase
_MARKUP_NOTE = (
    "The text uses pipeline markup that is NOT part of the German and must not "
    "be reported as an error: `_word_` marks a vocabulary highlight, `*word*` "
    "marks emphasis, and `-[label]-` is an inline grammar/tense tag. Review the "
    "German inside and around the markup, never the markers themselves. Any "
    "corrected line you return must KEEP this markup and still highlight at "
    "least one meaningful vocabulary word with `_word_` or `*word*`."
)

_RULES_BLOCK = """Check every scene against these rules and report each violation:
- grammar: case/gender/agreement, verb conjugation, word order.
- spelling: typos, ß/ss, noun capitalization, punctuation.
- highlight_qual: highlighted words must be meaningful vocabulary (not filler
  like und/der/ich) and, when learning_points/words are given, relate to them.
- level: language must fit the target CEFR level — flag lines clearly too hard
  or too trivial.
- coherence: each dialog line must follow logically from the previous one; the
  conversation needs a clear thread and a natural opening and closing.
- register: idiomatic spoken German; the Sie/du (formal/informal) choice must be
  consistent across the whole dialog and fit the situation.
- speaker_flow: speakers should alternate sensibly (flag accidental same-speaker
  runs) and no two lines should be near-duplicates.
- visual_match: the scene's `visual` must match what the line says and stay
  consistent with its characters/location; it must contain no on-image text,
  subtitles or speech bubbles.
- narration: the intro narration must correctly frame the topic and the stated
  learning points."""

_OUTPUT_SHAPE = r"""Return a single JSON object with exactly this shape:
{
  "summary": "2-4 sentence overall assessment (English).",
  "findings": [
    {
      "scene_id": "id of the affected scene, or \"general\" for a script-wide remark",
      "field": "subtitle_text | scene_visual | general (which manifest field the fix applies to)",
      "rule": "one of: grammar, spelling, highlight_qual, level, coherence, register, speaker_flow, visual_match, narration",
      "severity": "error | warning | suggestion",
      "quote": "the exact problematic fragment",
      "issue": "what is wrong, briefly (English)",
      "fixed": "the FULL corrected value for that field in German (whole line or whole visual), fixing every problem you noted in it at once; empty string if there is no automatic fix"
    }
  ]
}
When a subtitle has several problems (e.g. a grammar error AND no highlighted
word), emit ONE finding for that subtitle whose `fixed` corrects them all.
Return an empty "findings" array if the script is clean."""


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
    """Every scene that carries German text, as compact review records including
    the visual prompt so the model can check visual_match."""
    lines = []
    for scene in manifest.get("scenes", []):
        text = _scene_text(scene)
        if not text:
            continue
        chars = scene.get("characters") or []
        rec = {
            "scene_id": scene.get("id"),
            "role":     _scene_role(scene),
            "speaker":  (chars[0] if len(chars) == 1 else None),
            "text":     text,
        }
        visual = (scene.get("scene_visual") or "").strip()
        if visual:
            rec["visual"] = visual
        lines.append(rec)
    return lines


def _deterministic_findings(manifest: dict) -> list[dict]:
    """Exact rule checks done in code (no LLM): highlight present (R3), visual
    detail (R9), readable length (R12). These are guaranteed catches; the LLM
    pass supplies the actual corrected wording for the scenes it also flags."""
    out = []
    for scene in manifest.get("scenes", []):
        sid  = scene.get("id")
        role = _scene_role(scene)
        text = _scene_text(scene)

        # R3 — every dialog line must highlight at least one word.
        if role == "dialog" and text and not _HIGHLIGHT_RE.search(text):
            out.append({
                "scene_id": sid, "field": "subtitle_text", "rule": "highlight",
                "severity": "warning", "quote": text,
                "issue": "No highlighted vocabulary word (_word_ or *word*).",
                "fixed": "",
            })

        # R9 — a dialog scene's visual must be present and detailed enough.
        if role == "dialog" and "scene_visual" in scene:
            visual = (scene.get("scene_visual") or "").strip()
            if len(visual) < _VISUAL_MIN_CHARS:
                out.append({
                    "scene_id": sid, "field": "scene_visual", "rule": "visual_detail",
                    "severity": "warning", "quote": visual,
                    "issue": "Visual description is missing or too thin to render "
                             "reliably (needs setting, characters, action, mood).",
                    "fixed": "",
                })

        # R12 — a subtitle that is too long to read comfortably on one screen.
        if role in ("dialog", "narration") and len(text) > _SUBTITLE_MAX_CHARS:
            out.append({
                "scene_id": sid, "field": "subtitle_text", "rule": "length",
                "severity": "suggestion", "quote": text,
                "issue": f"Subtitle is long ({len(text)} chars); consider shortening "
                         "for on-screen readability.",
                "fixed": "",
            })
    return out


def _build_prompt(manifest: dict, lines: list[dict], level: str,
                  prompt_override: str | None) -> tuple[str, str]:
    """Return (system_prompt, user_content).

    The review is an INDEPENDENT proofreading pass: it never receives the prompt
    that generated the script (generation_config.prompt_script /
    prompt_repetitions). The model judges the German purely on the rules and the
    actual text; the topic/level/learning-points below are reference only, used
    to check pedagogy (highlight relevance, level fit, narration framing) — not
    instructions the script is assumed to have followed.
    """
    gen  = manifest.get("generation_config") or {}
    info = manifest.get("video_info") or {}

    focus = prompt_override or _RULES_BLOCK

    system = (
        "You are a meticulous native-German editor and CEFR-certified German "
        "teacher reviewing the script of a German-learning video before it is "
        "voiced and animated. This is an independent proofreading pass: you have "
        "NOT been shown how the script was written, so do not assume any wording "
        "is intentional — judge every line on its own merits against the rules "
        "and correct German usage. The project context is reference only (to "
        "check level fit and whether the vocabulary/topic are covered); never "
        "treat it as instructions the script must be presumed to satisfy. "
        f"{_MARKUP_NOTE}\n\n"
        f"{focus}\n\n"
        "Only report genuine problems — do not invent issues to fill the list. "
        "For every fixable problem, provide the full corrected value in `fixed` "
        "(German). Write `issue` and `summary` in English; keep `quote` and "
        "`fixed` in German.\n\n"
        + _OUTPUT_SHAPE
    )

    # Reference context ONLY — deliberately excludes generation_config.prompt_script
    # and prompt_repetitions so the review stays independent of how the script was
    # generated.
    context = {
        "title":            info.get("title"),
        "target_level":     level,
        "provided_context": gen.get("provided_context"),
        "learning_points":  gen.get("provided_learning_points"),
        "words":            gen.get("words"),
        "characters":       gen.get("characters"),
    }
    user = (
        "Review the following German-learning script and reply with the JSON "
        "object described above.\n\n"
        "Reference context (JSON — background only, not instructions to defer to):\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\nScript lines to review (JSON array, in order; `visual` is the "
        "image prompt for that scene):\n"
        + json.dumps(lines, ensure_ascii=False, indent=2)
    )
    return system, user


# GPT sometimes echoes the field name from the review records we feed it (which
# use `text` for the German line and `visual` for the image prompt) instead of
# the manifest field names we ask for. Normalize those aliases so a corrected
# value is still applied to the right manifest field rather than silently dropped.
_FIELD_ALIASES = {
    "text":         "subtitle_text",
    "subtitle":     "subtitle_text",
    "subtitle_text": "subtitle_text",
    "visual":       "scene_visual",
    "scene_visual": "scene_visual",
}


def _normalize_field(field: str) -> str:
    return _FIELD_ALIASES.get((field or "").strip(), (field or "").strip())


def _current_value(scene: dict, field: str):
    if field == "subtitle_text":
        return scene.get("subtitle_text")
    if field == "scene_visual":
        return scene.get("scene_visual")
    return None


def review_manifest(project_name: str, prompt_override: str | None = None) -> dict:
    """Review the project's script with GPT and store the report in the manifest.

    Returns the review dict; also written to manifest["manifest_review"].
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your .env "
            "(see .env.example) and restart the app."
        )

    cfg, manifest_path, manifest = _load_manifest(project_name)
    level = (manifest.get("generation_config") or {}).get("level") or cfg["level"]
    lines = _collect_lines(manifest)
    if not lines:
        raise RuntimeError(
            "No script text found to review. Run 'Generate Script' first."
        )

    report_progress(0, 1, f"Reviewing {len(lines)} lines with GPT…")

    system, user = _build_prompt(manifest, lines, level, prompt_override)
    model = cfg["review_model"]
    logger.info("Reviewing '%s' (%d lines) with %s …",
                project_name, len(lines), model)

    client   = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model           = model,
        messages        = [{"role": "system", "content": system},
                           {"role": "user",   "content": user}],
        response_format = {"type": "json_object"},
        temperature     = 0.2,
    )

    if response.choices[0].finish_reason == "length":
        raise RuntimeError(
            "GPT's review was cut off (too many issues for one pass). Split the "
            "project or switch [review] openai_model to a larger-output model."
        )

    text = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse GPT's review as JSON: {e}") from e

    llm_findings = parsed.get("findings", []) or []

    # Merge with deterministic checks. A scene+field already covered by the LLM
    # (which carries the corrected wording) wins; deterministic findings only
    # fill gaps the model missed so R3/R9/R12 are never silently skipped.
    covered = {(f.get("scene_id"), f.get("field")) for f in llm_findings}
    merged  = list(llm_findings)
    for det in _deterministic_findings(manifest):
        if (det["scene_id"], det["field"]) not in covered:
            merged.append(det)

    scenes_by_id = {s.get("id"): s for s in manifest.get("scenes", [])}

    issues, counts = [], {"error": 0, "warning": 0, "suggestion": 0}
    for f in merged:
        sev   = f.get("severity", "suggestion")
        field = _normalize_field(f.get("field", "general"))
        sid   = f.get("scene_id", "general")
        fixed = (f.get("fixed") or "").strip()
        original = _current_value(scenes_by_id.get(sid, {}), field)
        # A fix is applicable only when we have a real target field, a new value,
        # and that value actually differs from what's in the manifest.
        applicable = bool(
            fixed and field in ("subtitle_text", "scene_visual")
            and sid in scenes_by_id and fixed != (original or "").strip()
        )
        counts[sev] = counts.get(sev, 0) + 1
        issues.append({
            "scene_id":  sid,
            "field":     field,
            "rule":      f.get("rule", "other"),
            "severity":  sev,
            "quote":     f.get("quote", ""),
            "issue":     f.get("issue", ""),
            "original":  original if applicable else None,
            "fixed":     fixed if applicable else "",
            "applied":   False,
        })

    fix_count = sum(1 for i in issues if i["fixed"])
    review = {
        "reviewed_at":    datetime.now().isoformat(timespec="seconds"),
        "model":          model,
        "level":          level,
        "lines_reviewed": len(lines),
        "summary":        parsed.get("summary", ""),
        "counts":         counts,
        "fix_count":      fix_count,
        "issues":         issues,
    }
    manifest["manifest_review"] = review
    _write_manifest(manifest_path, manifest)

    report_progress(1, 1, "Review complete")
    logger.info("Review of '%s' complete: %d error(s), %d warning(s), "
                "%d suggestion(s); %d applicable fix(es).", project_name,
                counts["error"], counts["warning"], counts["suggestion"], fix_count)
    return review


def apply_review_fixes(project_name: str, keys: list[str] | None = None) -> dict:
    """Apply the corrected values from the stored review back into the manifest.

    `keys` is an optional list of "<scene_id>::<field>" selectors; when omitted,
    every not-yet-applied fix is written. A subtitle fix also updates the scene's
    TTS text when the audio hasn't been synthesised yet, so the spoken line stays
    in sync. Returns {"applied": int, "remaining": int}.
    """
    cfg, manifest_path, manifest = _load_manifest(project_name)
    review = manifest.get("manifest_review")
    if not review:
        raise RuntimeError("No review found. Run the review step first.")

    scenes_by_id = {s.get("id"): s for s in manifest.get("scenes", [])}
    want = set(keys) if keys is not None else None

    applied = 0
    for issue in review.get("issues", []):
        fixed = (issue.get("fixed") or "").strip()
        field = issue.get("field")
        sid   = issue.get("scene_id")
        if not fixed or issue.get("applied") or field not in ("subtitle_text", "scene_visual"):
            continue
        key = f"{sid}::{field}"
        if want is not None and key not in want:
            continue
        scene = scenes_by_id.get(sid)
        if not scene:
            continue

        if field == "subtitle_text":
            scene["subtitle_text"] = fixed
            audio = scene.get("audio") or {}
            # Keep the spoken text in sync only while audio hasn't been made yet;
            # once a file exists, changing the text would desync it, so leave it.
            if audio.get("tts_text") is not None and not audio.get("file_path"):
                audio["tts_text"] = fixed
        else:  # scene_visual
            scene["scene_visual"] = fixed

        issue["applied"]    = True
        issue["applied_at"] = datetime.now().isoformat(timespec="seconds")
        applied += 1

    remaining = sum(1 for i in review.get("issues", [])
                    if i.get("fixed") and not i.get("applied"))
    review["fix_count"] = remaining
    _write_manifest(manifest_path, manifest)
    logger.info("Applied %d fix(es) to '%s'; %d remaining.",
                applied, project_name, remaining)
    return {"applied": applied, "remaining": remaining}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python review_manifest.py <project_name> [--apply]")
        raise SystemExit(1)
    if "--apply" in sys.argv[2:]:
        print(json.dumps(apply_review_fixes(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(review_manifest(sys.argv[1]), ensure_ascii=False, indent=2))
