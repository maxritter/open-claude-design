"""Pure revision and receipt primitives for guarded design synchronization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from open_claude_design.config import CLAUDE_DESIGN_SYNC_SCHEMA_VERSION

SyncDirection = Literal["to-design", "to-code"]
SyncClassification = Literal["unchanged", "remote-only", "local-only", "both-changed", "unknown"]

REVIEW_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class SyncPair:
    """One declared relationship between a remote design and local code path."""

    remote_path: str
    local_path: str


def parse_pairs(values: list[str]) -> list[SyncPair]:
    """Parse repeatable REMOTE_PATH=LOCAL_PATH mappings without discarding many-to-one relations."""
    if not values:
        raise ValueError("At least one --pair is required for a sync review.")
    pairs: list[SyncPair] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if "=" not in value:
            raise ValueError(f"--pair expects REMOTE_PATH=LOCAL_PATH, got: {value}")
        remote_path, local_path = value.split("=", 1)
        if not remote_path or not local_path:
            raise ValueError(f"--pair expects non-empty REMOTE_PATH=LOCAL_PATH, got: {value}")
        key = (remote_path, local_path)
        if key in seen:
            raise ValueError(f"Duplicate sync pair: {remote_path}={local_path}")
        seen.add(key)
        pairs.append(SyncPair(remote_path=remote_path, local_path=local_path))
    return pairs


def content_sha256(data: bytes) -> str:
    """Return the stable byte-level revision used for local and remote content."""
    return hashlib.sha256(data).hexdigest()


def classify_pair(
    baseline: dict[str, Any] | None,
    *,
    remote_exists: bool,
    remote_etag: str,
    local_exists: bool,
    local_sha256: str | None,
) -> SyncClassification:
    """Classify one current pair against its last verified baseline."""
    if baseline is None:
        return "unknown"
    remote_changed = baseline.get("remote_exists") is not remote_exists or baseline.get("remote_etag") != remote_etag
    local_changed = baseline.get("local_exists") is not local_exists or baseline.get("local_sha256") != local_sha256
    if remote_changed and local_changed:
        return "both-changed"
    if remote_changed:
        return "remote-only"
    if local_changed:
        return "local-only"
    return "unchanged"


def aggregate_classification(classifications: list[SyncClassification]) -> SyncClassification:
    """Collapse pair classifications without hiding mixed-side changes."""
    changed = set(classifications) - {"unchanged"}
    if not changed:
        return "unchanged"
    if "unknown" in changed:
        return "unknown"
    if "both-changed" in changed or {"remote-only", "local-only"}.issubset(changed):
        return "both-changed"
    if changed == {"remote-only"}:
        return "remote-only"
    if changed == {"local-only"}:
        return "local-only"
    raise AssertionError(f"Unhandled synchronization classifications: {sorted(changed)}")


def canonical_digest(payload: dict[str, Any]) -> str:
    """Hash canonical JSON while excluding the self-referential digest field."""
    unsigned = {key: value for key, value in payload.items() if key != "review_digest"}
    encoded = json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy carrying an integrity digest for accidental-tampering detection."""
    sealed = dict(payload)
    sealed["review_digest"] = canonical_digest(sealed)
    return sealed


def validate_receipt(payload: object, *, review_id: str) -> dict[str, Any]:
    """Validate the bounded local receipt schema and digest."""
    if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
        raise ValueError("A sync review id must be exactly 32 lowercase hexadecimal characters.")
    if not isinstance(payload, dict):
        raise ValueError("The sync review receipt is not a JSON object.")
    if payload.get("schema_version") != CLAUDE_DESIGN_SYNC_SCHEMA_VERSION:
        raise ValueError("The sync review receipt uses an unsupported schema version.")
    if payload.get("review_id") != review_id:
        raise ValueError("The sync review receipt id does not match its path.")
    digest = payload.get("review_digest")
    if not isinstance(digest, str) or digest != canonical_digest(payload):
        raise ValueError("The sync review receipt changed after it was created.")
    if payload.get("direction") not in {"to-design", "to-code"}:
        raise ValueError("The sync review receipt has an invalid direction.")
    if payload.get("state") not in {
        "reviewed",
        "stale",
        "applying",
        "awaiting_verification",
        "unknown",
        "complete",
    }:
        raise ValueError("The sync review receipt has an invalid state.")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not pairs or not all(isinstance(pair, dict) for pair in pairs):
        raise ValueError("The sync review receipt has no valid file pairs.")
    return payload
