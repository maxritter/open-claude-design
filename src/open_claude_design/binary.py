"""Reconcile Claude Design's C2PA provenance with the bytes an agent wrote.

Claude Design's read transport adds a C2PA manifest to raster images: a
``caBX`` chunk in PNG, an APP11 JUMBF segment in JPEG, and a ``C2PA`` chunk in
WebP. Existing provenance is preserved. A container is removed only when
exactly one candidate reproduces the stored file's revision-bound byte count;
otherwise the transfer fails closed. Written files are additionally compared
byte for byte.

SVG is different: Claude Design re-serializes it on write and adds a C2PA
``<metadata>`` manifest, so a written SVG can only be verified as equivalent
XML once that manifest is removed.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ElementTree

from open_claude_design.errors import ClaudeDesignProtocolError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
WEBP_SIGNATURE = (b"RIFF", b"WEBP")
C2PA_NAMESPACE = "http://c2pa.org/manifest"
SVG_METADATA = "{http://www.w3.org/2000/svg}metadata"


def has_read_provenance_format(data: bytes) -> bool:
    """Return whether the read transport may have added C2PA to these bytes."""
    return data.startswith((PNG_SIGNATURE, JPEG_SIGNATURE)) or _is_webp(data)


def original_image_bytes(data: bytes, source_size: int) -> bytes:
    if len(data) == source_size:
        return data
    if data.startswith(PNG_SIGNATURE):
        return original_png_bytes(data, source_size)
    if data.startswith(JPEG_SIGNATURE):
        candidates = _jpeg_candidates(data, source_size)
    elif _is_webp(data):
        candidates = _webp_candidates(data, source_size)
    else:
        raise ClaudeDesignProtocolError("The raw image does not match its stored byte count.")
    if len(candidates) != 1:
        raise ClaudeDesignProtocolError("The raw image cannot be reconciled with its original stored bytes.")
    return candidates[0]


def original_png_bytes(data: bytes, source_size: int) -> bytes:
    if len(data) == source_size:
        return data
    if not data.startswith(PNG_SIGNATURE) or source_size < len(PNG_SIGNATURE):
        raise ClaudeDesignProtocolError("The raw image does not match its stored byte count.")
    offset = len(PNG_SIGNATURE)
    candidates: list[bytes] = []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ClaudeDesignProtocolError("The raw PNG contains an incomplete chunk.")
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + size + 12
        if end > len(data):
            raise ClaudeDesignProtocolError("The raw PNG contains an incomplete chunk.")
        if data[offset + 4 : offset + 8] == b"caBX" and len(data) - (end - offset) == source_size:
            candidates.append(data[:offset] + data[end:])
        offset = end
    if len(candidates) != 1:
        raise ClaudeDesignProtocolError("The raw PNG cannot be reconciled with its original stored bytes.")
    return candidates[0]


def _jpeg_candidates(data: bytes, source_size: int) -> list[bytes]:
    """Remove one APP11 JUMBF segment; scanning stops at the first scan header."""
    offset = len(JPEG_SIGNATURE)
    candidates: list[bytes] = []
    while True:
        if offset + 4 > len(data) or data[offset] != 0xFF:
            raise ClaudeDesignProtocolError("The raw JPEG contains an incomplete segment.")
        marker = data[offset + 1]
        if marker == 0xDA:
            return candidates
        end = offset + 2 + struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if end > len(data):
            raise ClaudeDesignProtocolError("The raw JPEG contains an incomplete segment.")
        if marker == 0xEB and data[offset + 4 : offset + 6] == b"JP" and len(data) - (end - offset) == source_size:
            candidates.append(data[:offset] + data[end:])
        offset = end


def _is_webp(data: bytes) -> bool:
    return data[:4] == WEBP_SIGNATURE[0] and data[8:12] == WEBP_SIGNATURE[1]


def _webp_candidates(data: bytes, source_size: int) -> list[bytes]:
    """Remove one ``C2PA`` chunk and restore the RIFF container size."""
    if struct.unpack("<I", data[4:8])[0] + 8 != len(data):
        raise ClaudeDesignProtocolError("The raw WebP container size does not match its bytes.")
    offset = 12
    candidates: list[bytes] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ClaudeDesignProtocolError("The raw WebP contains an incomplete chunk.")
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        end = offset + 8 + size + (size & 1)
        if end > len(data):
            raise ClaudeDesignProtocolError("The raw WebP contains an incomplete chunk.")
        if data[offset : offset + 4] == b"C2PA" and len(data) - (end - offset) == source_size:
            body = data[12:offset] + data[end:]
            candidates.append(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body)
        offset = end
    return candidates


def svg_equivalent(written: bytes, stored: bytes) -> bool:
    """Compare SVG as canonical XML after removing Claude Design's C2PA manifest."""
    try:
        return _canonical_svg(written) == _canonical_svg(stored)
    except (ElementTree.ParseError, UnicodeError, ValueError):
        return False


def _canonical_svg(data: bytes) -> str:
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("SVG with a document type is not compared semantically.")
    root = ElementTree.fromstring(data)
    for parent in root.iter():
        for child in list(parent):
            if (
                child.tag == SVG_METADATA
                and len(child)
                and all(str(item.tag).startswith(f"{{{C2PA_NAMESPACE}}}") for item in child)
            ):
                parent.remove(child)
    return ElementTree.canonicalize(ElementTree.tostring(root, encoding="unicode"))
