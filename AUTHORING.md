# Prompt-authoring brief

Copy everything below the line and paste it into any AI — a chat session where you
have been working out an idea, or a coding assistant pointed at a folder. It turns
that idea into a batch this generator can run.

It asks for **one JSON file** by default, because that is what a chat can actually
hand you: a single document with hundreds of entries, rather than hundreds of
files in a directory tree. Save what it gives you and run it directly:

```bash
./imagegen-cli validate ~/batch.json      # confirm every entry parses
./imagegen-cli run      ~/batch.json --limit 3   # smoke test before the full batch
./imagegen-cli run      ~/batch.json      # the rest
```

Get the brief without leaving the terminal:

```bash
./imagegen-cli spec | xclip -sel c    # Linux
./imagegen-cli spec | pbcopy          # macOS
./imagegen-cli spec > brief.md
```

---

You are preparing input for `imagegen`, a batch image generator. Convert the idea,
discussion or brief I give you into a batch it can run.

**Produce one JSON file** unless I ask otherwise. If you can write files, write it.
If you cannot, output it as a single fenced ```json block I can save.

## The JSON format

```json
{
  "project": "Premium Humans",
  "output_dir": "premium-humans",
  "defaults": {
    "size": "2048x2048",
    "background": "transparent",
    "negative": "watermark, text, extra fingers, distorted anatomy",
    "prompt_suffix": "crisp clean edges, photorealistic, high detail."
  },
  "options": { "max_file_size": 1200 },
  "images": [
    {
      "id": "01-001-founder-portrait",
      "output": "01-portraits/founder-portrait.png",
      "aspect": "3:4",
      "prompt": "Studio portrait of a smiling woman in her thirties wearing a navy blazer, three-quarter view, soft key light from the left, gentle rim light, subject fully isolated on a completely transparent background, no backdrop, no ground shadow, no scenery."
    },
    {
      "id": "02-001-team-wide",
      "output": "02-groups/team-wide.png",
      "size": "1920x1080",
      "background": "opaque",
      "prompt": "Five colleagues standing side by side in business casual clothing, warm office background, soft daylight, photorealistic."
    }
  ]
}
```

### Top-level keys

| Key | Rule |
|---|---|
| `images` | **Required.** The array of image entries. |
| `output_dir` | **Include it.** Where the images are written, relative to the JSON file itself. Use a short slug naming the batch, e.g. `"premium-humans"`. |
| `defaults` | Anything shared by every image: `size`, `aspect`, `background`, `negative`, `prompt_prefix`, `prompt_suffix`. Put shared style wording in `prompt_prefix` rather than repeating it in every entry. |
| `options` | Optional default flags, e.g. `{"max_file_size": 1200}` to keep files under 1200 KB. |
| `project` | Optional label. Anything else you add is ignored, not an error. |

### Per-image keys

| Key | Rule |
|---|---|
| `prompt` | **Required.** The full text sent to the generator. See the prompt-writing rules below. |
| `id` | Unique across the batch. Use `<section>-<number>-<slug>`, all lowercase, e.g. `01-001-founder-portrait`. |
| `output` | Path relative to `output_dir`, unique across the batch. **Every segment must be a slug** — lowercase letters, digits and dashes only, no spaces, no capitals — and it must end in `.png`. Never absolute, never containing `..`. Group images into numbered subfolders: `01-portraits/`, `02-groups/`. |
| `aspect` | One of `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `16:10`, `10:16`, `1:3`, `3:1`. Omit it when `size` is given — it is derived. |
| `size` | `"WIDTHxHEIGHT"`. Omit entirely if you have no specific requirement; the generator's native resolution is usually best. It only ever downscales. |
| `background` | `"transparent"` or `"opaque"`. Omit when it does not matter. This is metadata, **not** an instruction to the model — you must also say it in the prompt text. |
| `negative` | Things to avoid, comma separated. Optional; inherits from `defaults`. |

Order the `images` array in the order they should be generated.

## Writing the prompt text

- **Self-contained.** Each prompt must stand alone. The generator sees only that
  one block of text — no neighbouring entries, no chat history, no `description`
  field. Everything needed must be inside `prompt`.
- **Concrete and visual.** Subject, pose or arrangement, materials, colour
  direction, lighting, camera angle, composition. Not intent ("something that
  feels trustworthy") but appearance.
- **Consistent across the set.** If the images belong to one product or brand,
  put the shared style wording in `defaults.prompt_prefix` once rather than
  paraphrasing it differently in each entry.
- **Transparency must be spelled out in the prompt**, not just in `background`.
  This phrasing works reliably:

  > …crisp clean edges, subject fully isolated on a completely transparent
  > background, no backdrop, no ground shadow, no scenery.

- **No text in images** unless the image is specifically about lettering —
  generators mangle it. Say `no text, no letters, no watermark`.

## If I ask for a prompt folder instead

Same information, one Markdown file per image, at `<folder>/<NNN>-<slug>.md`:

```markdown
---
id: 01-001-founder-portrait
output: 01-portraits/founder-portrait.png
size: 2048x2048
aspect: "1:1"
background: transparent
negative: "watermark, text, distorted anatomy"
---
Studio portrait of a smiling woman in her thirties wearing a navy blazer…
```

The same field rules apply, plus:

- `aspect` **must be quoted** in YAML: `aspect: "16:9"`. Unquoted `16:9` is not
  a string.
- Shared settings go in an `imagegen.yaml` at the folder root under `defaults:`.
- Name the files as slugs too — `001-founder-portrait.md`, never
  `001 Founder Portrait.md`.
- `README.md`, `INDEX.md` and files starting with `.` or `_` are ignored, so
  notes can live alongside prompts safely.

## Before you finish

- Every `id` unique, every `output` unique.
- Every `output` is a lowercase-dash slug ending in `.png`, with no `..` and no
  leading `/`.
- `output_dir` is set.
- Every prompt reads as a complete standalone description.
- Valid JSON — no trailing commas, no comments, all strings double-quoted.
- Tell me the total number of images, so I know what the batch will cost.

Ask me for anything you genuinely need — how many images, what they are for, what
style ties them together — but do not stall on details you can reasonably choose
yourself. State the assumptions you made.
