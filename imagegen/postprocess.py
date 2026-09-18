"""Turn raw generator bytes into the image file that lands on disk.

Background handling follows the prompt by default: whatever the generator
returns is what gets saved. `--force-background-removal` adds a safety net for
the cases where the model ignores a "transparent background" instruction — but
it first checks whether a background is actually there. An image that already
carries a real alpha cut-out is left completely untouched.

Every image is saved as PNG unless its own `output:` extension asks for
something else (only allowed with `--allow-any-format`, see prompts.py) — PNG
is lossless and keeps alpha, so it is the safe default for a format nobody
asked to think about.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# A pixel is "see-through" below this alpha; 250 rather than 255 tolerates the
# near-opaque values lossy encoders leave behind on a genuinely transparent edge.
ALPHA_OPAQUE_CUTOFF = 250
# Fraction of pixels that must be see-through before we call an image a cut-out.
TRANSPARENT_MIN_FRACTION = 0.01
# Border-colour spread (0-255, per channel) still considered a flat backdrop.
FLAT_BORDER_TOLERANCE = 18
FLOODFILL_THRESHOLD = 32

# Colour-count ladder for compression, highest quality first. PNG palettes hold
# at most 256 entries, so this is the entire range available.
COLOUR_LADDER = (256, 192, 128, 96, 64, 48, 32)

# Extensions imagegen can write, mapped to the Pillow format name. PNG is the
# only one used unless --allow-any-format opts an author's own `output:` into
# one of the rest (see prompts.check_output_path).
FORMATS_BY_EXTENSION = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tiff": "TIFF",
    ".tif": "TIFF",
}
WRITABLE_EXTENSIONS = frozenset(FORMATS_BY_EXTENSION)

# Formats with no alpha channel: the image is flattened onto white before
# saving rather than plain mode-converted, which would keep the raw RGB
# under a translucent pixel and can leave a dark fringe at an antialiased
# cut-out edge.
OPAQUE_ONLY_FORMATS = {"JPEG", "BMP"}

# Quality ladder for --max-file-size on lossy formats, highest first.
QUALITY_LADDER = (90, 80, 70, 60, 50, 40, 30, 20)


# ---------------------------------------------------------------------------
# compression
# ---------------------------------------------------------------------------

def _pngquant_available() -> bool:
    return shutil.which("pngquant") is not None


def _pngquant(src: Path, colours: int) -> bytes | None:
    """Quantize with pngquant, which dithers and handles alpha far better."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        result = subprocess.run(
            ["pngquant", "--force", "--strip", "--speed", "1",
             str(colours), "--output", str(out), str(src)],
            capture_output=True, timeout=180,
        )
        # exit 98/99 mean "could not reach the quality floor"; anything written
        # is still usable, so judge by the file rather than the status code.
        if out.is_file() and out.stat().st_size > 0:
            return out.read_bytes()
        del result
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        out.unlink(missing_ok=True)


def _quantize_pillow(im: Image.Image, colours: int) -> bytes:
    quantized = im.quantize(colors=colours, method=Image.FASTOCTREE)
    buf = io.BytesIO()
    quantized.save(buf, "PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def compress_to_limit(dest: Path, max_bytes: int, fmt: str = "PNG") -> str | None:
    """Shrink `dest` (already written as `fmt`) below max_bytes. Returns a note.

    Never resizes — only ever reduces colour depth (PNG) or re-encodes at a
    lower quality (JPEG/WEBP) — so the image stays usable at the size it was
    generated for. Works down the ladder from the highest quality that fits,
    rather than jumping straight to the smallest, so an image barely over the
    limit is barely touched.
    """
    if fmt == "PNG":
        return _compress_png_to_limit(dest, max_bytes)
    if fmt in ("JPEG", "WEBP"):
        return _compress_lossy_to_limit(dest, max_bytes, fmt)
    original = dest.stat().st_size
    if original > max_bytes:
        return (f"{original // 1024}KB is over the {max_bytes // 1024}KB limit but "
                f"imagegen has no compressor for {fmt} — left as generated")
    return None


def _compress_png_to_limit(dest: Path, max_bytes: int) -> str | None:
    original = dest.stat().st_size
    if original <= max_bytes:
        return None

    im = Image.open(dest)
    im.load()
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    size = im.size

    use_pngquant = _pngquant_available()
    best: bytes | None = None
    for colours in COLOUR_LADDER:
        data = _pngquant(dest, colours) if use_pngquant else None
        if data is None:
            data = _quantize_pillow(im, colours)
        if best is None or len(data) < len(best):
            best = data
        if len(data) <= max_bytes:
            dest.write_bytes(data)
            tool = "pngquant" if use_pngquant else "palette"
            return (f"compressed {original // 1024}KB -> {len(data) // 1024}KB "
                    f"at {size[0]}x{size[1]} ({tool}, {colours} colours)")

    if best is not None and len(best) < original:
        dest.write_bytes(best)
        return (f"compressed {original // 1024}KB -> {len(best) // 1024}KB, still above "
                f"the {max_bytes // 1024}KB limit (32 colours is as far as PNG goes)")
    return f"could not compress below {max_bytes // 1024}KB without resizing; left as generated"


def _compress_lossy_to_limit(dest: Path, max_bytes: int, fmt: str) -> str | None:
    original = dest.stat().st_size
    if original <= max_bytes:
        return None

    im = Image.open(dest)
    im.load()
    if im.mode not in ("RGB", "L", "RGBA"):
        im = im.convert("RGB")

    best: bytes | None = None
    best_quality = None
    for quality in QUALITY_LADDER:
        buf = io.BytesIO()
        im.save(buf, fmt, quality=quality, optimize=True)
        data = buf.getvalue()
        if best is None or len(data) < len(best):
            best, best_quality = data, quality
        if len(data) <= max_bytes:
            dest.write_bytes(data)
            return (f"compressed {original // 1024}KB -> {len(data) // 1024}KB "
                    f"at quality {quality}")

    if best is not None and len(best) < original:
        dest.write_bytes(best)
        return (f"compressed {original // 1024}KB -> {len(best) // 1024}KB, still above "
                f"the {max_bytes // 1024}KB limit (quality {best_quality} is as low as this goes)")
    return f"could not compress below {max_bytes // 1024}KB without resizing; left as generated"


@dataclass
class Result:
    path: Path
    src_size: tuple[int, int]
    out_size: tuple[int, int]
    bytes_written: int
    transparent: bool
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# inspection
# ---------------------------------------------------------------------------

def transparent_fraction(im: Image.Image) -> float:
    # A palette image keeps its transparency in the palette, not in an A band,
    # which is exactly what a compressed output looks like — convert first or
    # every quantized image reports itself as opaque.
    if im.mode in ("P", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
    if "A" not in im.getbands():
        return 0.0
    alpha = np.asarray(im.getchannel("A"))
    return float((alpha < ALPHA_OPAQUE_CUTOFF).mean())


def has_cutout_alpha(im: Image.Image) -> bool:
    """True when the image is already a real cut-out, not just RGBA-tagged."""
    return transparent_fraction(im) >= TRANSPARENT_MIN_FRACTION


def border_pixels(im: Image.Image) -> np.ndarray:
    arr = np.asarray(im.convert("RGB"), dtype=np.int16)
    return np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])


def has_flat_background(im: Image.Image) -> tuple[bool, tuple[int, int, int]]:
    """Is the frame ringed by one flat colour we can safely flood away?"""
    edge = border_pixels(im)
    median = np.median(edge, axis=0)
    spread = np.abs(edge - median).max(axis=1)
    # Ignore the worst 2% — a subject that touches the frame skews the max.
    flat = float(np.percentile(spread, 98)) <= FLAT_BORDER_TOLERANCE
    return flat, tuple(int(v) for v in median)


# ---------------------------------------------------------------------------
# background removal
# ---------------------------------------------------------------------------

def _rembg_remove(im: Image.Image) -> Image.Image | None:
    try:
        from rembg import remove  # optional heavyweight dependency
    except Exception:
        return None
    return remove(im.convert("RGBA")).convert("RGBA")


def _floodfill_remove(im: Image.Image) -> Image.Image:
    """Flood the flat backdrop away from the frame edges.

    Seeded only from the border, so an interior region that happens to match the
    background colour (a white shirt, a white highlight) keeps its pixels.
    """
    rgb = im.convert("RGB")
    work = rgb.copy()
    sentinel = (255, 0, 255)
    w, h = work.size
    seeds = [
        (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
        (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2),
    ]
    for seed in seeds:
        try:
            ImageDraw.floodfill(work, seed, sentinel, thresh=FLOODFILL_THRESHOLD)
        except ValueError:
            continue

    # Per-channel comparison; a luminance diff alone can read a real colour as
    # the sentinel when the channel deltas happen to cancel out.
    diff = ImageChops.difference(work, Image.new("RGB", work.size, sentinel))
    r, g, b = diff.split()
    combined = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = combined.point(lambda v: 0 if v < 8 else 255)      # 0 = background

    # Eat the one-pixel matte fringe the flood leaves behind, then soften the
    # cut so the edge does not look stair-stepped at full resolution.
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))

    out = rgb.convert("RGBA")
    if "A" in im.getbands():
        mask = ImageChops.darker(mask, im.getchannel("A"))
    out.putalpha(mask)
    return out


def strip_background(im: Image.Image) -> tuple[Image.Image, str]:
    """Return (image, note). Never raises — a failed strip keeps the original."""
    if has_cutout_alpha(im):
        return im, "already transparent, background removal skipped"

    viad = _rembg_remove(im)
    if viad is not None and has_cutout_alpha(viad):
        return viad, "background removed (rembg)"

    flat, colour = has_flat_background(im)
    if not flat:
        return im, ("background NOT removed: no flat backdrop detected and rembg "
                    "is unavailable — left as generated")
    stripped = _floodfill_remove(im)
    if not has_cutout_alpha(stripped):
        return im, "background removal produced no cut-out — left as generated"
    return stripped, f"background removed (flood fill from rgb{colour})"


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def save_image(
    raw: bytes,
    dest: Path,
    *,
    size: tuple[int, int] | None,
    force_background_removal: bool,
    allow_upscale: bool = False,
    max_file_bytes: int | None = None,
) -> Result:
    im = Image.open(io.BytesIO(raw))
    im.load()
    src_size = im.size
    notes: list[str] = []

    if im.mode != "RGBA":
        im = im.convert("RGBA")

    if force_background_removal:
        im, note = strip_background(im)
        notes.append(note)

    out_size = src_size
    if size and size != im.size:
        if size[0] > im.size[0] or size[1] > im.size[1]:
            if allow_upscale:
                im = im.resize(size, Image.LANCZOS)
                notes.append(f"upscaled {src_size[0]}x{src_size[1]} -> {size[0]}x{size[1]}")
                out_size = size
            else:
                notes.append(
                    f"kept native {src_size[0]}x{src_size[1]} "
                    f"(requested {size[0]}x{size[1]} would upscale; pass --allow-upscale)"
                )
        else:
            im = im.resize(size, Image.LANCZOS)
            out_size = size

    fmt = FORMATS_BY_EXTENSION.get(dest.suffix.lower(), "PNG")
    to_save = im
    if fmt in OPAQUE_ONLY_FORMATS:
        # A plain mode convert keeps whatever raw RGB sits under a translucent
        # pixel, which can fringe dark at an antialiased cut-out edge — paste
        # onto white using the real alpha instead.
        flattened = Image.new("RGB", im.size, (255, 255, 255))
        flattened.paste(im, mask=im.getchannel("A"))
        to_save = flattened

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    save_kwargs = {"optimize": True}
    if fmt == "JPEG":
        save_kwargs["quality"] = 95
    to_save.save(tmp, fmt, **save_kwargs)
    tmp.replace(dest)   # never leave a half-written file where a resume can adopt it

    if max_file_bytes:
        note = compress_to_limit(dest, max_file_bytes, fmt)
        if note:
            notes.append(note)

    return Result(
        path=dest,
        src_size=src_size,
        out_size=out_size,
        bytes_written=dest.stat().st_size,
        transparent=has_cutout_alpha(Image.open(dest)),
        notes=notes,
    )
