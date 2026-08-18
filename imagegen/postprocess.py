"""Turn raw generator bytes into the PNG that lands on disk.

Background handling follows the prompt by default: whatever the generator
returns is what gets saved. `--force-background-removal` adds a safety net for
the cases where the model ignores a "transparent background" instruction — but
it first checks whether a background is actually there. An image that already
carries a real alpha cut-out is left completely untouched.
"""

from __future__ import annotations

import io
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

def save_png(
    raw: bytes,
    dest: Path,
    *,
    size: tuple[int, int] | None,
    force_background_removal: bool,
    allow_upscale: bool = False,
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

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    im.save(tmp, "PNG", optimize=True)
    tmp.replace(dest)   # never leave a half-written file where a resume can adopt it

    return Result(
        path=dest,
        src_size=src_size,
        out_size=out_size,
        bytes_written=dest.stat().st_size,
        transparent=has_cutout_alpha(im),
        notes=notes,
    )
