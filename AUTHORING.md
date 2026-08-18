# Prompt-authoring brief

Copy everything below the line and paste it into any AI — a chat session where you
have been working out an idea, or a coding assistant pointed at a folder. It turns
that idea into prompt files this generator can run.

Get it without leaving the terminal:

```bash
./imagegen-cli spec | pbcopy        # macOS
./imagegen-cli spec | xclip -sel c  # Linux
./imagegen-cli spec > brief.md
```

Then run what it produced:

```bash
./imagegen-cli validate ~/my-images    # confirm every file parses
./imagegen-cli run      ~/my-images --limit 3   # smoke test before the full batch
```

---

You are preparing input for `imagegen`, a batch image generator. Convert the idea,
discussion or brief I give you into a **prompt folder**: one Markdown file per
image, in the exact format below.

If you can write files, create the folder and the files. If you cannot, output each
file as a separate fenced code block with its full relative path on the line above
it, so I can save them by hand.

## What one image looks like

A file named `<folder>/<NNN>-<slug>.md`:

```markdown
---
id: 02-001-founder-portrait
output: 02-portraits/founder.png
size: 2048x2048
aspect: "1:1"
background: transparent
negative: "watermark, text, distorted anatomy, extra fingers"
---
A polished studio portrait of a smiling woman in her thirties wearing a navy
blazer, three-quarter view, soft key light from the left, gentle rim light,
crisp clean edges, photorealistic, high detail, subject fully isolated on a
completely transparent background, no backdrop, no ground shadow, no scenery.
```

Front-matter is the settings, everything after it is the prompt sent to the
generator.

## Field rules

| Field | Rule |
|---|---|
| `id` | Unique across the whole folder. Use `<section>-<number>-<slug>`, all lowercase, e.g. `02-001-founder-portrait`. |
| `output` | Path **relative to the output folder**, unique across the folder, mirroring the prompt folder structure. **Every segment must be a slug** — lowercase letters, digits and dashes only, no spaces, no capitals, no punctuation — and it must end in `.png`. Never absolute, and never containing `..`. Anything else is rejected or warned about. |
| `size` | `WIDTHxHEIGHT`, no spaces. Omit entirely if you have no specific requirement — the generator's native resolution is usually the best one. Only ever downscales. |
| `aspect` | **Must be quoted**: `aspect: "16:9"`. Unquoted `16:9` is not valid YAML. Use one of `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `16:10`, `10:16`, `1:3`, `3:1`. Omit it when `size` is given — it is derived. |
| `background` | `transparent` or `opaque`. Omit when it does not matter. This is metadata, **not** an instruction to the model — you must also say it in the prompt text. |
| `negative` | Comma-separated things to avoid. Optional. |

Every field is optional. `id` defaults to the file path without its extension and
`output` defaults to that path with `.png`, so a well-named file needs almost no
front-matter.

## Folder rules

- One folder, one batch. Group images into numbered subfolders: `01-logos/`,
  `02-portraits/`, `03-icons/`.
- Number files so they sort in the order they should be generated:
  `001-symbol.md`, `002-wordmark.md`. Path order is generation order.
- **Name the prompt files as slugs too** — lowercase, dashes, no spaces: use
  `001-founder-portrait.md`, never `001 Founder Portrait.md`. Filenames become
  ids and output paths, and both get typed into shell commands.
- `README.md`, `INDEX.md`, `AGENTS.md`, `CLAUDE.md` and any file starting with `.`
  or `_` are ignored, so notes can live alongside prompts safely.
- Put anything shared by every image in `imagegen.yaml` at the folder root instead
  of repeating it in every file:

````yaml
defaults:
  size: 2048x2048
  aspect: "1:1"
  background: transparent
  negative: "watermark, text artifacts, low resolution"
  prompt_prefix: |
    Consistent premium illustration style across the whole set: soft 3D forms,
    rounded geometry, soft studio lighting, clean silhouettes.
````

  A value in a file's front-matter always beats the folder default. One catch: if
  a file sets its own `size` but no `aspect`, the aspect comes from that size, not
  from the folder default — so do not mix a folder-wide `aspect` with per-file
  sizes of a different shape.

## Writing the prompt text

- **Self-contained.** Each prompt must stand alone. The generator sees only that
  one block of text — no folder context, no neighbouring files, no chat history.
- **Concrete and visual.** Subject, pose or arrangement, materials, colour
  direction, lighting, camera angle, composition. Not intent ("something that
  feels trustworthy") but appearance.
- **Consistent across the set.** If the images belong to one product or brand,
  repeat the same style, lighting and palette wording in every prompt, or put it
  once in `prompt_prefix`.
- **Transparency must be spelled out in the prompt**, not just in `background:`.
  This phrasing works reliably:

  > …crisp clean edges, subject fully isolated on a completely transparent
  > background, no backdrop, no ground shadow, no scenery.

- **No text in images** unless the image is specifically about lettering —
  generators mangle it. Say `no text, no letters, no watermark`.
- If a file needs notes for humans, wrap the real prompt in a fenced ```text block
  under a `## PROMPT` heading; only that first fenced block is sent to the
  generator and the surrounding prose is dropped.

## Before you finish

- Every `id` unique, every `output` unique.
- Every filename, `id` and `output` path is lowercase-dash-slug, and every
  `output` ends in `.png`.
- Every `aspect` quoted.
- Front-matter opens and closes with `---` on their own lines.
- Every prompt reads as a complete standalone description.
- Count the files and tell me the total, so I know what the batch will cost.

Ask me for anything you genuinely need — how many images, what they are for, what
style ties them together — but do not stall on details you can reasonably choose
yourself. State the assumptions you made.
