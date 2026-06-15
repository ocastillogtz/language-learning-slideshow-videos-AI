"""
generate_annotations.py
=======================
Generates grammar annotations for a German sentence using GPT, in the schema
consumed by html_annotation_renderer (see ANNOTATION_SCHEMA.md).

Output shape:
  {
    "text": "<the sentence>",
    "tokens": [ {"text": "...", "case"?, "gender"?, "role"?, "group_id"?}, ... ],
    "spans":  [ {"type": "...", "token_ids": [...], "verb_final"?}, ... ]
  }

This replaces the previous flat-token annotator + PIL renderer. If the model
returns something unusable, generate_annotations() degrades gracefully to a
plain token list (no spans) so the video pipeline never crashes.
"""

import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_MODEL = "gpt-4.1-mini"

VALID_CASES = {"nominative", "accusative", "dative", "genitive"}
VALID_GENDERS = {"masculine", "feminine", "neuter"}
VALID_ROLES = {"verb", "subject", "object"}
VALID_SPAN_TYPES = {"nebensatz"}

_CASE_ALIAS = {"nom": "nominative", "akk": "accusative", "acc": "accusative",
               "dat": "dative", "gen": "genitive", "akkusativ": "accusative",
               "dativ": "dative", "genitiv": "genitive", "nominativ": "nominative"}
_GENDER_ALIAS = {"m": "masculine", "f": "feminine", "n": "neuter",
                 "masc": "masculine", "fem": "feminine", "neu": "neuter"}

_EXAMPLE = json.dumps({
    "tokens": [
        {"text": "Gestern"},
        {"text": "ist", "role": "verb", "group_id": "v1", "infinitive": "sein", "tense": "Perfekt"},
        {"text": "der", "case": "nominative", "gender": "masculine"},
        {"text": "Fuchs", "role": "subject"},
        {"text": "aufgestanden,", "role": "verb", "group_id": "v1", "infinitive": "aufstehen", "tense": "Perfekt"},
        {"text": "weil"}, {"text": "er"}, {"text": "Hunger"},
        {"text": "hatte.", "role": "verb", "infinitive": "haben", "tense": "Präteritum"},
    ],
    "spans": [
        {"type": "nebensatz", "token_ids": [5, 6, 7, 8], "verb_final": 8},
    ],
}, ensure_ascii=False, indent=2)

_PROMPT_TEMPLATE = """
You are a German grammar annotator. Analyse the sentence and return a JSON object
describing it for a learner-facing grammar overlay.

Return ONLY a JSON object with two keys: "tokens" and "spans".

FOCUS — only annotate the grammar that teaches a learner the most. In priority order:
  1. Case: Akkusativ, Dativ and Genitiv are the most important to mark. Mark
     Nominativ only when it usefully contrasts with an object in the sentence;
     otherwise leave it out.
  2. Nebensatz (subordinate clause that sends the conjugated verb to the end).
  3. Verb conjugation (every verb gets role=verb, plus its infinitive and tense).
Annotate these thoroughly and skip incidental details that don't teach one of the
above — a cleaner overlay is better than an exhaustive one.

"tokens": an array, one object per word IN ORDER. Each token:
  - "text": the exact word, including any trailing punctuation
  - "case": nominative | accusative | dative | genitive (focus on accusative,
    dative and genitive; only where it teaches something)
  - "gender": masculine | feminine | neuter (only when a case is given and gender is clear)
  - "role": verb | subject | object (mark every verb as "verb")
  - "group_id": a short shared id (e.g. v1) for BOTH parts of a split separable verb
    (trennbares Verb) so they can be coloured the same. Use only when actually split.
  - "infinitive": for EVERY verb token, the dictionary base form (e.g. "aufstehen",
    "sein", "haben"). This is most useful for Präteritum and Partizip forms that look
    different from the infinitive (e.g. "aufgestanden" -> "aufstehen", "ging" -> "gehen").
    For a split separable verb, give the full infinitive on BOTH parts (e.g. both
    "ist ... aufgestanden" parts get "aufstehen"). Omit on non-verbs.
  - "tense": for EVERY verb token, the conjugation tense in German, one of:
    Präsens, Präteritum, Perfekt, Plusquamperfekt, Futur I, Futur II,
    Konjunktiv I, Konjunktiv II, Imperativ. For a compound tense (Perfekt,
    Plusquamperfekt, Futur, Konjunktiv) give the SAME tense on every part of the
    verb (auxiliary + participle/infinitive). Omit on non-verbs.

"spans": an array of subordinate-clause boxes. ONLY one type exists:
  - "type": "nebensatz" (subordinate clause). Do NOT output any other span type.
  - "token_ids": 0-based indices (matching token order) the box covers. Must be contiguous.
  - "verb_final": 0-based index of the clause-final conjugated verb.

Rules:
- token_ids are 0-based positions in the tokens array.
- Only annotate what is genuinely useful; omit optional fields when unsure.
- Mark a "nebensatz" ONLY when the subordinate clause actually moves the conjugated
  verb to the END of the clause (the contrast with main-clause word order, where the
  verb is in second position). This happens with subordinating conjunctions like
  weil, dass, ob, als, wenn, obwohl, damit, relative pronouns (der/die/das/...), etc.
  Always include "verb_final" pointing at that clause-final conjugated verb. If a
  clause does NOT send the verb to the end (e.g. main clauses, or coordinations with
  und/aber/oder/denn), do NOT emit a span for it.
- A span must be disjoint from, or fully nested inside, another span (no partial overlap).

Example for: Gestern ist der Fuchs aufgestanden, weil er Hunger hatte.
__EXAMPLE__

Sentence:
"__SENTENCE__"
""".strip()


def _build_prompt(sentence):
    return _PROMPT_TEMPLATE.replace("__EXAMPLE__", _EXAMPLE).replace("__SENTENCE__", sentence)


def _clean_tokens(raw):
    out = []
    for t in raw or []:
        if not isinstance(t, dict) or not t.get("text"):
            continue
        tok = {"text": str(t["text"])}
        case = str(t.get("case", "")).lower().strip()
        case = _CASE_ALIAS.get(case, case)
        if case in VALID_CASES:
            tok["case"] = case
        gender = str(t.get("gender", "")).lower().strip()
        gender = _GENDER_ALIAS.get(gender, gender)
        if gender in VALID_GENDERS:
            tok["gender"] = gender
        role = str(t.get("role", "")).lower().strip()
        if role in VALID_ROLES:
            tok["role"] = role
        if t.get("group_id"):
            tok["group_id"] = str(t["group_id"])
        inf = str(t.get("infinitive", "")).strip()
        # only meaningful for verbs; keep it only when this token is a verb
        if inf and tok.get("role") == "verb":
            tok["infinitive"] = inf
        tense = str(t.get("tense", "")).strip()
        if tense and tok.get("role") == "verb":
            tok["tense"] = tense
        out.append(tok)
    return out


def _clean_spans(raw, n_tokens):
    out = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        typ = str(s.get("type", "")).lower().strip()
        if typ not in VALID_SPAN_TYPES:
            continue
        ids = s.get("token_ids")
        if not ids and "start" in s and "end" in s:
            ids = list(range(int(s["start"]), int(s["end"]) + 1))
        ids = [i for i in (ids or []) if isinstance(i, int) and 0 <= i < n_tokens]
        if not ids:
            continue
        # A nebensatz is only worth boxing when it actually moves the conjugated
        # verb to the end, i.e. it has a valid verb_final. Drop any clause without one.
        vf = s.get("verb_final")
        if not (isinstance(vf, int) and 0 <= vf < n_tokens):
            continue
        out.append({"type": typ, "token_ids": sorted(set(ids)), "verb_final": vf})
    return out


def _fallback(sentence):
    return {"text": sentence,
            "tokens": [{"text": w} for w in sentence.split()],
            "spans": []}


# Bump when the prompt/schema changes in a way that should invalidate old caches.
# v3: removed TEKAMOLO spans; nebensatz only when it has a verb_final (verb-end contrast).
# v4: prompt now prioritises akk/dativ/genitiv + nebensatz + verb conjugation.
CACHE_VERSION = 4


def _load_cached(cache_path, sentence):
    """Return a cached annotation iff it exists and matches this sentence + schema
    version; otherwise None. Never raises."""
    try:
        from pathlib import Path
        p = Path(cache_path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if (data.get("_cache_version") == CACHE_VERSION
                and data.get("text") == sentence
                and isinstance(data.get("tokens"), list)):
            return {"text": data["text"], "tokens": data["tokens"], "spans": data.get("spans", [])}
    except Exception as e:
        logger.warning("Ignoring unreadable annotation cache %s: %s", cache_path, e)
    return None


def _save_cached(cache_path, result):
    """Persist a successful annotation next to the rendered PNG. Never raises."""
    try:
        from pathlib import Path
        p = Path(cache_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(result, _cache_version=CACHE_VERSION)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        logger.warning("Could not write annotation cache %s: %s", cache_path, e)


def generate_annotations(sentence, model=DEFAULT_MODEL, cache_path=None, force=False):
    """Return the annotation schema for a German sentence. Never raises.

    If cache_path is given, a previously stored annotation for the *same* sentence
    text (and schema version) is reused instead of calling OpenAI again — so
    re-rendering a video does not re-prompt. Only successful results are cached;
    fallbacks (API failure / unusable output) are never written, so a transient
    error won't get stuck.

    Pass force=True to ignore any cached result and re-prompt OpenAI (the fresh
    result still overwrites the cache). Used by the "redo annotations" controls.
    """
    sentence = (sentence or "").strip()
    if not sentence:
        return _fallback("")

    if cache_path and not force:
        cached = _load_cached(cache_path, sentence)
        if cached is not None:
            return cached

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _build_prompt(sentence)}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.warning("Annotation generation failed for %r -- using fallback: %s", sentence, e)
        return _fallback(sentence)
    tokens = _clean_tokens(data.get("tokens", []) if isinstance(data, dict) else [])
    if not tokens:
        logger.warning("No usable tokens for %r -- using fallback", sentence)
        return _fallback(sentence)
    spans = _clean_spans(data.get("spans", []), len(tokens))
    result = {"text": sentence, "tokens": tokens, "spans": spans}

    if cache_path:
        _save_cached(cache_path, result)
    return result


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "Ich gebe dem Mann das Buch."
    print(json.dumps(generate_annotations(s), indent=2, ensure_ascii=False))
