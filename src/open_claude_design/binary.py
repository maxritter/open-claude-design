"""Recover a stored PNG when the read transport adds a C2PA provenance chunk.

Existing provenance is preserved. A chunk is removed only when exactly one
candidate reproduces the stored file's revision-bound byte count; otherwise the
transfer fails closed. Written files are additionally compared byte for byte.
"""

from __future__ import annotations

import struct

from open_claude_design.errors import ClaudeDesignProtocolError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
