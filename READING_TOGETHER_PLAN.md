# `reading_together` — Implementation Plan

Status: **proposal for review — no code changed yet.**
Decisions locked: one project → many outputs · Playwright/Chromium HTML renderer ·
single narrator voice (v1) · grammar boxes = trennbare verb + TEKAMOLO + Nebensatz/verb-position + existing case/gender.

---

## 1. Goal

A new project type that turns a **public-domain short story** into:

- **Vertical "story" videos**, 6 sentences each, in order → `final_part1.mp4 … final_partN.mp4`
- **One horizontal video** with all sentences → `final_long.mp4`

with **grammar-annotated** on-screen text (boxes + colours) and support for
**animal / non-human characters** created once and reused everywhere.

The old source text is **modernized** (spelling + light rewrite) before use, both for
readability and to keep us clearly clear of any residual copyright in a specific edition/translation.

---

## 2. Where this fits the existing architecture

Reuses, unchanged in spirit:

- Declarative project types in `assets/project_types/project_types.json`
- The flat `scenes[]` manifest model + per-scene MP4 render in `create_video.py`
- fal.ai image generation + character/location compositing (`create_images.py`)
- The job runner (`core.run_job`) and the React pipeline UI

New, because a sentence-stream story is not a two-character dialog:

- A **pre-project stage** (modernize → split → cast characters → annotate)
- A **richer annotation schema** + **two renderers** (HTML/CSS and Ideogram)
- **Single-image characters**
- **Multi-output packaging** (parts + long) in assembly

---

## 3. Data model changes

### 3.1 `characters.json` — single-image characters
Add two optional fields (back-compatible; existing characters ignore them):
```jsonc
"Fuchs": {
  "single_ref": true,                                  // NEW
  "ref_image_file_path": "characters/Fuchs/ref.png",   // NEW — the one reusable image
  "voice_id": "...",                                    // optional (single narrator in v1)
  "fixed_description": "a clever red fox, ...",
  "variable_description": ""
}
```
`build_composite()` gains a branch: if a character is `single_ref`, use `ref_image_file_path`
directly as its reference panel (skip the turnaround / `34left` requirement).

### 3.2 Annotation schema (upgrade `generate_annotations.py`)
Today it returns flat tokens. New shape adds **spans** and **groups** while keeping tokens:
```jsonc
{
  "tokens": [
    {"i": 0, "text": "Gestern", "role": null},
    {"i": 1, "text": "ist", "role": "verb", "group_id": "v1"},
    {"i": 5, "text": "aufgestanden", "role": "verb", "group_id": "v1"}  // trennbar → same colour
  ],
  "spans": [
    {"type": "temporal", "token_ids": [0]},          // TEKAMOLO box
    {"type": "lokal",    "token_ids": [3,4]},
    {"type": "nebensatz","token_ids": [7,8,9,10],
     "verb_final_token_id": 10}                       // Nebensatz box + verb-position marker
  ]
}
```
- `group_id` → trennbare verb halves share one colour.
- `spans[type in temporal|kausal|modal|lokal]` → TEKAMOLO boxes.
- `spans[type=nebensatz]` → subordinate-clause box + a small "verb here" marker on `verb_final_token_id`.
- Existing case/gender/role kept on tokens.
This single object is consumed by **both** renderers.

### 3.3 Manifest — reading fields
`generation_config` gains a `reading` block written by the pre-project stage:
```jsonc
"reading": {
  "raw_text": "...original...",
  "modernized_text": "...",
  "sentences": [
    {"id":"s001","text":"...","characters":["Fuchs"],
     "scene_visual":"...","annotation": { /* schema 3.2 */ }}
  ],
  "sentences_per_part": 6,
  "annotation_renderer": "html"        // html | ideogram | builtin
}
```
`scenes[]` is then built one scene per sentence (narration-style: image + narrator audio +
annotated subtitle), tagged with `_part_index` so packaging knows the groups.

---

## 4. New / changed modules

| File | Change |
|---|---|
| `create_reading_source.py` | **NEW.** GPT modernize → sentence split → cast characters → per-sentence scene_visual + annotation. Writes `generation_config.reading` and builds `scenes[]`. |
| `generate_annotations.py` | **UPGRADE** to the spans/groups schema (3.2). |
| `html_annotation_renderer.py` | **NEW.** Render annotation → HTML/CSS → PNG (Playwright/Chromium) → `ImageClip`. Same drop-in contract as `subtitle_renderer`. |
| `ideogram_annotation_renderer.py` | **NEW.** Build a prompt from the annotation → fal Ideogram → PNG. (Confirm exact fal model slug at build time.) |
| `create_images.py` | `build_composite` handles `single_ref` characters. |
| `manage_characters.py` | Add `add_single_ref_character()` (text-to-image or uploaded ref → one image). |
| `create_video.py` | New `annotation_renderer` selector ("html"/"ideogram"/"builtin"); reading scenes use it. |
| `assemble_video.py` | Emit per-part finals + one long final, driven by `_part_index`. |
| `create_script.py` / `build_scene_list` | Add a `mode: "reading_sentences"` branch (or delegate to the new module) so the dialog schema isn't forced. |
| `assets/project_types/project_types.json` | Add `reading_together` entry (`format: horizontal`, reading rules, renderer default). |

---

## 5. Pipeline (new step order for this type)

```
create_project
  → create_reading_source   (modernize, split, cast characters, annotate)   [NEW]
  → [review/edit in UI]
  → create_audio            (single narrator voice)
  → create_images           (single-ref animals + scene visuals)
  → create_video            (annotated subtitles via chosen renderer)
  → assemble_video          (final_part1..N.mp4  +  final_long.mp4)          [EXTENDED]
  → upload
```

---

## 6. Front-end (React components)

- `Modals.js` — add `reading_together` with its own creation form: large **story-text** textarea,
  level, **sentences-per-part** (default 6), **renderer** choice (HTML / Ideogram).
- New **Reading review** panel (likely in `ProjectView`/a new tab): editable modernized text +
  sentence list, detected characters with **regenerate art**, per-sentence annotation preview with an
  **HTML ↔ Ideogram** compare toggle.
- `PipelineTab.js` — surface the new steps (Modernize & Split, Cast Characters, Annotate, Render Parts, Render Long).
- Backend routes in `routes/pipeline.py` + `routes/projects.py` for the new stage and per-part assembly.

---

## 7. New dependencies

- **Playwright + Chromium** (HTML renderer). One-time `playwright install chromium`.
- Ideogram model is just another fal call — no new package (uses existing `fal_client`).
- A German web font for the HTML renderer (bundle in `assets/fonts/`).

---

## 8. Suggested phasing

1. **Annotation schema + HTML renderer** — standalone, testable on sample sentences (PNG output), no video yet.
2. **Ideogram renderer** — same input, compare output side-by-side.
3. **Pre-project stage** (modernize/split/cast/annotate) + reading scene builder.
4. **Single-image characters** end-to-end.
5. **Multi-output assembly** (parts + long).
6. **Front-end** wiring + review screen.

Each phase is independently demoable.

---

## 9. Risks / things to confirm during build

- **Exact fal Ideogram model slug** (you said "ideogram4"; fal currently exposes Ideogram v3) — verify before wiring step 2.
- **GPT annotation accuracy** for TEKAMOLO/Nebensatz on complex sentences — needs a fallback (skip boxes, keep plain) like the existing renderer already does.
- **Playwright in your run environment** — confirm Chromium can be installed where the pipeline runs.
- **Modernization fidelity vs. safety** — how aggressive the rewrite should be (kept as a tunable prompt).
- **Sentence count not divisible by 6** — last part will have the remainder (1–5 sentences); confirm that's fine.

---

## 10. Verification plan

- Unit-test the annotation schema on a fixed set of German sentences (trennbar, TEKAMOLO, Nebensatz).
- Render the same sentences through both renderers; eyeball PNGs.
- End-to-end on one short public-domain story: confirm part1..N + long all render, characters consistent, narrator audio aligned.
