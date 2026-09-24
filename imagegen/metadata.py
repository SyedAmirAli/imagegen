"""Embed descriptive metadata (title, description, keywords, author) in a saved image.

A manifest entry may carry a `meta` object:

    "meta": {
      "author": "…", "title": "…", "description": "…",
      "tags": ["apple", "fruit", …]
    }

It is written into the file itself as an XMP packet, the form Adobe Stock,
Lightroom, Bridge, exiftool and most file managers read — so the file keeps
its title and keywords wherever it is copied to, not only inside this tool.

Everything here edits the container at the byte level and never re-encodes
pixels. That is what lets it run *after* `--max-file-size` compression: the
compressed image data is kept exactly, only a small metadata chunk is added.
It must run last, because any later Pillow save would drop the chunk again.

  * PNG  — an `iTXt` chunk `XML:com.adobe.xmp`, plus the PNG-registered
           `Title` / `Author` / `Description` text keywords and `Keywords`.
  * JPEG — an APP1 XMP segment.
  * WebP — an `XMP ` chunk (the file is promoted to the extended VP8X form).
"""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

XMP_KEYWORD = b"XML:com.adobe.xmp"
JPEG_XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Text keywords written alongside the XMP in PNG; replaced on every embed.
PNG_TEXT_KEYS = ("Title", "Author", "Description", "Keywords", "Copyright")
IMAGEGEN_NS = "https://github.com/SyedAmirAli/imagegen/ns/1.0/"

# Accepted spellings for each field, first match wins.
ALIASES = {
    "title": ("title", "headline"),
    "description": ("description", "caption", "abstract"),
    "author": ("author", "creator", "artist", "by"),
    "tags": ("tags", "keywords", "subject"),
    "copyright": ("copyright", "rights"),
}
_XML_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class MetadataError(ValueError):
    pass


def from_job_extra(extra: dict | None, skip=()) -> dict | None:
    """The `meta` object of a job, when it has one.

    `skip` names manifest `meta` keys (as written in the manifest: "prompt",
    "tags", …) to leave out entirely — `--metadata-skip`.
    """
    if not isinstance(extra, dict):
        return None
    skip = {s.strip().lower() for s in skip if s and s.strip()}
    for key in ("meta", "metadata"):
        value = extra.get(key)
        if isinstance(value, dict):
            return normalise({k: v for k, v in value.items() if str(k).lower() not in skip})
    return None


def parse_skip(values) -> list[str]:
    """`--metadata-skip a,b --metadata-skip c` -> ["a", "b", "c"]."""
    out: list[str] = []
    for value in values or []:
        out += [part.strip() for part in str(value).split(",") if part.strip()]
    return out


def normalise(meta: dict | None) -> dict | None:
    """Coerce a meta object into {title, description, author, tags, copyright, extra}.

    Returns None when nothing worth writing is left, so callers can skip the
    file untouched.
    """
    if not isinstance(meta, dict):
        return None
    used: set[str] = set()
    out: dict = {}
    for field, names in ALIASES.items():
        for name in names:
            if name in meta and meta[name] not in (None, "", []):
                used.add(name)
                out[field] = meta[name]
                break

    for field in ("title", "description", "copyright"):
        if field in out:
            out[field] = str(out[field]).strip()
    if "author" in out:
        value = out["author"]
        authors = value if isinstance(value, list) else [value]
        out["author"] = [str(a).strip() for a in authors if str(a).strip()]
    if "tags" in out:
        value = out["tags"]
        tags = value if isinstance(value, list) else str(value).split(",")
        seen: set[str] = set()
        cleaned = []
        for tag in tags:
            tag = str(tag).strip()
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                cleaned.append(tag)
        out["tags"] = cleaned

    # Anything else scalar is kept too, under our own namespace, so a
    # manifest's extra fields (category, model, …) are not silently lost.
    # (A dict already normalised carries them in `extra`; take those as-is.)
    nested = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
    extra = {}
    for key, value in {**nested, **meta}.items():
        if key in used or key == "extra" or not _XML_NAME.match(str(key)):
            continue
        if isinstance(value, bool):
            extra[str(key)] = "true" if value else "false"
        elif isinstance(value, (str, int, float)) and str(value).strip():
            extra[str(key)] = str(value).strip()
    if extra:
        out["extra"] = extra

    out = {k: v for k, v in out.items() if v}
    return out or None


# ---------------------------------------------------------------------------
# XMP
# ---------------------------------------------------------------------------

def build_xmp(meta: dict) -> str:
    def alt(tag: str, text: str) -> str:
        return (f"   <{tag}><rdf:Alt><rdf:li xml:lang=\"x-default\">{escape(text)}"
                f"</rdf:li></rdf:Alt></{tag}>")

    def seq(tag: str, kind: str, items: list[str]) -> str:
        lis = "".join(f"<rdf:li>{escape(i)}</rdf:li>" for i in items)
        return f"   <{tag}><rdf:{kind}>{lis}</rdf:{kind}></{tag}>"

    props = []
    if meta.get("title"):
        props.append(alt("dc:title", meta["title"]))
        props.append(f"   <photoshop:Headline>{escape(meta['title'])}</photoshop:Headline>")
    if meta.get("description"):
        props.append(alt("dc:description", meta["description"]))
    if meta.get("author"):
        props.append(seq("dc:creator", "Seq", meta["author"]))
    if meta.get("tags"):
        props.append(seq("dc:subject", "Bag", meta["tags"]))
    if meta.get("copyright"):
        props.append(alt("dc:rights", meta["copyright"]))
    for key, value in (meta.get("extra") or {}).items():
        props.append(f"   <imagegen:{key}>{escape(value)}</imagegen:{key}>")

    body = "\n".join(props)
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"\n'
        f'    xmlns:imagegen="{IMAGEGEN_NS}">\n'
        f"{body}\n"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )


# ---------------------------------------------------------------------------
# containers
# ---------------------------------------------------------------------------

def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _png_itxt(keyword: bytes, text: str) -> bytes:
    # keyword \0 compression-flag compression-method language \0 translated \0 text
    return _png_chunk(b"iTXt", keyword + b"\x00\x00\x00\x00\x00" + text.encode("utf-8"))


def _png_chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise MetadataError("not a PNG file")
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise MetadataError("truncated PNG chunk")
        yield kind, data[pos + 8:pos + 8 + length], data[pos:end]
        pos = end
        if kind == b"IEND":
            break


def _embed_png(data: bytes, meta: dict) -> bytes:
    own_keys = {XMP_KEYWORD, *(k.encode() for k in PNG_TEXT_KEYS)}
    new = [_png_itxt(XMP_KEYWORD, build_xmp(meta))]
    text = {
        "Title": meta.get("title"),
        "Author": ", ".join(meta.get("author") or []),
        "Description": meta.get("description"),
        "Keywords": ", ".join(meta.get("tags") or []),
        "Copyright": meta.get("copyright"),
    }
    new += [_png_itxt(k.encode(), v) for k, v in text.items() if v]

    out = [PNG_SIGNATURE]
    inserted = False
    for kind, body, raw in _png_chunks(data):
        if kind in (b"iTXt", b"tEXt", b"zTXt") and body.split(b"\x00", 1)[0] in own_keys:
            continue   # an earlier embed — replace, never duplicate
        if kind == b"IDAT" and not inserted:
            out += new
            inserted = True
        out.append(raw)
    if not inserted:
        raise MetadataError("PNG has no image data")
    return b"".join(out)


def _embed_jpeg(data: bytes, meta: dict) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise MetadataError("not a JPEG file")
    payload = JPEG_XMP_HEADER + build_xmp(meta).encode("utf-8")
    if len(payload) + 2 > 0xFFFF:
        raise MetadataError("metadata too large for a single JPEG XMP segment")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload

    pos = 2
    head = [data[:2]]
    # Walk the APPn/COM segments at the front, dropping an old XMP segment.
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            break
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        seg = data[pos:pos + 2 + length]
        if marker == 0xE1 and seg[4:4 + len(JPEG_XMP_HEADER)] == JPEG_XMP_HEADER:
            pos += 2 + length
            continue
        head.append(seg)
        pos += 2 + length
    # Ours goes after a leading APP0 (JFIF) / APP1 (Exif) run, which some
    # readers expect first, else straight after SOI.
    idx = 1
    while idx < len(head) and head[idx][1] in (0xE0, 0xE1):
        idx += 1
    head.insert(idx, segment)
    return b"".join(head) + data[pos:]


def _riff_chunks(data: bytes):
    pos = 12
    while pos + 8 <= len(data):
        kind, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        end = pos + 8 + size + (size & 1)
        yield kind, data[pos + 8:pos + 8 + size], data[pos:end]
        pos = end


def _riff_chunk(kind: bytes, body: bytes) -> bytes:
    return kind + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def _embed_webp(data: bytes, meta: dict, path: Path) -> bytes:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise MetadataError("not a WebP file")
    chunks = [(k, b) for k, b, _ in _riff_chunks(data) if k != b"XMP "]
    if not chunks:
        raise MetadataError("WebP has no chunks")

    if chunks[0][0] == b"VP8X":
        header = bytearray(chunks[0][1])
        header[0] |= 0x04                      # XMP present
        chunks[0] = (b"VP8X", bytes(header))
    else:
        # A simple (VP8 / VP8L) file: promote it to the extended form, which
        # needs the canvas size and whether there is alpha.
        from PIL import Image
        with Image.open(path) as im:
            width, height = im.size
            alpha = "A" in im.getbands()
        flags = 0x04 | (0x10 if alpha else 0)
        body = (bytes([flags, 0, 0, 0])
                + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little"))
        chunks.insert(0, (b"VP8X", body))

    chunks.append((b"XMP ", build_xmp(meta).encode("utf-8")))
    payload = b"WEBP" + b"".join(_riff_chunk(k, b) for k, b in chunks)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def embed(path: Path, meta: dict | None) -> str | None:
    """Write `meta` into the image at `path`, in place. Returns a note, or None.

    A missing or empty `meta` leaves the file untouched. Unsupported formats
    are reported, not raised — metadata is never a reason to fail an image.
    """
    meta = normalise(meta)
    if not meta:
        return None
    path = Path(path)
    data = path.read_bytes()
    try:
        if data.startswith(PNG_SIGNATURE):
            new = _embed_png(data, meta)
        elif data.startswith(b"\xff\xd8"):
            new = _embed_jpeg(data, meta)
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            new = _embed_webp(data, meta, path)
        else:
            return f"metadata not embedded: {path.suffix or 'this format'} is not supported"
    except (MetadataError, struct.error, OSError) as exc:
        return f"metadata not embedded: {exc}"

    tmp = path.with_name(path.name + ".meta")
    tmp.write_bytes(new)
    tmp.replace(path)
    parts = [f for f in ("title", "description", "author", "copyright") if meta.get(f)]
    if meta.get("tags"):
        n = len(meta["tags"])
        parts.append(f"{n} keyword{'' if n == 1 else 's'}")
    if meta.get("extra"):
        parts.append(f"{len(meta['extra'])} other")
    return "metadata embedded: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# reading back (used to carry metadata onto derived files, e.g. upscales)
# ---------------------------------------------------------------------------

def read_xmp(path: Path) -> str | None:
    """The raw XMP packet in a PNG/JPEG/WebP, if there is one."""
    data = Path(path).read_bytes()
    try:
        if data.startswith(PNG_SIGNATURE):
            for kind, body, _ in _png_chunks(data):
                if kind == b"iTXt" and body.startswith(XMP_KEYWORD + b"\x00"):
                    rest = body[len(XMP_KEYWORD) + 1:]
                    compressed = rest[0] == 1
                    rest = rest[2:]
                    rest = rest.split(b"\x00", 2)[2]    # skip language, translated keyword
                    return (zlib.decompress(rest) if compressed else rest).decode("utf-8")
        elif data.startswith(b"\xff\xd8"):
            pos = 2
            while pos + 4 <= len(data) and data[pos] == 0xFF:
                length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
                seg = data[pos + 4:pos + 2 + length]
                if data[pos + 1] == 0xE1 and seg.startswith(JPEG_XMP_HEADER):
                    return seg[len(JPEG_XMP_HEADER):].decode("utf-8")
                pos += 2 + length
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            for kind, body, _ in _riff_chunks(data):
                if kind == b"XMP ":
                    return body.decode("utf-8")
    except (MetadataError, struct.error, IndexError, zlib.error, UnicodeDecodeError):
        return None
    return None


def parse_xmp(xmp: str) -> dict:
    """Pull the fields build_xmp writes back out of a packet."""
    def alt(tag: str) -> str | None:
        m = re.search(rf"<{tag}>.*?<rdf:li[^>]*>(.*?)</rdf:li>", xmp, re.S)
        return _unescape(m.group(1)) if m else None

    def items(tag: str) -> list[str]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xmp, re.S)
        if not m:
            return []
        return [_unescape(v) for v in re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", m.group(1), re.S)]

    meta: dict = {}
    if (v := alt("dc:title")):
        meta["title"] = v
    if (v := alt("dc:description")):
        meta["description"] = v
    if (v := items("dc:creator")):
        meta["author"] = v
    if (v := items("dc:subject")):
        meta["tags"] = v
    if (v := alt("dc:rights")):
        meta["copyright"] = v
    extra = {k: _unescape(v) for k, v in re.findall(r"<imagegen:([\w.-]+)>(.*?)</imagegen:\1>", xmp, re.S)}
    if extra:
        meta["extra"] = extra
    return meta


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))


def copy(src: Path, dest: Path) -> str | None:
    """Carry the metadata of `src` onto `dest` (e.g. an upscaled copy)."""
    xmp = read_xmp(src)
    if not xmp:
        return None
    meta = parse_xmp(xmp)
    if not meta:
        return None
    return embed(dest, meta)
