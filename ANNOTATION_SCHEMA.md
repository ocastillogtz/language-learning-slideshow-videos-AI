# Grammar annotation schema

The single JSON shape consumed by **both** annotation renderers (the HTML/CSS
renderer now, the Ideogram-via-fal renderer later). Produced per sentence by the
upgraded `generate_annotations.py` (a later phase); for now it is hand-authored
in `html_annotation_renderer.demo_cases()` for testing.

```jsonc
{
  "text": "Gestern ist der Fuchs früh aufgestanden, weil er Hunger hatte.",

  "tokens": [
    {"text": "Gestern"},
    {"text": "ist",          "role": "verb", "group_id": "v1"},
    {"text": "der",          "case": "nominative", "gender": "masculine"},
    {"text": "Fuchs",        "role": "subject"},
    {"text": "früh"},
    {"text": "aufgestanden,", "role": "verb", "group_id": "v1", "infinitive": "aufstehen"},
    {"text": "weil"}, {"text": "er"}, {"text": "Hunger"},
    {"text": "hatte.",       "role": "verb", "infinitive": "haben"}
  ],

  "spans": [
    {"type": "temporal",  "token_ids": [0]},
    {"type": "modal",     "token_ids": [4]},
    {"type": "nebensatz", "token_ids": [6,7,8,9], "verb_final": 9}
  ]
}
```

## tokens[]
| field | meaning | rendering |
|---|---|---|
| `text` | the word exactly as written (incl. trailing punctuation) | the word |
| `i` | optional explicit index; defaults to list order | — |
| `case` | `nominative` / `accusative` / `dative` / `genitive` (or `nom`/`acc`/`dat`/`gen`) | coloured label above the word |
| `gender` | `masculine` / `feminine` / `neuter` (or `masc`/`fem`/`neu`) | appended to the case label (`DAT · m`) |
| `role` | `verb` / `subject` / `object` | `verb` → bold; others → label above |
| `tense` | (verbs) conjugation tense, e.g. `Präteritum`, `Perfekt`, `Konjunktiv II` | small grey label **above** the word |
| `infinitive` | (verbs) dictionary base form, e.g. `aufstehen` for `aufgestanden` | shown in italics **below** the word when it differs from the conjugated form |
| `group_id` | links separable-verb parts (any shared string) | all members share one colour + underline |
| `bold` | force bold | bold |

The `tense` (above) and `infinitive` (below) together let a learner read the
conjugation in context, the tense it's in, and the base form to look up — e.g.
`Perfekt` over `aufgestanden` over `aufstehen`. The infinitive is only rendered
when it differs from the word itself, so present-tense forms equal to the
infinitive add no clutter.

Every word reserves equal vertical space above and below, so the main word stays
on a single consistent centre line whether or not it carries a tense label or an
infinitive — words with extra annotations no longer sit higher or lower than
their neighbours. Accepted `tense` spellings are normalised (e.g. `imperfekt` →
`Präteritum`, `partizip` → `Partizip II`); unknown strings are shown as given.

## spans[]
Subordinate-clause boxes. Each span covers a **contiguous** token range. The
**only** span type is `nebensatz`, and it is boxed **only when the clause moves
the conjugated verb to the end** (it must carry a `verb_final`). The old TEKAMOLO
fields (temporal / kausal / modal / lokal) are no longer annotated or drawn.
| field | meaning |
|---|---|
| `type` | `nebensatz` (only) |
| `token_ids` | list of token indices the box covers (min..max used as the range) |
| `start` / `end` | alternative to `token_ids` — inclusive range |
| `verb_final` | **required** — index of the clause-final conjugated verb → gets a "↳ Verb" marker. A span without one is dropped. |

The point of the box is the **verb-position contrast**: subordinate clauses
(weil, dass, ob, als, wenn, relative pronouns, …) send the verb to the end,
unlike main-clause word order. Clauses that don't move the verb (and coordinations
with und / aber / oder / denn) are not boxed.

Boxes may **nest** (a Nebensatz inside another Nebensatz) or be disjoint. A span
that **partially overlaps** another (neither contains the other) is dropped with a
warning so the HTML stays valid.

## Colours (defaults, all configurable in `DEFAULT_STYLE`)
- Case labels: NOM green · ACC red · DAT blue · GEN purple
- Nebensatz: teal, dashed border
- Separable-verb groups: amber → pink → violet → cyan → lime (cycled)

## Output contract
`render_annotation_png(annotation, out_path, horizontal=False)` writes a
**transparent PNG** (white text, dark outline) sized to the wrap width — the same
drop-in contract as `subtitle_renderer.create_annotated_subtitle`, so it plugs
straight into `create_video.py`.

## Sizing the text to the canvas
The wrap width is set per orientation: `max_width_px` is `980` (vertical) and
`1640` (horizontal, via `HORIZONTAL_STYLE_OVERRIDES`), and the words sit in a
`flex-wrap` row, so a sentence simply wraps onto more lines when it runs out of
width. Height is not fixed — the PNG grows to fit however many wrapped rows
result.

Three ways to control size, from coarse to fine:
- `horizontal=True/False` — picks the orientation preset (width + base word size).
- `font_scale=<float>` — the general "make everything bigger/smaller" knob.
  Multiplies the word *and* every label (tense, case/gender, infinitive, box
  labels), plus gaps, padding and outline, all together. The wrap width
  (`max_width_px`) is deliberately left unscaled so text still wraps to the
  target canvas. Resolution order: defaults → horizontal → `style` → `font_scale`.
- `style={...}` — override any single key, e.g. `style={"word_size_px": 72}` or
  `style={"max_width_px": 1200}`.

All three are accepted by `render_annotation_html`, `render_annotation_png`, and
`AnnotationBatchRenderer`. Example: `render_annotation_png(ann, "out.png",
horizontal=True, font_scale=1.25)`.
