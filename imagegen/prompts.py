"""Load a prompt folder into an ordered list of Job objects.

Primary format is Markdown with YAML front-matter, one file per image:

    ---
    id: 01-001-symbol                  # optional; derived from the path
    output: 01-logo/symbol.png         # optional; derived from the path
    size: 2048x2048                    # optional
    aspect: "1:1"                      # optional; derived from size
    background: transparent            # transparent | opaque
    negative: "blurry, watermark"      # optional
    ---
    The prompt text goes here.

A folder-level `imagegen.yaml` may supply defaults for every field, so shared
settings live in one place instead of being copied into 500 files.

Files without front-matter fall back to a heading/bold-field parser so existing
hand-written prompt libraries keep working unchanged.
"""

from __future__ import annotations

import fnmatch
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n(.*?)```", re.S)
SIZE_RE = re.compile(r"(\d{2,5})\s*[x×]\s*(\d{2,5})")
CONFIG_NAMES = ("imagegen.yaml", "imagegen.yml", "_defaults.yaml", "_defaults.yml")
# Documentation that lives alongside prompts and is never a prompt itself.
DEFAULT_EXCLUDES = (
    "INDEX.md", "README.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md",
    "LICENSE.md", "TODO.md", "NOTES.md",
)

# Legacy (front-matter-less) field labels, e.g. "**Asset ID:** `01-001-symbol`".
LEGACY_FIELDS = {
    "id": ("asset id", "id"),
    "output": ("output file", "output"),
    "size": ("size",),
    "aspect": ("aspect", "aspect ratio"),
    "background": ("background",),
}


class PromptError(Exception):
    """A prompt file could not be parsed into a usable job."""


@dataclass
class Job:
    id: str
    prompt: str
    output: Path            # absolute destination path
    source: Path            # absolute path of the prompt file
    rel_source: str         # prompt path relative to the prompt root
    rel_output: str         # output path relative to the output root
    negative: str = ""
    size: tuple[int, int] | None = None
    aspect: str | None = None
    background: str = "unspecified"
    extra: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def wants_transparency(self) -> bool:
        return self.background == "transparent"

    @property
    def forbids_transparency(self) -> bool:
        """An explicit opaque background: never strip it, even when forced."""
        return self.background == "opaque"

    @property
    def prompt_sha(self) -> str:
        payload = f"{self.prompt}\x00{self.negative}\x00{self.aspect}\x00{self.size}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# field coercion
# ---------------------------------------------------------------------------

def parse_size(value) -> tuple[int, int] | None:
    if value in (None, ""):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    m = SIZE_RE.search(str(value))
    if not m:
        raise PromptError(f"unparseable size: {value!r} (expected e.g. 2048x2048)")
    return int(m.group(1)), int(m.group(2))


def derive_aspect(size: tuple[int, int]) -> str:
    w, h = size
    g = math.gcd(w, h) or 1
    return f"{w // g}:{h // g}"


SLUG_OK_RE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
UNSAFE_RE = re.compile(r"[^a-z0-9.-]+")


def slugify(text: str) -> str:
    """Lowercase, dash-separated, filesystem- and URL-safe."""
    slug = UNSAFE_RE.sub("-", text.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    return slug or "untitled"


def slug_output_path(rel_path: Path) -> str:
    """Sluggify every component of an auto-derived output path.

    Applied only when a prompt file does not name its own `output:` — a prompt
    called `My Logo #2 (final).md` should not become an image whose filename
    needs quoting in every shell command that touches it.
    """
    parts = [slugify(part) for part in rel_path.parent.parts if part not in (".", "")]
    return "/".join(parts + [f"{slugify(rel_path.stem)}.png"])


def check_output_path(rel_output: str) -> list[str]:
    """Validate an author-supplied `output:`. Returns warnings; raises on unsafe.

    Traversal is rejected rather than normalised: an `output:` of `../x.png`
    writes outside the output folder, which silently scatters images across the
    filesystem and puts them where a resume will never find them again.
    """
    if Path(rel_output).is_absolute() or rel_output.startswith("~"):
        raise PromptError(f"output must be a relative path, got {rel_output!r}")
    parts = PurePosixPath(rel_output).parts
    if ".." in parts:
        raise PromptError(
            f"output must stay inside the output folder, got {rel_output!r}"
        )
    if not parts or rel_output.endswith("/"):
        raise PromptError(f"output is not a file path: {rel_output!r}")

    suffix = PurePosixPath(rel_output).suffix.lower()
    if suffix and suffix != ".png":
        raise PromptError(
            f"output must be a .png file (every image is written as PNG), got {rel_output!r}"
        )

    warnings = []
    name = PurePosixPath(rel_output).name
    stem = name[: -len(suffix)] if suffix else name
    for part in (*parts[:-1], stem):
        if not SLUG_OK_RE.match(part):
            warnings.append(
                f"output {rel_output!r} is not a clean slug "
                "(use lowercase letters, digits and dashes)"
            )
            break
    return warnings


def normalise_background(value) -> str:
    """transparent | opaque | unspecified.

    The three-way answer matters: an explicit `opaque` is an opt-out that
    --force-background-removal must respect, while a prompt file that simply
    never mentions the background stays eligible for it.
    """
    if value in (None, ""):
        return "unspecified"
    text = str(value).strip().lower()
    if text.startswith(("transparent", "alpha", "none", "no background", "cut-out", "cutout")):
        return "transparent"
    if text.startswith(("opaque", "solid", "filled", "white", "background")):
        return "opaque"
    return "unspecified"


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def _body_to_prompt(body: str) -> str:
    """Take the prompt out of a Markdown body.

    A fenced block wins when one is present — hand-written prompt files usually
    wrap the real prompt in ```text so the surrounding prose (headings, notes,
    checklists) never reaches the generator.
    """
    fences = FENCE_RE.findall(body)
    if fences:
        return fences[0].strip()
    return body.strip()


def _split_sections(text: str) -> dict[str, str]:
    """Map lowercased Markdown heading -> section body."""
    sections: dict[str, str] = {}
    current = ""
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current:
                sections[current] = "\n".join(buf)
            current = line.lstrip("#").strip().lower()
            buf = []
        else:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf)
    return sections


def _parse_legacy(text: str) -> tuple[dict, str, str]:
    """Parse a prompt file that has no YAML front-matter."""
    meta: dict = {}
    for line in text.splitlines():
        m = re.match(r"\s*\*\*(.+?):\*\*\s*(.*)", line)
        if not m:
            continue
        label = m.group(1).strip().lower()
        value = m.group(2).strip().strip("`").strip()
        for key, aliases in LEGACY_FIELDS.items():
            if label in aliases and key not in meta:
                meta[key] = value
        # "**Size:** 2048x2048 px · **Aspect:** 1:1 · **Format:** PNG" packs
        # several fields onto one line, so mine the whole line too.
        if "aspect" not in meta:
            m2 = re.search(r"aspect:?\*{0,2}\s*(\d+\s*:\s*\d+)", line, re.I)
            if m2:
                meta["aspect"] = m2.group(1).replace(" ", "")
        if "size" not in meta and SIZE_RE.search(line) and "size" in label:
            meta["size"] = line

    sections = _split_sections(text)
    prompt = ""
    negative = ""
    for name, body in sections.items():
        if not prompt and name.startswith("prompt"):
            prompt = _body_to_prompt(body)
        if not negative and name.startswith("negative"):
            negative = _body_to_prompt(body)
    if not prompt:
        prompt = _body_to_prompt(text)
    return meta, prompt, negative


def _excluded(path: Path, root: Path, patterns) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(
        fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) for pat in patterns
    )


def load_config(root: Path) -> dict:
    for name in CONFIG_NAMES:
        path = root / name
        if path.is_file():
            data = yaml.safe_load(path.read_text()) or {}
            if not isinstance(data, dict):
                raise PromptError(f"{path} must contain a YAML mapping")
            return data
    return {}


def parse_file(path: Path, root: Path, out_root: Path, defaults: dict) -> Job:
    text = path.read_text(encoding="utf-8")
    m = FRONT_MATTER_RE.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            raise PromptError("front-matter must be a YAML mapping")
        prompt = str(meta.pop("prompt", "") or "").strip() or _body_to_prompt(m.group(2))
        negative = str(meta.get("negative", "") or "").strip()
    else:
        meta, prompt, negative = _parse_legacy(text)

    merged = {**defaults, **{k: v for k, v in meta.items() if v not in (None, "")}}
    rel_source = path.relative_to(root).as_posix()

    if not prompt.strip():
        raise PromptError("no prompt text found")

    job_id = str(merged.get("id") or path.relative_to(root).with_suffix("").as_posix())

    warnings: list[str] = []
    rel_output = str(merged.get("output") or "").strip().replace("\\", "/")
    if rel_output:
        if not PurePosixPath(rel_output).suffix:
            rel_output += ".png"        # `01-logo/symbol` is an obvious intent
        warnings += check_output_path(rel_output)
    else:
        rel_output = slug_output_path(path.relative_to(root))

    size = parse_size(merged.get("size"))
    # A file that states its own size but no aspect derives the aspect from that
    # size — inheriting a folder default here would contradict the file.
    if "aspect" in meta and meta["aspect"]:
        aspect = str(meta["aspect"]).strip()
    elif "size" in meta and meta["size"] and size:
        aspect = derive_aspect(size)
    else:
        aspect = str(merged.get("aspect") or "").strip() or (derive_aspect(size) if size else None)

    prefix = str(merged.get("prompt_prefix") or "")
    suffix = str(merged.get("prompt_suffix") or "")
    if prefix:
        prompt = f"{prefix.rstrip()}\n\n{prompt}"
    if suffix:
        prompt = f"{prompt}\n\n{suffix.lstrip()}"

    known = {"id", "output", "size", "aspect", "background", "negative",
             "prompt", "prompt_prefix", "prompt_suffix"}
    return Job(
        id=job_id,
        prompt=prompt.strip(),
        output=(out_root / rel_output).resolve(),
        source=path.resolve(),
        rel_source=rel_source,
        rel_output=rel_output,
        negative=negative or str(merged.get("negative", "") or "").strip(),
        size=size,
        aspect=aspect,
        background=normalise_background(merged.get("background")),
        extra={k: v for k, v in merged.items() if k not in known},
        warnings=warnings,
    )


def load_folder(root: Path, out_root: Path) -> tuple[list[Job], list[tuple[Path, str]]]:
    """Return (jobs, errors) for every prompt file under `root`, path-sorted."""
    root = root.resolve()
    if not root.is_dir():
        raise PromptError(f"prompt folder does not exist: {root}")

    config = load_config(root)
    defaults = config.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise PromptError("`defaults` in the folder config must be a mapping")

    excludes = tuple(config.get("exclude") or ()) + DEFAULT_EXCLUDES
    out_root = out_root.resolve()
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in {".md", ".markdown", ".txt"}
        and p.name not in CONFIG_NAMES
        and not p.name.startswith((".", "_"))
        and out_root not in p.parents
        and not _excluded(p, root, excludes)
    )

    jobs: list[Job] = []
    errors: list[tuple[Path, str]] = []
    seen_ids: dict[str, Path] = {}
    seen_out: dict[str, Path] = {}
    for path in files:
        try:
            job = parse_file(path, root, out_root, defaults)
        except (PromptError, yaml.YAMLError) as exc:
            errors.append((path, str(exc)))
            continue
        if job.id in seen_ids:
            errors.append((path, f"duplicate id {job.id!r} (also in {seen_ids[job.id].name})"))
            continue
        if job.rel_output in seen_out:
            errors.append((path, f"duplicate output {job.rel_output!r} "
                                 f"(also from {seen_out[job.rel_output].name})"))
            continue
        seen_ids[job.id] = path
        seen_out[job.rel_output] = path
        jobs.append(job)
    return jobs, errors
