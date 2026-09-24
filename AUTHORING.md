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
      "prompt": "Studio portrait of a smiling woman in her thirties wearing a navy blazer, three-quarter view, soft key light from the left, gentle rim light, subject fully isolated on a completely transparent background, no backdrop, no ground shadow, no scenery.",
      "meta": {
        "author": "Jane Doe",
        "copyright": "© 2026 Jane Doe. All rights reserved.",
        "title": "Smiling businesswoman in a navy blazer isolated on a transparent background",
        "description": "Studio portrait of a smiling woman in her thirties wearing a navy blazer, lit with soft key light and a gentle rim light, fully cut out on a transparent background for websites, presentations and ads.",
        "tags": ["businesswoman", "woman", "portrait", "smiling", "navy blazer", "business attire", "professional", "corporate", "business", "studio portrait", "three quarter view", "isolated", "transparent background", "cut out", "people"],
        "category": "People",
        "adobe_category_id": 13,
        "ai_generated": true,
        "fictional_people_property": true,
        "model": "Ideogram",
        "prompt": "Studio portrait of a smiling woman in her thirties wearing a navy blazer, three-quarter view, soft key light from the left, gentle rim light, subject fully isolated on a completely transparent background, no backdrop, no ground shadow, no scenery. crisp clean edges, photorealistic, high detail.",
        "file_type": "png"
      }
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
| `options` | Optional default flags, e.g. `{"max_file_size": 1200}` to keep files under 1200 KB, or `{"flat": true}` to write every image directly into `output_dir` with no subfolders. |
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
| `meta` | Stock metadata written into the saved file (see "Stock metadata" below). Never sent to the generator. Include it whenever the images are meant for stock upload. |

Order the `images` array in the order they should be generated.

### Stock metadata (`meta`)

Each entry may carry a `meta` object. `imagegen` writes it into the image itself
as XMP (plus PNG text keywords), the form Adobe Stock, Lightroom, Bridge and
exiftool read, so the file keeps its title and keywords wherever it goes:

```bash
./imagegen-cli run ~/batch.json --embed-metadata       # embed while generating
./imagegen-cli embed-metadata ~/batch.json             # embed into images already made
```

| Field | Rule |
|---|---|
| `author` | The creator's name exactly as I give it. Ask me if I did not give one; never guess. Written as `dc:creator`. |
| `copyright` | Copyright notice, e.g. `"© 2026 Jane Doe. All rights reserved."`. Written as `dc:rights`. |
| `title` | **At most 100 characters.** One line, sentence case, no trailing period: main subject plus what sets this image apart. Unique across the batch. |
| `description` | **At most 600 characters.** One to three plain sentences: what is shown, notable details, what it suits. |
| `tags` | **At least 15** unique lowercase keywords, one to three words each, most important first (Adobe weighs the first 10 most). |
| `category` | Adobe Stock category name: Animals, Buildings and Architecture, Business, Drinks, The Environment, States of Mind, Food, Graphic Resources, Hobbies and Leisure, Industry, Landscapes, Lifestyle, People, Plants and Flowers, Culture and Religion, Science, Social Issues, Sports, Technology, Transport, Travel. |
| `adobe_category_id` | That category's number, 1–21 in the order listed above. |
| `ai_generated` | `true` for generated images. Stock sites require AI content to be marked. |
| `fictional_people_property` | `true` when the image shows people or recognisable property (buildings, vehicles, products) that are generated; otherwise `false`. |
| `model` | The generator used, e.g. `"Ideogram"`. |
| `prompt` | The full prompt as sent (entry prompt plus prefix/suffix). Freepik's upload CSV asks for it. |
| `file_type` | Format for upload: `"png"` for transparent images, `"jpg"` for opaque ones. |

Rules for writing it:

- Describe the image, not the prompt: state only what the image will show; never
  invent age, ethnicity, emotion, location or brand the prompt does not fix.
- No prompt jargon (`photorealistic`, `8k`, `render`), no brand names,
  trademarks, real people's names or copyrighted characters.
- Plain English text: no emojis, hashtags, HTML or line breaks.
- Build each entry's `meta` from the same parts as its prompt, so titles and tags
  always match that image. Never reuse one generic title or tag list.
- Fields shared by every image (`author`, `copyright`, `model`, `ai_generated`)
  may go once in `defaults.meta`; each entry's own `meta` wins field by field.
  Repeating them per entry is also fine.

### One file for the whole batch

Keep the entire batch in **one JSON file**, even at 1,000+ images: write it
with a script if a reply cannot hold it. Split only if you truly cannot produce
one file, into numbered files — `from-1-100.json`, `from-101-200.json` and so on
— each a complete, valid manifest with the **same `output_dir`**. They are run
together as one batch:

```bash
imagegen-cli run ./from-*.json
```

Ids, `output` paths and `meta.title` must be unique across *all* the files,
not just within one. `defaults` are per-file, so each chunk carries its own shared wording.

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
- Every prompt is unique — no two identical or near-identical prompts.
- If the batch is for stock: every entry has `meta` with the author I named, a
  title of at most 100 characters, a description of at most 600, at least 15
  unique tags, and the category, AI, model, prompt and file-type fields.
- Valid JSON — no trailing commas, no comments, all strings double-quoted.
- Tell me the total number of images, so I know what the batch will cost.

Ask me for anything you genuinely need — how many images, what they are for, what
style ties them together — but do not stall on details you can reasonably choose
yourself. State the assumptions you made.
