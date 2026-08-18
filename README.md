# imagegen

One reusable CLI for batch image generation. Point it at a folder of prompts and
it drives a real, signed-in Ideogram session in Chrome — one image at a time, one
tab — saving every result as a PNG at the path its prompt asks for.

It is built to be interrupted. Progress is written after every single image, so a
crash, a `Ctrl-C` or a closed browser costs at most the image in flight. Rerun the
identical command and it continues from exactly where it stopped.

```bash
./imagegen-cli init     ~/my-images        # scaffold a prompt folder
./imagegen-cli validate ~/my-images        # parse every prompt, report problems
./imagegen-cli run      ~/my-images        # generate everything still pending
./imagegen-cli status   ~/my-images        # how far along am I
./imagegen-cli spec                        # brief that turns an idea into a prompt folder
```

Have an idea or a chat discussion rather than a folder of prompts? Hand
[`AUTHORING.md`](AUTHORING.md) to any AI and it writes the folder for you — see
[§5](#5-from-an-idea-to-a-prompt-folder).

---

## Contents

1. [Install](#1-install)
2. [The prompt folder](#2-the-prompt-folder)
3. [Prompt file structure](#3-prompt-file-structure)
4. [Folder-level settings: `imagegen.yaml`](#4-folder-level-settings-imagegenyaml)
5. [From an idea to a prompt folder](#5-from-an-idea-to-a-prompt-folder)
6. [Where output goes](#6-where-output-goes)
7. [Backgrounds and transparency](#7-backgrounds-and-transparency)
8. [Resuming, retrying, skipping](#8-resuming-retrying-skipping)
9. [Command reference](#9-command-reference)
10. [Chrome and the Ideogram session](#10-chrome-and-the-ideogram-session)
11. [Adding another generator](#11-adding-another-generator)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Install

```bash
git clone git@github.com:SyedAmirAli/imagegen.git
cd imagegen
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium      # only if Playwright is not set up yet
```

If your Python is externally managed (Debian/Ubuntu, PEP 668), use a virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python imagegen-cli run ~/my-images
```

Nothing else is needed. The tool launches its own Chrome when the debugging port
is not already live.

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
| `id` | no | Stable identifier used for progress tracking and `--only`. **Defaults to the file's path without its extension** (`02-portraits/001-founder`). Must be unique in the folder. |
| `output` | no | Where the PNG is written, **relative to the output folder**. Defaults to the prompt's own path with a `.png` extension, which mirrors your prompt tree into the output tree. Absolute paths are rejected. |
| `size` | no | Final pixel size, `WIDTHxHEIGHT`. Omit to keep whatever the generator produces natively. The image is only ever downscaled to this; see `--allow-upscale`. |
| `aspect` | no | Ratio requested from the generator, e.g. `"1:1"`, `"3:4"`, `"16:9"`. Quote it — bare `16:9` is not valid YAML. Derived from `size` when omitted. A ratio the generator does not offer is snapped to the nearest one it does, and the substitution is logged. |
| `background` | no | `transparent`, `opaque`, or omitted. This is an instruction to *you and the tool*, not to the model — put the actual wording in the prompt too. See §7. |
| `negative` | no | Things to avoid. Ideogram's current composer has no separate negative field, so this is appended to the prompt as `NEGATIVE PROMPT (avoid entirely): …` unless that text already appears in the prompt. |

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

## 5. From an idea to a prompt folder

You do not have to write the format by hand. If you have an idea, a design brief,
or a chat session where you worked out what the images should be, hand that plus
[`AUTHORING.md`](AUTHORING.md) to any AI and let it produce the folder for you.

```bash
./imagegen-cli spec | xclip -selection clipboard   # Linux
./imagegen-cli spec | pbcopy                       # macOS
./imagegen-cli spec > brief.md
```

Paste it into a chat alongside your idea and it writes each file out as a code
block for you to save. Give it to a coding assistant with access to a directory
and it creates the folder and the files directly. The brief covers the format,
the field rules, folder and naming conventions, how to keep a set visually
consistent, and the wording that actually produces transparent cut-outs.

Then check its work before spending generations:

```bash
./imagegen-cli validate ~/my-images            # every file parses?
./imagegen-cli run ~/my-images --dry-run       # right count, right paths?
./imagegen-cli run ~/my-images --limit 3       # smoke test three images
```

`validate` and `--dry-run` never open a browser and never write anything, so
they are free to run as often as you like.

---

## 6. Where output goes

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

Images are written to a `.part` file and moved into place only once complete, so
an interrupted download can never leave a truncated PNG that a later run would
mistake for a finished one.

`progress.json` is plain, readable JSON — one entry per id with its status,
attempt count, timestamps, the last error, the provider's image id, and notes
such as `background removed (rembg)` or `kept native 1024x1024`.

---

## 7. Backgrounds and transparency

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

## 8. Resuming, retrying, skipping

- **Already-generated items are skipped.** Rerunning the same command is always
  safe and always cheap.
- **Deleting `progress.json` is safe.** The next run adopts every image already
  on disk as done and queues only the rest. `--no-reconcile` opts out.
- **Failures are kept, not lost.** An item that fails all its attempts is marked
  `failed` with its error and a screenshot in `.imagegen/debug/`. Re-queue them
  with `--retry-failed`.
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

---

## 9. Command reference

### `run <prompt-folder>`

| Flag | Default | Purpose |
|---|---|---|
| `-o, --out DIR` | `<prompt-folder>/output` | where images are written |
| `--backend NAME` | `ideogram` | `ideogram` or `mock` |
| `--limit N` | 0 (all) | stop after N successful images |
| `--only ID` | — | generate just this id; repeatable |
| `--match GLOB` | — | only ids/paths matching this glob; repeatable |
| `--retry-failed` | off | re-queue previously failed items |
| `--redo-changed` | off | re-queue done items whose prompt was edited |
| `--no-reconcile` | off | do not adopt images already on disk as done |
| `--force-background-removal` | off | cut out the background when one is really there (§7) |
| `--allow-upscale` | off | resize up to `size:` instead of keeping native resolution |
| `--max-attempts N` | 3 | tries per image |
| `--retry-backoff S` | 5.0 | seconds × attempt to wait before retrying |
| `--min-gap` / `--max-gap` | 4 / 9 | random pause between generations, in seconds |
| `--dry-run` | off | print what would be generated and exit, writing nothing |
| `--state PATH` | `.imagegen/progress.json` | override the state file location |

Ideogram backend flags: `--cdp-url` (default `http://127.0.0.1:9222`),
`--ideogram-url`, `--chrome-binary`, `--chrome-profile` (default
`~/.chrome-imagegen`), `--no-launch-chrome`, `--gen-timeout` (420s),
`--accept-timeout` (90s), `--poll-interval` (3s), `--reload-every` (25).

Mock backend flags: `--mock-fail-rate`, `--mock-transparent`.

### `status <prompt-folder>`

Counts, percentage, the last completed id, every failed item with its error, and
which prompts were edited since they were generated. Read-only.

### `validate <prompt-folder>`

Parses every prompt file, prints each parse error with its filename, and shows
the fully resolved first job so you can confirm the defaults landed where you
expected. Read-only, no browser.

### `init <folder>`

Scaffolds `imagegen.yaml` and an example prompt. Never overwrites existing files.

### `spec`

Prints the prompt-authoring brief ([`AUTHORING.md`](AUTHORING.md)) for pasting
into an AI along with your idea. `--out FILE` writes it to a file, `--full`
includes the human-facing intro. See §5.

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

# exercise the whole pipeline without spending a single generation
./imagegen-cli run ~/my-images --backend mock --mock-fail-rate 0.3
```

### Exit codes

`0` all good · `1` finished with failed items · `2` fatal (not signed in, no
browser, unparseable prompt folder) · `130` interrupted.

---

## 10. Chrome and the Ideogram session

Images come from your signed-in web session, not a paid API key. The backend
launches Chrome itself with `--remote-debugging-port` on a **dedicated profile**
(`~/.chrome-imagegen` by default) and reuses it if it is already running.

That separate profile is mandatory, not a preference: since Chrome 136 the
debugging flag is *silently ignored* when `--user-data-dir` points at the default
profile — Chrome starts, the flag appears in the process list, and the DevTools
server never binds. Your everyday Chrome can stay open; this is a separate
instance.

On first run, sign in to Ideogram inside that window once. The session persists
from then on. To reuse a profile that is already signed in:

```bash
./imagegen-cli run ~/my-images --chrome-profile ~/.chrome-ideogram-automation
```

Keep the Chrome window open for the whole batch — closing it ends the run.

### How a finished image is identified

The tool watches Ideogram's own API traffic (`/api/images/sample` and
`/api/gallery/retrieve-requests`) and picks the request whose prompt is ours and
whose creation time is after we pressed generate, then waits for it to reach
100% before downloading.

It deliberately does **not** diff the `<img>` tags on the page. Any page with a
live feed — explore, a shared gallery, lazily loaded history — grows new images
on its own, and a DOM diff will happily hand back a stranger's picture as "the
one we just made". That failure is silent and produces plausible-looking files.

---

## 11. Adding another generator

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

## 12. Troubleshooting

**"this Chrome profile is not signed in to Ideogram"** — sign in inside the
automation window, confirm the generator page loads, then rerun. Or point
`--chrome-profile` at a profile that is already signed in.

**"cannot attach to Chrome" / "Chrome did not expose … within 40s"** — a stale
instance is probably holding the profile directory. Close that Chrome window, or
use a different `--chrome-profile`.

**"Ideogram never registered the request"** — the generate click did not produce
a submission. Usually credits, a rate limit, or a UI change. Check
`.imagegen/debug/<id>_a1.png`.

**"Ideogram rejected the generation (HTTP …)"** — the account hit a quota or rate
limit. Wait, then `--retry-failed`.

**"aspect option … is in the DOM but not clickable"** — Ideogram changed its
composer layout. The selectors live at the top of
`imagegen/backends/ideogram.py`.

**Images come back opaque when you asked for transparency** — strengthen the
prompt wording first (§7), then add `--force-background-removal`.

**"another run holds …/run.lock"** — a run is already going against that output
folder. If you are certain nothing is running, delete the lock file.
