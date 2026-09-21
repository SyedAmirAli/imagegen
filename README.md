# imagegen

One reusable CLI for batch image generation. Point it at a folder of prompts and
it drives a real, signed-in session — Ideogram or Recraft — in Chrome, one image
at a time, one tab — saving every result as a PNG at the path its prompt asks for.

It is built to be interrupted. Progress is written after every single image, so a
crash, a `Ctrl-C` or a closed browser costs at most the image in flight. Rerun the
identical command and it continues from exactly where it stopped.

```bash
pip install imagegen-cli

imagegen run      ~/my-images        # a folder of Markdown prompts
imagegen run      ~/batch.json       # …or a single JSON manifest
imagegen run      ~/batch/*.json     # …or several, as one resumable batch
imagegen status   ~/my-images        # how far along am I
imagegen validate ~/my-images        # parse everything, report problems
imagegen init     ~/my-images        # scaffold a prompt folder
imagegen convert  ~/batch.json ~/my-images   # JSON → prompt folder
imagegen spec                        # brief that turns an idea into either
```

**Two input formats, both first class.** A folder of Markdown prompt files, or a
single JSON manifest holding the whole batch — including where the images go.
The JSON route exists because that is what an AI chat can actually hand you: one
document with four hundred entries, rather than four hundred files in a tree. See
[§5](#5-json-manifests).

Have an idea or a chat discussion rather than either? Hand
[`AUTHORING.md`](AUTHORING.md) to any AI and it writes the batch for you — see
[§6](#6-from-an-idea-to-a-batch).

---

## Contents

1. [Install](#1-install)
2. [The prompt folder](#2-the-prompt-folder)
3. [Prompt file structure](#3-prompt-file-structure)
4. [Folder-level settings: `imagegen.yaml`](#4-folder-level-settings-imagegenyaml)
5. [JSON manifests](#5-json-manifests)
6. [From an idea to a batch](#6-from-an-idea-to-a-batch)
7. [Where output goes](#7-where-output-goes)
8. [Backgrounds and transparency](#8-backgrounds-and-transparency)
9. [Resuming, retrying, skipping](#9-resuming-retrying-skipping)
10. [Command reference](#10-command-reference)
11. [Chrome and the web session](#11-chrome-and-the-web-session)
12. [Adding another generator](#12-adding-another-generator)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Install

```bash
pipx install imagegen-cli          # or: python3 -m pip install imagegen-cli
imagegen --version
```

The command is `imagegen`; `imagegen-cli` is installed as an alias, so every
example in this README works under either name. `pipx` is the better choice for
a CLI — it gets its own virtualenv and stays off your system Python, which also
sidesteps the "externally managed environment" error on Debian and Ubuntu.

Playwright's browser bundle is only needed if you want the tool to drive its own
Chromium rather than one already on the machine:

```bash
python3 -m playwright install chromium
```

Nothing else is needed. The tool launches its own Chrome when the debugging port
is not already live.

### From a git checkout

```bash
git clone git@github.com:SyedAmirAli/imagegen.git
cd imagegen
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/imagegen run ~/my-images
```

`./imagegen-cli` at the repo root runs the same code without installing anything,
as long as the dependencies are importable.

### Platforms

Linux, macOS and Windows. There is nothing platform-specific in the pipeline —
paths, the progress file and the lock are all handled natively on each — and the
test suite runs on all three in CI.

Two Windows notes:

- Use **Windows Terminal or PowerShell 7** if you want the live progress line.
  The legacy `cmd.exe` console cannot render ANSI, so the tool detects that and
  falls back to plain output rather than printing escape codes at you.
- Chrome is found automatically at its usual install locations (`Program Files`,
  `%LOCALAPPDATA%`) even though it is not on `PATH`. Pass `--chrome-binary` if
  you keep it somewhere unusual.

---

## 2. The prompt folder

A prompt folder is any directory containing one Markdown file per image. Nesting
is free-form — subfolders are how you group a batch, and they are mirrored into
the output folder by default.

```
my-images/                      ← you pass THIS path to the CLI
├── imagegen.yaml               ← optional: settings shared by every prompt
├── README.md                   ← ignored (docs are never treated as prompts)
├── 01-logo/
│   ├── 001-symbol.md           ← one image
│   └── 002-wordmark.md         ← one image
└── 02-portraits/
    ├── 001-founder.md
    └── 002-team.md
```

**Which files are read.** Every `.md`, `.markdown` and `.txt` file under the
folder, sorted by path — that sort order is also the generation order, so number
your files if the sequence matters.

**Which files are ignored.**

| Ignored | Why |
|---|---|
| `INDEX.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `LICENSE.md`, `TODO.md`, `NOTES.md` | documentation that lives next to prompts |
| anything starting with `.` or `_` | drafts and partials |
| `imagegen.yaml` / `_defaults.yaml` | the folder's own config |
| everything inside the output folder | so a run never feeds on its own results |
| globs listed under `exclude:` in `imagegen.yaml` | your own exclusions |

Run `./imagegen-cli validate <folder>` any time to see exactly what was picked up
and what failed to parse. It reads only — it never generates anything.

---

## 3. Prompt file structure

A prompt file is YAML front-matter (the settings) followed by the prompt text
(the body):

```markdown
---
id: portrait-founder                # optional
output: 02-portraits/founder.png    # optional
size: 2048x2048                     # optional
aspect: "1:1"                       # optional
background: transparent             # optional
negative: "watermark, text, blurry" # optional
---
A polished studio portrait of a smiling woman in her thirties wearing a navy
blazer, three-quarter view, soft key light from the left, crisp clean edges,
photorealistic, subject fully isolated on a completely transparent background,
no backdrop, no ground shadow, no scenery.
```

### The fields

| Field | Required | Meaning |
|---|---|---|
| `id` | no | Stable identifier used for progress tracking and `--only`. **Defaults to the file's path without its extension** (`02-portraits/001-founder`). Must be unique in the folder. Keep it a slug — it also names the debug screenshots. |
| `output` | no | Where the PNG is written, **relative to the output folder**. Defaults to a slugified version of the prompt's own path, which mirrors your prompt tree into the output tree. Must end in `.png` — see [file naming](#file-naming). |
| `size` | no | Final pixel size, `WIDTHxHEIGHT`. Omit to keep whatever the generator produces natively. The image is only ever downscaled to this; see `--allow-upscale`. |
| `aspect` | no | Ratio requested from the generator, e.g. `"1:1"`, `"3:4"`, `"16:9"`. Quote it — bare `16:9` is not valid YAML. Derived from `size` when omitted. A ratio the generator does not offer is snapped to the nearest one it does, and the substitution is logged. |
| `background` | no | `transparent`, `opaque`, or omitted. This is an instruction to *you and the tool*, not to the model — put the actual wording in the prompt too. See §8. |
| `negative` | no | Things to avoid. Ideogram's composer has no separate negative field, so this is appended to the prompt as `NEGATIVE PROMPT (avoid entirely): …` unless that text already appears in the prompt. Recraft has a real "Negative prompt" field (shown once a concrete `--recraft-model` is selected — "Auto" has none) and uses that instead; it only falls back to the Ideogram-style append when that field isn't on screen. |

Any other key you add is preserved and passed through to the backend, so a future
backend can read `model:`, `seed:` or `style:` without changing the core.

### The body

Everything after the front-matter is the prompt. If the body contains a fenced
code block, **the first fenced block wins** and the surrounding prose is dropped:

````markdown
---
id: 001-symbol
---
## Notes for humans
This asset must match the brand mark. Not sent to the generator.

## PROMPT
```text
A rounded abstract knowledge symbol, soft 3D forms, deep indigo and cyan,
transparent background.
```
````

That is what lets a prompt file double as documentation without leaking headings,
checklists and commentary into the generator.

### File naming

Output paths are filenames you will type, glob and script against, so they are
held to a slug convention: **lowercase letters, digits and dashes**, one segment
per folder level, ending in `.png`.

When you leave `output:` out, the path is derived from the prompt file and
slugified automatically — `02-portraits/My Logo #2 (final).md` becomes
`02-portraits/my-logo-2-final.png`. Name your prompt files cleanly and you never
have to think about it.

When you do set `output:` yourself it is taken as written, but checked:

| You write | Result |
|---|---|
| `02-portraits/founder.png` | accepted |
| `02-portraits/founder` | accepted, `.png` appended |
| `Section One/My Icon.png` | accepted with a **warning** — your path, your call, but it is awkward to type |
| `founder.jpg` | **rejected** — every image is written as PNG, so any other extension is a lie about the file |
| `../../elsewhere.png` | **rejected** — escaping the output folder scatters images where a resume can never find them again |
| `/home/me/founder.png` | **rejected** — absolute paths ignore `--out` |

Two prompts sharing one `output` path are rejected as well; without that check
the second image silently overwrites the first and the run still reports success.

### Legacy files without front-matter

Existing hand-written libraries keep working untouched. A file with no
front-matter is parsed for `**Asset ID:**`, `**Output file:**`, `**Size:**`,
`**Aspect:**` and `**Background:**` bold fields plus a `## PROMPT` fenced block
and an optional `## NEGATIVE PROMPT` block. A 541-file library in that format
loads with zero edits.

---

## 4. Folder-level settings: `imagegen.yaml`

Put shared settings in one file at the root of the prompt folder instead of
copy-pasting them into 500 prompts. Anything a prompt file sets wins over these.

```yaml
# ~/my-images/imagegen.yaml

defaults:                   # defaults for every prompt file's front-matter
  size: 2048x2048
  aspect: "1:1"
  background: transparent
  negative: "watermark, text artifacts, distorted anatomy"
  prompt_prefix: |          # prepended to every prompt — a shared style block
    Premium casual game illustration, soft 3D forms, rounded geometry,
    consistent studio lighting across the whole set.
  prompt_suffix: |          # appended to every prompt
    Clean anti-aliased edges, production ready.

exclude:                    # extra globs that are not prompts
  - "drafts/*.md"
  - "*-wip.md"

options:                    # default CLI flags for this folder
  chrome_profile: ~/.chrome-ideogram-automation
  force_background_removal: true
  max_file_size: 1200       # compress anything above 1200 KB
  min_gap: 6
  max_gap: 12
```

`options:` accepts any long flag from `run` with dashes turned into underscores
(`--force-background-removal` → `force_background_removal`). A flag you actually
type on the command line always beats the file, and applied config values are
printed at the start of each run so there is no hidden state.

One caveat worth knowing: a file that declares its own `size` but no `aspect`
derives the aspect from that size rather than inheriting the folder default —
otherwise a `640x480` prompt would silently be generated as `1:1`.

---

## 5. JSON manifests

A prompt folder is not the only input. `run`, `status` and `validate` all accept
a **single JSON file** describing the whole batch, and use it directly — no
intermediate folder, no conversion step:

```bash
./imagegen-cli run ~/batches/premium-humans.json
```

This is the format to ask an AI for. A chat session can comfortably produce one
JSON document with four hundred entries; it cannot hand you four hundred
Markdown files in a directory tree.

```json
{
  "project": "Premium Humans",
  "output_dir": "premium-humans",
  "defaults": {
    "size": "2048x2048",
    "background": "transparent",
    "negative": "watermark, text, extra fingers",
    "prompt_suffix": "crisp clean edges, isolated on a transparent background."
  },
  "options": { "max_file_size": 1200 },
  "images": [
    {
      "id": "01-001-founder",
      "output": "01-portraits/founder.png",
      "prompt": "A smiling founder in a navy blazer, three-quarter view…",
      "aspect": "3:4"
    },
    {
      "id": "02-001-team",
      "output": "02-groups/team.png",
      "size": "1920x1080",
      "background": "opaque",
      "prompt": "Five colleagues standing together…"
    }
  ]
}
```

### Top-level keys

| Key | Meaning |
|---|---|
| `images` | **Required.** The list of images. `assets`, `items`, `prompts` and `entries` are accepted as aliases, and a bare top-level array works too. |
| `output_dir` | Where images are written, **relative to the JSON file itself** so the manifest stays portable. Absolute paths are allowed. Defaults to `<json-file-folder>/output`, and `--out` overrides it. When several manifests run together and want different folders, this becomes the manifest's subfolder under the run's output root (see [§5](#several-manifests-one-batch)). |
| `defaults` | Applied to every image, same fields as a folder's `imagegen.yaml` `defaults:` — `size`, `aspect`, `background`, `negative`, `prompt_prefix`, `prompt_suffix`. Unknown keys are ignored, so manifests carrying metadata for other tools load fine. |
| `options` | Default CLI flags for this batch, e.g. `{"max_file_size": 1200, "flat": true}`. Flags you type still win. |
| anything else | Ignored. `project`, `generated_at`, `sections` and friends are yours to keep. |

### Per-image keys

Same meanings as the front-matter fields in [§3](#3-prompt-file-structure):
`id`, `output`, `prompt`, `negative`, `size`, `aspect`, `background`. Only
`prompt` is truly required — `id` falls back to the entry's position and
`output` can be assembled from `folder` + `filename`.

Aliases are accepted so existing manifests load unchanged:

| Canonical | Also accepted |
|---|---|
| `output` | `output_file`, `relative_path`, `path`, `file`, or `folder` + `filename` |
| `size` | `dimensions`, or a `width` + `height` pair |
| `aspect` | `aspect_ratio`, `aspectRatio`, `ratio` |
| `negative` | `negative_prompt`, `negativePrompt` |
| `background` | `transparent_background: true/false`, `transparent: true/false` |
| `id` | `asset_id`, `key`, `slug` |

Output paths get the same safety checks as everywhere else: relative, inside the
output directory, `.png`, and unique. A bad entry is reported with its position
(`batch.json[7]: no prompt text`) and the rest of the batch still runs.

### Several manifests, one batch

A chat session that plans 700 images usually hands them over in chunks — one
file per hundred. Pass them all at once; they run as a single batch, in the
order given:

```bash
./imagegen-cli run ~/batches/from-*.json
./imagegen-cli status ~/batches/from-*.json
```

```
imagegen 1.0.0  ·  ideogram  ·  /home/me/batches  (7 sources)
source   from-1-100.json
…
prompts  700 total, 700 new
```

The rules:

- **Manifests that agree on an `output_dir` write straight into it.** Seven
  chunks of one 700-image set are one set of images, and splitting them into
  seven folders would be wrong.
- **Manifests that disagree keep the structure each one declares**, side by side
  under the run's output folder. Twenty-five game batches, each asking for its
  own folder, give you exactly the tree you would get from running them one at a
  time — in one resumable run:

  ```bash
  ./imagegen-cli run ~/prompts/batch-*.json -o ~/game/assets
  ```

  ```
  output   /home/me/game/assets  (one subfolder per source)
  source   batch-01-core.json  →  batch-01-core/
  source   batch-02-bubble.json  →  batch-02-bubble/
  ```

  ```
  ~/game/assets/batch-01-core/01-mascots/mascot-blue.png
  ~/game/assets/batch-02-bubble/01-bubbles/bubble-blue.png
  ```

  `-o/--out` names the root. Without it the root is the folder the manifests
  live in, which reproduces what running them separately would have written.
  Two manifests naming the same folder (both `"output_dir": "images"`) would
  merge back together, so both fall back to their file names instead.
- **One progress file**, in the run's output folder, so a resume covers the
  whole batch. Interrupt at image 430 of 700 and the next run picks up there.
- **Ids and output paths must be unique across all the files** — within a shared
  folder. A second file reusing an id or a filename has that entry reported and
  skipped; the rest of the file still runs. Where each source has its own
  subfolder this barely applies: the images are in different folders, and a
  shared id is qualified with the subfolder on *both* sides (`batch-01/star`,
  `batch-02/star`) rather than one image being dropped.
- **`defaults` stay per-file** — each manifest's `prompt_suffix`, `size` and so
  on apply only to its own images, so chunks written at different times keep
  their own wording. Only `options` merge, last file wins.
- `--flat` applies across the whole batch — subfolders and all — so a name
  shared by two manifests is renamed apart the same way it would be within one.

### Converting to a prompt folder

If you would rather hand-edit the prompts as Markdown, or keep them in version
control as separate files, convert once and work in the folder afterwards:

```bash
./imagegen-cli convert ~/batches/premium-humans.json ~/prompts/premium-humans
./imagegen-cli run ~/prompts/premium-humans
```

Each image becomes one Markdown file laid out to mirror the image it produces
(`01-portraits/founder.png` → `01-portraits/founder.md`), with the settings in
front-matter. Existing files are kept unless you pass `--force`. Both routes are
equivalent: converting the 541-asset manifest and loading the result produces
jobs identical to reading the JSON directly, field for field.

---

## 6. From an idea to a batch

You do not have to write either format by hand. If you have an idea, a design
brief, or a chat session where you worked out what the images should be, hand that
plus [`AUTHORING.md`](AUTHORING.md) to any AI and let it produce the batch.

```bash
./imagegen-cli spec | xclip -selection clipboard   # Linux
./imagegen-cli spec | pbcopy                       # macOS
./imagegen-cli spec > brief.md
```

The brief asks for **one JSON manifest** by default — the format a chat can
realistically deliver in a single message. Save what it produces and run it. If
you would rather have editable Markdown, ask it for a prompt folder instead, or
convert the JSON afterwards with `convert`; the brief documents both.

It also covers the field rules, naming conventions, how to keep a set visually
consistent, and the wording that actually produces transparent cut-outs.

Then check its work before spending generations:

```bash
./imagegen-cli validate ~/batch.json           # every entry parses?
./imagegen-cli run ~/batch.json --dry-run      # right count, right paths?
./imagegen-cli run ~/batch.json --limit 3      # smoke test three images
```

`validate` and `--dry-run` never open a browser and never write anything, so
they are free to run as often as you like.

---

## 7. Where output goes

By default the output folder is `<prompt-folder>/output`. Override it with
`-o/--out`, which is what you want when the prompt library lives in a repo and
the images should not:

```bash
./imagegen-cli run ~/my-images -o ~/Pictures/my-images-render
```

Inside the output folder:

```
output/
├── 01-logo/
│   └── 001-symbol.png          ← mirrors the prompt tree, or wherever `output:` said
├── 02-portraits/
│   └── founder.png
└── .imagegen/                  ← everything the tool needs to resume
    ├── progress.json           ← the source of truth: per-item status, errors, notes
    ├── run.log                 ← full history of every run against this folder
    ├── run.lock                ← present only while a run is in progress
    └── debug/                  ← screenshots of failed attempts, named <id>_a<N>.png
```

### One flat folder instead of categories

The subfolders exist because a few hundred images are easier to browse that way,
but some consumers want the opposite — an asset loader that globs a single
directory, a sprite packer, a bulk upload form. `--flat` writes every image
straight into the output folder:

```bash
./imagegen-cli run ~/my-images --flat
```

```
output/
├── 001-symbol.png
├── founder.png
└── .imagegen/
```

Only the filename is kept, so names that were unique thanks to their folders can
now collide — `icons/star.png` and `badges/star.png` are both `star.png`. When
that happens, *every* member of the colliding set is renamed to its full path
joined with dashes (`icons-star.png`, `badges-star.png`); the ones that do not
collide keep their plain filename. The rule does not depend on read order, so
adding a new prompt never renames an image already on disk.

`--flat` also applies to `status` and `validate`, and can be set once per batch
as `flat: true` under `options:` in `imagegen.yaml` or a manifest.

> Flat and nested layouts do not share state. If you switch `--flat` on for a
> batch you already generated, point `-o` at a fresh output folder — otherwise
> the run finds none of the old files under their new names and regenerates
> everything.

Images are written to a `.part` file and moved into place only once complete, so
an interrupted download can never leave a truncated PNG that a later run would
mistake for a finished one.

`progress.json` is plain, readable JSON — one entry per id with its status,
attempt count, timestamps, the last error, the provider's image id, and notes
such as `background removed (rembg)` or `kept native 1024x1024`.

### Keeping file size down

Transparent PNGs from a 2K generator are big — 4-5 MB each is normal, and 500 of
them is over 2 GB. `--max-file-size` compresses anything above a limit you set,
**without ever changing the resolution**:

```bash
./imagegen-cli run ~/my-images --max-file-size          # limit = 1200 KB (the default)
./imagegen-cli run ~/my-images --max-file-size 800      # limit = 800 KB
./imagegen-cli run ~/my-images                          # no compression at all
```

Or set it once per folder in `imagegen.yaml`:

```yaml
options:
  max_file_size: 1200
```

Images already under the limit are left untouched, bit for bit. Anything over it
is reduced by shrinking the colour palette, starting from the highest quality
that fits rather than jumping to the smallest, and the resulting size and colour
count are recorded as a `note:` and in `progress.json`:

```
  ✓  1728x2304  transparent  853KB  34s
  · compressed 5300KB -> 853KB at 1728x2304 (palette, 256 colours)
```

Real results from 2K portraits with the 1200 KB default: 3961 KB → 571 KB,
4912 KB → 809 KB, 5300 KB → 853 KB, all at their original pixel dimensions and
with transparency intact.

Two things worth knowing:

- **Results usually land well under the limit.** PNG's only lossy lever is the
  colour palette, which caps at 256 entries; the next quality tier up is full
  truecolour, which is the 4 MB file you started with. So there is nothing
  between "about 600-900 KB" and "4 MB", and the tool takes the best one that
  fits rather than padding up to your number.
- **Install `pngquant` for better-looking results.** When it is on your `PATH` it
  is used instead of the built-in quantizer — same size, noticeably better
  gradients and edges, because it dithers. Without it, Pillow's octree quantizer
  is used, which is still visually very close on photographic subjects but flatter
  in smooth areas.

  ```bash
  sudo apt install pngquant       # Debian/Ubuntu
  brew install pngquant           # macOS
  ```

Compression runs after background removal, so a cut-out is compressed with its
alpha already in place. Transparency survives — it moves into the palette, which
is why a compressed file reports mode `P` rather than `RGBA`.

---

## 8. Backgrounds and transparency

**The prompt is the source of truth.** By default, whatever the generator returns
is exactly what gets saved. If your prompt asks for a transparent background,
Ideogram's own alpha channel is used untouched — no cleanup, no second-guessing.

Write the transparency into the prompt text itself. This phrasing reliably
produced a real alpha channel:

> …crisp clean edges, photorealistic, high detail, subject fully isolated on a
> completely transparent background, no backdrop, no ground shadow, no scenery.

`--force-background-removal` is the safety net for images that come back opaque
anyway. It checks before it acts:

1. Image already has a real alpha cut-out → **left completely alone.**
2. Prompt says `background: opaque` → **never stripped**, even when forced.
3. Otherwise → background removed, via `rembg` when installed, else a
   border-seeded flood fill.

The flood fill is seeded only from the frame edges, so an interior region that
happens to match the backdrop colour (a white shirt, a bright highlight) keeps
its pixels. When it finds no flat backdrop and `rembg` is unavailable, it leaves
the image exactly as generated and says so rather than mangling the subject.

`rembg` is optional and heavy. Install it in a venv when you need general
(non-flat) background removal:

```bash
.venv/bin/pip install rembg
```

Every decision is recorded per item in `progress.json` and printed as a `note:`.

---

## 9. Resuming, retrying, skipping

- **Already-generated items are skipped.** Rerunning the same command is always
  safe and always cheap.
- **Deleting `progress.json` is safe.** The next run adopts every image already
  on disk as done and queues only the rest.
- **Deleting an image regenerates it.** Reconciliation runs both ways, so
  removing a PNG you were not happy with re-queues exactly that one on the next
  run. `--no-reconcile` opts out of both directions.
- **Failures are kept, not lost.** An item that fails all its attempts is marked
  `failed` with its error and a screenshot in `.imagegen/debug/`. Re-queue them
  with `--retry-failed`. With `--after-item-fail-pause` (or a rotate URL) the
  same item is **not** left failed: the run pauses, optionally asks a host to
  rotate the proxy IP, recovers the page, and retries that id until it
  succeeds or you interrupt — see [§10](#after-a-full-give-up-pause--rotate--retry).
- **Editing a prompt does not silently regenerate it.** The tool hashes each
  prompt; `status` reports which ones changed since they were generated, and
  `--redo-changed` re-queues exactly those.
- **Deleting a prompt file** leaves its image and its record intact, flagged as
  orphaned, and never queues it again.
- **One run per output folder.** A lock file stops two runs from fighting over
  the same directory; a lock left behind by a dead process is cleared
  automatically.
- **`Ctrl-C` finishes the current image and exits cleanly.** Press it twice to
  stop immediately.

### While it runs

In an interactive terminal the run shows a single live status line that stays
current instead of scrolling:

```
[12/497] 01-012-business-professional-012  2:3 · 2048x2048 · transparent  → 01-business-professional/business-professional-012.png
  ✓  1664x2496  transparent  2.3MB  31s
  · kept native 1664x2496 (requested 2048x2048 would upscale)
 ⣾ · 12/497 · ███░░░░░░░░░░░░░░░ ·  2.4% · ✓11 ✗1 · rendering 45% · 6m12s elapsed · eta 3h58m
```

The percentage during `rendering` is Ideogram's own progress for your image, read
from its API rather than guessed, so a slow generation is visibly moving rather
than apparently hung. The ETA is a rolling average of recent images.

Colour and the live line are used only when stdout is an interactive terminal.
Piped or redirected output is plain text, `NO_COLOR` is honoured, and
`.imagegen/run.log` never contains escape codes — a log you cannot grep is not a
log. Force either way with `--color always|never`.

---

## 10. Command reference

### `run <source>`

`<source>` is a prompt folder or a `.json` manifest, for `run`, `status` and
`validate` alike. Several manifests can be listed at once and run as one batch
(see [§5](#several-manifests-one-batch)):

```bash
./imagegen-cli run ~/batches/from-1-100.json ~/batches/from-101-200.json
```

#### Shared `run` flags

| Flag | Default | Purpose |
|---|---|---|
| `-o, --out DIR` | manifest's `output_dir`, else `<source>/output` | where images are written; with several sources that want different folders, each keeps its own structure as a subfolder of this one |
| `--backend NAME` | `ideogram` | `ideogram`, `recraft` or `mock` |
| `--limit N` | 0 (all) | stop after N successful images |
| `--only ID` | — | generate just this id; repeatable |
| `--match GLOB` | — | only ids/paths matching this glob; repeatable |
| `--retry-failed` | off | re-queue previously failed items |
| `--redo-changed` | off | re-queue done items whose prompt was edited |
| `--no-reconcile` | off | do not adopt images already on disk as done |
| `--flat` | off | write every image directly into the output folder, no category subfolders (§7) |
| `--allow-any-format` | off | honour each item's `output:` extension (`.jpg`, `.webp`, …) instead of requiring `.png` |
| `--force-background-removal` | off | cut out the background when one is really there (§8) |
| `--max-file-size KB` | off | compress images over this size, keeping resolution; bare flag means 1200 KB |
| `--allow-upscale` | off | resize up to `size:` instead of keeping native resolution |
| `--max-attempts N` | 3 | tries per image before a give-up |
| `--retry-backoff S` | 5.0 | seconds × attempt to wait before the next try inside one give-up cycle |
| `--min-gap` / `--max-gap` | 4 / 9 | random pause between *successful* generations, in seconds |
| `--delay COUNT:SECONDS` | off | extra pause of `SECONDS` after every `COUNT` successful generations (on top of min/max gap). Example: `--delay 1:5` waits 5s after every image; `--delay 5:30` waits 30s after every 5th |
| `--after-item-fail-pause SECONDS` | `0` (off) | after a full give-up on one id, wait this many seconds, recover the page, then **retry the same id** until it succeeds (or you interrupt). Hosts like Sarathi pass `30` |
| `--after-item-fail-rotate-url URL` | off | `POST` this URL after a give-up (before the pause) so a host can rotate the browser's proxy exit IP. Implies the same retry-until-pass behaviour as a non-zero pause |
| `--dry-run` | off | print what would be generated and exit, writing nothing |
| `--color` | `auto` | `auto`, `always` or `never` for colour and the live status line |
| `--state PATH` | `.imagegen/progress.json` | override the state file location |

#### After a full give-up: pause / rotate / retry

Without the after-fail flags, exhausting `--max-attempts` marks the item
`failed` and the batch moves on (re-queue later with `--retry-failed`).

With `--after-item-fail-pause` and/or `--after-item-fail-rotate-url`:

1. Log `gave up on <id> — will rotate/pause and retry`
2. If a rotate URL is set → `POST` it (short timeout; a failure is a warning, not a stop)
3. If pause &gt; 0 → wait that many seconds (status line shows `after-fail pause`)
4. Reload/recover the page
5. Start a **new** attempt cycle on the **same** id
6. Repeat until the image succeeds, or `Ctrl-C` / a fatal error stops the run

Bare CLI defaults leave both flags off so behaviour stays unchanged for scripts
that do not opt in.

#### Ideogram backend flags

| Flag | Default | Purpose |
|---|---|---|
| `--cdp-url` | `http://127.0.0.1:9222` | Chrome DevTools endpoint |
| `--page-cookie NAME=VALUE` | — | attach to the page whose profile carries this cookie, instead of the first Ideogram tab (several runs can share one browser) |
| `--ideogram-url` | Ideogram home | page to open/return to between generations |
| `--chrome-binary` | autodetect | Chrome executable |
| `--chrome-profile` | `~/.chrome-imagegen` | dedicated profile directory (must not be the default Chrome profile) |
| `--no-launch-chrome` | off | fail instead of starting Chrome when the CDP port is dead (attach-only hosts) |
| `--gen-timeout` | 420s | seconds to wait for one image |
| `--accept-timeout` | 90s | seconds to wait for Ideogram to register a submit |
| `--poll-interval` | 3s | seconds between finished-image checks |
| `--reload-every` | 25 | reload the tab every N generations (`0` = never) |

#### Recraft backend flags

| Flag | Default | Purpose |
|---|---|---|
| `--recraft-cdp-url` | `http://127.0.0.1:9223` | Chrome DevTools endpoint (different port from Ideogram so both can run at once) |
| `--recraft-page-cookie NAME=VALUE` | — | same idea as `--page-cookie`, for Recraft tabs in a shared browser |
| `--recraft-project-url` | create on first run | reuse a project, e.g. `https://www.recraft.ai/project/<id>`; without it the backend creates one and prints the URL |
| `--recraft-model` | leave as Auto | select a model by visible picker name, e.g. `"Recraft V4.1"` (once at run start, not per image) |
| `--recraft-model-wait` | 30s | if the named model is not in the picker, wait this long for a manual choice (`0` to skip) |
| `--recraft-chrome-binary` | autodetect | Chrome executable |
| `--recraft-chrome-profile` | `~/.chrome-imagegen-recraft` | dedicated profile directory |
| `--recraft-no-launch-chrome` | off | attach-only: do not start Chrome if CDP is down |
| `--recraft-gen-timeout` | 300s | seconds to wait for one image after submit |
| `--recraft-poll-interval` | 3s | seconds between `poll_recraft` retries |
| `--recraft-max-prompt-chars` | off | trim prompts to this many characters at a word boundary before typing (Recraft's UI can silently truncate ~1000 chars once a concrete model is selected) |

#### Mock backend flags

| Flag | Purpose |
|---|---|
| `--mock-fail-rate` | probability (0–1) that a mock generation raises |
| `--mock-delay` | seconds to fake-render (for watching the progress line) |
| `--mock-transparent` | emit an image that already has an alpha cut-out |

### `status <prompt-folder>`

Counts, percentage, the last completed id, every failed item with its error, and
which prompts were edited since they were generated. Read-only.

### `validate <prompt-folder>`

Parses every prompt file, prints each parse error with its filename, and shows
the fully resolved first job so you can confirm the defaults landed where you
expected. Read-only, no browser.

### `convert <manifest.json> <folder>`

Writes one Markdown prompt file per image, mirroring the output layout, plus an
`imagegen.yaml`. `--force` overwrites files that already exist. Only needed when
you want the prompts as editable files — `run` reads a manifest directly.

### `init <folder>`

Scaffolds `imagegen.yaml` and an example prompt. Never overwrites existing files.

### `spec`

Prints the prompt-authoring brief ([`AUTHORING.md`](AUTHORING.md)) for pasting
into an AI along with your idea. `--out FILE` writes it to a file, `--full`
includes the human-facing intro. See §6.

### Examples

```bash
# smoke test: three images, then stop
./imagegen-cli run ~/my-images --limit 3

# just one section, with the browser profile that is already signed in
./imagegen-cli run ~/my-images --match '02-portraits/*' \
    --chrome-profile ~/.chrome-ideogram-automation

# regenerate one asset you were not happy with
rm ~/my-images/output/02-portraits/founder.png
./imagegen-cli run ~/my-images --only portrait-founder

# pick up everything that failed overnight
./imagegen-cli run ~/my-images --retry-failed

# pace a long Recraft batch: extra 30s after every 5 successes
./imagegen-cli run batch.json --backend recraft --flat \
    --recraft-model "Recraft V4.1" \
    --recraft-project-url https://www.recraft.ai/project/<id> \
    --delay 5:30

# attach to a host-owned browser (e.g. Sarathi): do not launch Chrome,
# pin the tab via page cookie, pause+rotate on give-up then retry the same id
./imagegen-cli run batch.json --backend recraft --flat \
    --recraft-no-launch-chrome \
    --recraft-cdp-url http://127.0.0.1:9412 \
    --recraft-page-cookie sarathi_page=<workflow-id> \
    --recraft-model "Recraft V4.1" \
    --after-item-fail-pause 30 \
    --after-item-fail-rotate-url 'http://127.0.0.1:PORT/rotate?token=…'

# exercise the whole pipeline without spending a single generation
./imagegen-cli run ~/my-images --backend mock --mock-fail-rate 0.3
```

### Exit codes

`0` all good · `1` finished with failed items · `2` fatal (not signed in, no
browser, unparseable prompt folder) · `130` interrupted.

---

## 11. Chrome and the web session

Images come from your signed-in web session, not a paid API key. Each backend
launches Chrome itself with `--remote-debugging-port` on a **dedicated profile**
(`~/.chrome-imagegen` for Ideogram, `~/.chrome-imagegen-recraft` for Recraft, by
default) and reuses it if it is already running. Chrome is always started as a
plain subprocess, never through Playwright's own launcher — Playwright's
launcher sets automation fingerprints (`navigator.webdriver`, missing feature
flags) that bot-detection such as Cloudflare Turnstile flags during sign-in; a
normally-launched Chrome that Playwright only *attaches* to is indistinguishable
from one you opened by hand.

That separate profile is mandatory, not a preference: since Chrome 136 the
debugging flag is *silently ignored* when `--user-data-dir` points at the default
profile — Chrome starts, the flag appears in the process list, and the DevTools
server never binds. Your everyday Chrome can stay open; this is a separate
instance.

On first run, sign in inside that window once. The session persists from then
on. To reuse a profile that is already signed in:

```bash
./imagegen-cli run ~/my-images --chrome-profile ~/.chrome-ideogram-automation
./imagegen-cli run ~/my-images --backend recraft --recraft-chrome-profile ~/.chrome-recraft-automation
```

Keep the Chrome window open for the whole batch — closing it ends the run.

**Attach-only hosts** (for example Sarathi) already own the browser. Pass
`--no-launch-chrome` / `--recraft-no-launch-chrome` and point `--cdp-url` /
`--recraft-cdp-url` at that app's DevTools port. When several signed-in profiles
share one CDP endpoint, pin the run to its tab with `--page-cookie` /
`--recraft-page-cookie` (`NAME=VALUE` that the host set on that profile).

Recraft also needs a **project** open (its canvas board), not just a signed-in
session — a fresh account has none. First run creates one and prints its URL;
pass that back as `--recraft-project-url` on later runs to keep reusing the same
project instead of accumulating a new "Untitled" one every time:

```bash
./imagegen-cli run ~/my-images --backend recraft \
  --recraft-project-url https://www.recraft.ai/project/<id>
```

### How a finished image is identified

**Ideogram**: the tool watches Ideogram's own API traffic (`/api/images/sample`
and `/api/gallery/retrieve-requests`) and picks the request whose prompt is ours
and whose creation time is after we pressed generate, then waits for it to reach
100% before downloading.

It deliberately does **not** diff the `<img>` tags on the page. Any page with a
live feed — explore, a shared gallery, lazily loaded history — grows new images
on its own, and a DOM diff will happily hand back a stranger's picture as "the
one we just made". That failure is silent and produces plausible-looking files.

**Recraft**: the editor renders every image onto a single `<canvas>` (a
design-tool board, not a DOM gallery), so there is nothing to diff at all.
Instead the tool watches the network response to *our own* submit request
(`queue_recraft/prompt_to_image`), which hands back an `operationId` paired 1:1
with that request, then waits for Recraft's own single follow-up call
(`poll_recraft`) carrying that same id. That reply names the job's image ids —
either as a multipart body with the image bytes inline, or as a plain JSON
manifest; when it is JSON the browser fetches the pixels next, from a signed
`img.recraft.ai` URL, and the tool reads the bytes off that response. None of
these are replayed by the tool itself (Recraft's client attaches an auth token
said requests need, that a bare HTTP client doesn't have) — they are always the
page's own already-authenticated calls, just read passively.

---

## 12. Adding another generator

`imagegen/backends/base.py` is the entire contract:

```python
class Backend:
    name = "my-backend"

    @staticmethod
    def add_arguments(parser): ...      # optional CLI flags
    def open(self): ...                 # get ready, or raise FatalBackendError
    def generate(self, job) -> GenerationResult: ...   # raise BackendError to retry
    def recover(self): ...              # optional: reset between failed attempts
    def snapshot(self, path) -> bool: ...  # optional: debug capture
    def close(self): ...
```

Implement it, register it in `imagegen/backends/__init__.py`, and the prompt
loading, queue, resume, retry, pacing, background handling and PNG writing all
apply unchanged.

`--backend mock` is a built-in offline backend that synthesises images locally —
use it to test the pipeline without spending real generations.

---

## 13. Troubleshooting

**"this Chrome profile is not signed in to Ideogram"** — sign in inside the
automation window, confirm the generator page loads, then rerun. Or point
`--chrome-profile` at a profile that is already signed in.

**"cannot attach to Chrome" / "Chrome did not expose … within 40s"** — a stale
instance is probably holding the profile directory. Close that Chrome window, or
use a different `--chrome-profile`.

**"Ideogram never registered the request"** / **"Recraft never registered the
request within 30s of pressing generate"** — the generate click did not produce
a submission. Usually credits, a rate limit ("too many requests"), or a UI
change. Check `.imagegen/debug/<id>_a1.png`. With `--after-item-fail-pause` the
run will wait and retry the same id; add `--after-item-fail-rotate-url` (or a
system VPN) if the limit is IP-based.

**"Ideogram rejected the generation (HTTP …)"** — the account hit a quota or rate
limit. Wait, then `--retry-failed`.

**"aspect option … is in the DOM but not clickable"** — Ideogram or Recraft
changed its composer layout. The selectors live at the top of
`imagegen/backends/ideogram.py` / `imagegen/backends/recraft.py`.

**"this Chrome profile is not signed in to Recraft"** — sign in inside the
automation window, confirm a project opens, then rerun.

**"rotate hook failed"** — the `--after-item-fail-rotate-url` POST did not
succeed (host down, bad token, or no proxies configured there). The pause and
page recover still run; only the IP change was skipped.

**"could not set batch size to x1" (warning, not fatal)** — a freshly created
Recraft project's settings controls can take a few seconds to finish hydrating
after the quick-start screen; harmless once it happens, but generations in that
run may cost extra credits per image (Recraft still generates the batch, this
backend just only keeps the first result). Rerun with `--recraft-project-url`
pointing at that same project and it won't happen again.

**"image not finished after …s" (Recraft)** — the account hit a quota or rate
limit, or the generation is unusually slow (a high-res or premium model). The
message also says where the wait got to: a poll reply that never named an image
means it never finished rendering, while "the manifest named … but its image
bytes never arrived" means Recraft finished but the browser never fetched the
picture. Raise `--recraft-gen-timeout`, or wait and `--retry-failed`.

**Images come back opaque when you asked for transparency** — strengthen the
prompt wording first (§8), then add `--force-background-removal`.

**"another run holds …/run.lock"** — a run is already going against that output
folder. If you are certain nothing is running, delete the lock file.

---

## License

MIT — see [LICENSE](LICENSE). Contributions welcome; the test suite runs on
Linux, macOS and Windows, so a pull request that touches paths, encoding or
process handling should keep all three green.
