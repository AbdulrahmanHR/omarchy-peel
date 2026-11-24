# Tool options contract (registry ↔ `peel-tool` ↔ `peel config` ↔ Options card ↔ Panel)

Tools on the Tools wheel take options: how to split a PDF, which pages, the rotation angle, and so on.
One schema file, `registry/tool-options.json`, is read by both `bin/peel` (to store defaults) and
`bin/peel-tool` (to validate and run). Nothing else hard-codes the field list.

## Schema: `registry/tool-options.json`

```json
{
  "version": 1,
  "fields": [
    { "key": "split-pdf.mode", "tool": "split-pdf", "label": "Split", "type": "enum", "default": "each",
      "remember": true,
      "choices": [
        { "value": "each",    "label": "Every page" },
        { "value": "every",   "label": "Every N pages" },
        { "value": "ranges",  "label": "One file per range" },
        { "value": "extract", "label": "Pages into one PDF" } ] },
    { "key": "split-pdf.every", "tool": "split-pdf", "label": "Pages per file", "type": "integer", "default": 2,
      "min": 1, "max": 500, "step": 1, "unit": "", "remember": true,
      "showWhen": { "key": "split-pdf.mode", "in": ["every"] } },
    { "key": "split-pdf.pages", "tool": "split-pdf", "label": "Pages", "type": "pages", "default": "",
      "remember": false, "placeholder": "All pages, or e.g. 1-3, 5, 8-end" }
  ]
}
```

Every field has `key` (`<tool id>.<name>`, or `ask` for the one global field), `tool` (a tool id, or `""`
for global), `label`, `type`, `default` and `remember`. Optional: `description`, `showWhen`
(`{key, in: [values]}`: show only while that field's value is one of `in`), `placeholder`.

Types:

| type | extra keys | value |
|---|---|---|
| `integer` | `min`, `max`, `step`, `unit` | int in range |
| `enum` | `choices: [{value, label}]` | one of the values (ints stay ints) |
| `boolean` | — | `true` / `false` |
| `pages` | `placeholder` | a page selection string, grammar below; `""` means all pages |

`remember: false` fields are per run only: `peel config set` refuses them, the Panel never lists them.

### Fields (v1)

| key | type | default | choices / range | remember |
|---|---|---|---|---|
| `ask` | enum | `split` | `split` (Only Split pages), `always` (Every tool with options), `never` (Never: use saved settings) | yes |
| `split-pdf.mode` | enum | `each` | each, every, ranges, extract (labels above) | yes |
| `split-pdf.every` | integer | 2 | 1–500, shown when mode = every | yes |
| `split-pdf.pages` | pages | `""` | — | **no** |
| `rotate.angle` | enum | 90 | 90 (90° clockwise), 180 (180°), 270 (90° counter-clockwise) | yes |
| `resize-half.scale` | enum | 50 | 25, 50, 75 (labels "25%", "50%", "75%") | yes |
| `compress.level` | enum | `medium` | light, medium, strong | yes |
| `snapshot.at` | integer | 10 | 0–100, step 5, unit `%` (position in the video) | yes |
| `trim-silence.threshold` | enum | -50 | -60, -50, -40 (labels "-60 dB" …) | yes |

`ask` group label in the Panel: "General"; every other field is grouped by its tool's label.

### Page selection grammar (`pages` type)

- Comma-separated items; spaces are ignored. Empty string = all pages.
- Item: `N`, `N-M`, `N-end`, or `end`. `last` is an alias of `end`. N, M are integers ≥ 1.
- `N-M` with N > M is a reversed range (pages M..N in reverse order).
- At most 200 items and 500 characters. Anything else is a syntax error.
- Resolved against a PDF's page count at check/run time; a page past the end is an error
  ("page 14 is past the end (12 pages)").
- The backend resolves the selection to explicit page numbers and builds qpdf ranges from integers
  only. The user's text never reaches an argv.

### Split modes (pages = the resolved selection, or all pages)

| mode | outputs |
|---|---|
| `each` | one PDF per selected page |
| `every` | the selected pages in order, chunked into groups of `split-pdf.every` |
| `ranges` | one PDF per comma item of `pages` (needs a non-empty `pages`) |
| `extract` | one PDF with all selected pages in the given order (needs a non-empty `pages`) |

Output name per file, from its page list: one page → `doc (page 5).pdf`; contiguous ascending →
`doc (pages 1-3).pdf`; anything else → `doc (part K).pdf` (K = 1-based output index). Extract with a
non-contiguous selection → `doc (selected pages).pdf`. More than 2000 outputs is an error.

### Other tools

- `rotate` now also applies to PDFs (all pages, `qpdf --rotate=+ANGLE`), label "Rotate".
- `resize-half` keeps its id; label becomes "Resize", description "Smaller copy (50% by default)".
- `compress.level`: image `-quality` 85 / 75 / 60 with max side 3840 / 2560 / 1920; video CRF (x264)
  23 / 28 / 33, VP9 +10; lossy audio bitrate 160k / 128k / 96k (opus 128k / 96k / 64k);
  PDF `/printer` / `/ebook` / `/screen`. `medium` must equal today's behaviour.
- `snapshot.at`: seconds = duration × at / 100, clamped to `duration − 0.1` so 100% still yields a frame.
- `trim-silence.threshold`: the dB value in both `silenceremove` edges.

## `peel-tool`

```
peel-tool targets --json -- FILE...
  {"tools": [{"id": "split-pdf", "label": "Split pages", "options": ["split-pdf.mode", "split-pdf.every",
              "split-pdf.pages"], "ask": true}, ...]}
peel-tool info --json -- FILE...
  {"files": [{"path": "/abs/doc.pdf", "kind": "pdf", "pages": 12}]}        # pages only for PDFs
peel-tool check --json --tool ID [--opt KEY=VALUE]... -- FILE...
  {"ok": true, "error": "", "outputs": 4, "summary": "4 PDFs: pages 1-3, 4-6, 7-9, 10-12"}
  {"ok": false, "error": "page 14 is past the end (12 pages)", "outputs": 0, "summary": ""}
peel-tool run --tool ID [--opt KEY=VALUE]... [--progress] [--notify] -- FILE...
```

- `options` lists the field keys for that tool (empty list when none); `ask` is true when the card
  should open: `ask` setting `always` and the tool has options, or `split` and the tool is `split-pdf`.
  `never` → false.
- `--opt` keys must belong to `--tool`; values are parsed like `peel config set` (ints for integer and
  int-valued enum fields, `true`/`false`, pages grammar). Unknown key or bad value: exit 1, one-line
  stderr, before any work. `check` with a bad option returns `ok: false` (exit 0) instead.
- An option not given falls back to the saved value (`config.tools`), then the field default.
- `check` never writes a file. With several FILEs the summary describes the first and `outputs` is the
  total; an error on any file is reported as `"<name>: <message>"`.
- `summary` is short plain text for the card (≤ 120 chars, truncate long lists with "…").

## `peel config`

- `config.json` gains `"tools": {}`: a flat map of overrides keyed by field key (absent = default),
  same rules as `advanced` (bad entries warn on stderr and are dropped on load).
- `peel config --json` adds `options.tools` (the schema's `fields`, unchanged) and `effectiveTools`
  (every `remember: true` field: override ?? default).
- `peel config set tools.<key> VALUE`; `default` removes the override; `remember: false` keys and
  unknown keys exit 1 with a one-line message.

## UI

- **Options card** (Catcher overlay): picking a tool whose `ask` is true opens a card at the wheel
  instead of running. It shows the tool label, the file name (or "N files"), the page count for PDFs,
  one row per visible field (enum ≤ 4 choices: chips; more: cycle; integer: − value +; pages: text
  input with the placeholder), the live `check` summary or error, a "Remember these settings"
  checkbox (writes `tools.<key>` for `remember` fields via `setConfig`), and Run / Cancel.
  Prefilled from `effectiveTools`. Enter runs (disabled while `check` says not ok), Esc cancels,
  Tab / Shift+Tab move between controls, arrows change the focused control. Works after a drag drop
  too: the card takes exclusive keyboard focus.
- **Panel**: a "Tool options" disclosure after Advanced, grouped by tool label, listing `remember`
  fields with the same row widgets as Advanced, plus a per-field reset and "Reset all".

## v1.1 additions (round 2)

### Schema
- Optional field key `kinds: ["pdf"]`: the card shows the field only when every selected file is of one
  of these kinds (kinds from `peel-tool info`). The backend ignores the option for other kinds.
- `split-pdf.mode` gains `remove` ("Remove pages": everything except the selection, one PDF, needs a
  non-empty `pages`) and `parts` ("Equal parts": the selection cut into `split-pdf.parts` near-equal
  chunks, earlier chunks get the extra page). Choice order: each, every, parts, ranges, extract, remove.
- `split-pdf.parts`: integer 2–100, default 2, step 1, remember, `showWhen` mode in [parts].
- `split-pdf.folder`: boolean, default false, remember, label "Put files in a folder". When true and a
  run makes more than one file, the outputs go into a new folder `<stem> (split)` (free-named like files:
  `<stem> (split) (1)`) beside the source / in the output folder. On failure the partial outputs and the
  folder (if empty) are removed.
- `rotate.pages`: pages, default "", remember false, `kinds: ["pdf"]`, placeholder "All pages".
  PDFs only: rotates just the selected pages (`qpdf --rotate=+A:RANGE`, RANGE built from ints).

### Grammar additions
- Items `odd` and `even` (all odd / even pages of the document).
- Step suffix on ranges: `N-M:K` / `N-end:K` (every K-th page of the range, K ≥ 1). Reversed ranges
  step downwards.
- A selection may resolve to at most 10000 page references; more is an error in both `check` and `run`.
- Descending runs are emitted to qpdf as `a-b` ranges (qpdf accepts reversed ranges), never page by page.
  Summaries print runs as `10-1`, never `10+9+8…`.

### Behaviour fixes
- `targets`: `ask` is true for `split-pdf` whenever the saved mode is `ranges`, `extract` or `remove`
  (they need pages), whatever the `ask` setting says.
- `check` for compress on lossless audio returns `ok: false`, error "lossless audio, nothing to compress".
- SIGTERM/SIGINT during `run` exit through the normal cleanup (no partial outputs left).
- `run()` turns `OSError` from `Popen` into a per-file error; the `finished` event is always emitted.
- gs gets a `-sOutputFile` with no `%` from the directory path (run in the output dir with a relative
  temp name, or escape `%` as `%%`).

### UI additions
- Card: an output-count line in the warn colour when `check` says `outputs > 50` ("Makes N files").
- Card: quick-pick chips under any `pages` box: All · Odd · Even (they set the text to "", "odd", "even").
- Card: Enter pressed while a check is pending runs as soon as that check returns ok.
- Wheel: segments whose `ask` is true show a small "…" after the label. Keyboard mode: Shift+Enter opens
  the card for any tool segment with a non-empty `options`, even when `ask` is false.

## v1.2 additions: Merge PDFs controls

### Order
The merge order is the order of the FILE arguments. The card shows the files as a list the user can
reorder; Run passes the files in the shown order. No option carries the order.

### Fields
- `merge-pdf.mode`: enum, default `append`, remember. Choices: `append` ("One after another"),
  `insert` ("Insert into the first PDF").
- `merge-pdf.at`: integer 0–99999, default 0, step 1, remember **false**, `showWhen` mode in [insert],
  label "After page", description "0 puts them before page 1". Validated against the first PDF's
  (selected) page count at check/run time: "page 40 is past the end of a.pdf (12 pages)".
- `merge-pdf.pages`: type `pages`, default "", remember false, new schema key `perFile: true`.
  On the CLI it is given per file as `--opt merge-pdf.pages.<i>=SPEC`, `<i>` = 1-based position in
  the FILE list. Empty / absent = all pages of that file. Same grammar as split.
  The card does not render a perFile field as a normal row; it renders it inside the file list.

### Semantics
- `append`: file 1's selected pages, then file 2's, … in order.
- `insert`: the first file is the base. Its selected pages are kept; all other files' selected pages,
  in order, go in after the `at`-th page of the base's selection (0 = before its first page).
- Output name stays `<first file stem> (merged).pdf`. qpdf argv built from ints only, as for split
  (file paths absolute, so `@`/`-` names stay safe). 10000-reference cap counts all files together.
- `check` summary examples: "1 PDF, 17 pages from 3 files" / "1 PDF, 17 pages: 5 inserted after page 3
  of a.pdf". Errors name the file: "b.pdf: page 9 is past the end (4 pages)".

### Ask
- The `ask` choice `split` is replaced by `pdf` ("Split and Merge PDFs"), the new default: the card
  opens for `split-pdf` and `merge-pdf`. `always` and `never` unchanged. A saved `split` value loads
  as `pdf` (no warning).

### Card
- For `merge-pdf` the card shows a "Files" list under the header: one row per file with position,
  name (elided, PlainText), its page count from `info`, a compact pages box (placeholder "All"),
  and ↑ / ↓ buttons. Keyboard: Up/Down move between rows, Alt+Up / Alt+Down (also Ctrl+Up/Down) move
  the focused file, Tab enters the row's pages box. Chips above the list: "Name A→Z" and "Reverse".
- The `merge-pdf.mode` chips and, in insert mode, the "After page" stepper (max = first file's page
  count once known) sit below the list. Reordering re-runs `check`, since the base file changes.
