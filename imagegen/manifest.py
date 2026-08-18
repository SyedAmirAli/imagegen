"""Load a JSON manifest into the same Job objects a prompt folder produces.

A manifest is one file describing a whole batch, which is what an AI chat can
realistically hand you — asking it for four hundred separate Markdown files with
a folder structure usually is not.

The canonical shape is:

    {
      "project": "Premium Humans",
      "output_dir": "images",
      "defaults": { "size": "2048x2048", "background": "transparent" },
      "images": [
        { "id": "01-001-founder", "output": "01-portraits/founder.png",
          "prompt": "...", "negative": "...", "aspect": "3:4" }
      ]
    }

Field aliases are accepted throughout, so manifests written for other pipelines
(`assets` / `relative_path` / `aspect_ratio` / `transparent_background` / a bare
`width`+`height` pair) load without being rewritten first.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from .prompts import (
    Job,
    PromptError,
    check_output_path,
    derive_aspect,
    normalise_background,
    parse_size,
    slugify,
)

# Where the list of images lives, in order of preference.
LIST_KEYS = ("images", "assets", "items", "prompts", "entries")
# Where the output directory lives.
OUTPUT_DIR_KEYS = ("output_dir", "output_directory", "output_folder", "outputDir", "output")

FIELD_ALIASES = {
    "prompt": ("prompt", "text", "description_prompt"),
    "negative": ("negative", "negative_prompt", "negativePrompt"),
    "aspect": ("aspect", "aspect_ratio", "aspectRatio", "ratio"),
    "size": ("size", "dimensions"),
    "background": ("background",),
    "id": ("id", "asset_id", "key", "slug"),
}
# Default keys we understand; anything else in `defaults` is metadata for other
# tools (colour profile, bit depth, …) and is ignored rather than fought with.
DEFAULT_KEYS = ("size", "aspect", "background", "negative",
                "prompt_prefix", "prompt_suffix")


def _first(entry: dict, names: tuple[str, ...]):
    for name in names:
        value = entry.get(name)
        if value not in (None, ""):
            return value
    return None


def output_dir_of(data: dict) -> str | None:
    """The output directory a manifest declares, if any."""
    if not isinstance(data, dict):
        return None
    for key in OUTPUT_DIR_KEYS:
        value = data.get(key)
        # `output` at top level is only a directory when it is a bare string;
        # a list there is the image list, not a path.
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_CACHE: dict[Path, object] = {}


def read(path: Path) -> dict | list:
    """Parse a manifest, once per path — these files run to megabytes."""
    key = path.resolve()
    if key in _CACHE:
        return _CACHE[key]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _CACHE[key] = data
        return data
    except json.JSONDecodeError as exc:
        raise PromptError(f"{path.name} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PromptError(f"cannot read {path}: {exc}") from exc


def image_list(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise PromptError("a manifest must be a JSON object or an array of images")
    for key in LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return value
    raise PromptError(
        f"no image list found — expected one of {', '.join(LIST_KEYS)}, "
        f"got keys: {', '.join(sorted(data)[:8])}"
    )


def _entry_size(entry: dict) -> tuple[int, int] | None:
    size = parse_size(_first(entry, FIELD_ALIASES["size"]))
    if size:
        return size
    width, height = entry.get("width"), entry.get("height")
    if width and height:
        return int(width), int(height)
    return None


def _entry_background(entry: dict, default) -> str:
    explicit = _first(entry, FIELD_ALIASES["background"])
    if explicit is not None:
        return normalise_background(explicit)
    flag = entry.get("transparent_background", entry.get("transparent"))
    if isinstance(flag, bool):
        return "transparent" if flag else "opaque"
    return normalise_background(default)


def _entry_output(entry: dict, fallback_id: str) -> str:
    """Work out where this image goes, from whichever keys the manifest uses."""
    direct = _first(entry, ("output", "output_file", "relative_path", "path", "file"))
    if direct:
        return str(direct).replace("\\", "/")

    folder = str(entry.get("folder") or "").strip("/")
    filename = str(entry.get("filename") or "").strip()
    if not filename:
        filename = f"{slugify(str(entry.get('name') or fallback_id))}.png"
    return f"{folder}/{filename}" if folder else filename


def parse(path: Path, out_root: Path, *, defaults: dict | None = None):
    """Return (jobs, errors) for a manifest file."""
    data = read(path)
    entries = image_list(data)
    top = data if isinstance(data, dict) else {}

    merged_defaults = {k: v for k, v in (top.get("defaults") or {}).items()
                       if k in DEFAULT_KEYS}
    merged_defaults.update(defaults or {})

    out_root = out_root.resolve()
    jobs: list[Job] = []
    errors: list[tuple[Path, str]] = []
    seen_ids: dict[str, int] = {}
    seen_out: dict[str, int] = {}

    for position, entry in enumerate(entries, 1):
        label = f"{path.name}[{position}]"
        try:
            if not isinstance(entry, dict):
                raise PromptError("each image must be a JSON object")

            prompt = str(_first(entry, FIELD_ALIASES["prompt"]) or "").strip()
            if not prompt:
                raise PromptError("no prompt text")

            job_id = str(_first(entry, FIELD_ALIASES["id"]) or f"{path.stem}-{position:04d}")
            rel_output = _entry_output(entry, job_id)
            if not PurePosixPath(rel_output).suffix:
                rel_output += ".png"
            check_output_path(rel_output)

            size = _entry_size(entry) or parse_size(merged_defaults.get("size"))
            aspect = str(_first(entry, FIELD_ALIASES["aspect"]) or "").strip()
            if not aspect:
                aspect = (derive_aspect(size) if size
                          else str(merged_defaults.get("aspect") or "").strip())

            prefix = str(merged_defaults.get("prompt_prefix") or "")
            suffix = str(merged_defaults.get("prompt_suffix") or "")
            if prefix:
                prompt = f"{prefix.rstrip()}\n\n{prompt}"
            if suffix:
                prompt = f"{prompt}\n\n{suffix.lstrip()}"

            negative = str(_first(entry, FIELD_ALIASES["negative"])
                           or merged_defaults.get("negative") or "").strip()

            if job_id in seen_ids:
                raise PromptError(f"duplicate id {job_id!r} (also at entry {seen_ids[job_id]})")
            if rel_output in seen_out:
                raise PromptError(
                    f"duplicate output {rel_output!r} (also at entry {seen_out[rel_output]})")
            seen_ids[job_id] = position
            seen_out[rel_output] = position

            known = {"prompt", "negative", "aspect", "size", "background", "id", "output"}
            jobs.append(Job(
                id=job_id,
                prompt=prompt,
                output=(out_root / rel_output).resolve(),
                source=path.resolve(),
                rel_source=f"{path.name}[{position}]",
                rel_output=rel_output,
                negative=negative,
                size=size,
                aspect=aspect or None,
                background=_entry_background(entry, merged_defaults.get("background")),
                extra={k: v for k, v in entry.items() if k not in known},
            ))
        except (PromptError, ValueError, TypeError) as exc:
            errors.append((Path(label), str(exc)))

    return jobs, errors
