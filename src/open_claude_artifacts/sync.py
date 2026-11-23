"""Revision-bound artifact synchronization with account-isolated local receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from open_claude_artifacts import workspace
from open_claude_artifacts.api import (
    SHA256,
    ArtifactClient,
    ArtifactConflict,
    ArtifactOutcomeUnknown,
    ArtifactSnapshot,
    artifact_id,
    artifact_url,
    file_path,
)
from open_claude_artifacts.config import (
    ARTIFACT_MAX_SYNC_BYTES,
    ARTIFACT_MAX_SYNC_DIFF_BYTES,
    ARTIFACT_MAX_SYNC_PAIRS,
    ARTIFACT_SYNC_PARTS,
    ARTIFACT_SYNC_SCHEMA_VERSION,
)
from open_claude_artifacts.errors import ArtifactSafetyError
from open_claude_artifacts.operation_locks import operation_lock

SyncDirection = Literal["to-design", "to-code"]
SyncClassification = Literal["unchanged", "remote-only", "local-only", "both-changed", "unknown"]

REVIEW_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class SyncPair:
    """One declared relationship between a remote artifact file and local code path."""

    remote_path: str
    local_path: str


def parse_pairs(values: list[str]) -> list[SyncPair]:
    """Parse repeatable REMOTE_PATH=LOCAL_PATH mappings."""
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
    return hashlib.sha256(data).hexdigest()


def classify_pair(
    baseline: dict[str, Any] | None,
    *,
    remote_exists: bool,
    remote_etag: str,
    local_exists: bool,
    local_sha256: str | None,
) -> SyncClassification:
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
    unsigned = {key: value for key, value in payload.items() if key != "review_digest"}
    encoded = json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["review_digest"] = canonical_digest(sealed)
    return sealed


def validate_receipt(payload: object, *, review_id: str) -> dict[str, Any]:
    if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
        raise ValueError("A sync review id must be exactly 32 lowercase hexadecimal characters.")
    if not isinstance(payload, dict):
        raise ValueError("The sync review receipt is not a JSON object.")
    if payload.get("schema_version") != ARTIFACT_SYNC_SCHEMA_VERSION:
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


def review_directory(root: Path, review_id: str) -> Path:
    if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
        raise ValueError("An artifact review id must be 32 lowercase hexadecimal characters.")
    return root.joinpath(*ARTIFACT_SYNC_PARTS, "reviews", review_id)


def save(root: Path, receipt: dict[str, Any]) -> None:
    path = review_directory(root, receipt["review_id"]) / "receipt.json"
    workspace.write_json(root, path, seal_receipt(receipt), force=path.exists())


def load(root: Path, review_id: str) -> dict[str, Any]:
    directory = review_directory(root, review_id)
    receipt = validate_receipt(workspace.read_json(root, directory / "receipt.json"), review_id=review_id)
    if receipt.get("schema_version") != ARTIFACT_SYNC_SCHEMA_VERSION:
        raise ValueError("This is not a supported artifact review receipt.")
    artifact_id(receipt.get("artifact_id", ""))
    if not isinstance(receipt.get("identity"), str) or not SHA256.fullmatch(receipt["identity"]):
        raise ValueError("Artifact receipt lacks its login identity.")
    if receipt.get("classification") not in {"unchanged", "remote-only", "local-only", "both-changed", "unknown"}:
        raise ValueError("Artifact receipt has an invalid classification.")
    if not isinstance(receipt.get("version"), str) or not isinstance(receipt.get("type_id"), str):
        raise ValueError("Artifact receipt lacks its version and native type.")
    if len(receipt["pairs"]) > ARTIFACT_MAX_SYNC_PAIRS:
        raise ValueError("Artifact receipt exceeds the pair limit.")
    seen: set[tuple[str, str]] = set()
    for index, pair in enumerate(receipt["pairs"]):
        file_path(pair.get("remote_path", ""), write=True)
        workspace.validate_local_relative_path(pair.get("local_path"))
        key = (pair["remote_path"], pair["local_path"])
        if key in seen:
            raise ValueError("Artifact receipt repeats a pair.")
        seen.add(key)
        for side in ("local", "remote"):
            exists, digest = pair.get(f"{side}_exists"), pair.get(f"{side}_sha256")
            if not isinstance(exists, bool) or (
                exists and (not isinstance(digest, str) or not SHA256.fullmatch(digest))
            ):
                raise ValueError("Artifact receipt has an invalid content revision.")
            if not exists and digest is not None:
                raise ValueError("Artifact receipt has an invalid missing-file revision.")
            expected = (directory / "snapshots" / f"{index:03d}-{side}.bin").relative_to(root).as_posix()
            if pair.get(f"{side}_snapshot") != expected:
                raise ValueError("Artifact receipt snapshot escapes its assigned path.")
    return receipt


def ledger_path(root: Path, receipt: dict[str, Any], pair: dict[str, Any]) -> Path:
    key = "\0".join((receipt["identity"], receipt["artifact_id"], pair["remote_path"], pair["local_path"]))
    return root.joinpath(*ARTIFACT_SYNC_PARTS, "ledger", hashlib.sha256(key.encode()).hexdigest() + ".json")


def public(receipt: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: receipt[key]
        for key in ("review_id", "artifact_id", "direction", "state", "classification", "version", "pairs")
    }
    result.update(
        {
            "url": artifact_url(receipt["artifact_id"]),
            "mutated": receipt.get("mutated", False),
            "render_executed": False,
            "reviewed_version": receipt["version"],
            "version": receipt.get("applied_version", receipt["version"]),
        }
    )
    if receipt["state"] != "complete":
        result["diff_path"] = receipt["diff_path"]
    return result


def review(args: argparse.Namespace, client: ArtifactClient, root: Path) -> dict[str, Any]:
    pairs = parse_pairs(args.pairs)
    if len(pairs) > ARTIFACT_MAX_SYNC_PAIRS:
        raise ValueError("Review at most 64 file pairs at a time.")
    if args.direction == "to-design" and len({pair.remote_path for pair in pairs}) != len(pairs):
        raise ValueError("A to-design review needs one local source for each remote file.")
    for pair in pairs:
        file_path(pair.remote_path, write=True)
        workspace.read_optional_local(root, pair.local_path)
    snapshot = client.snapshot(artifact_id(args.artifact_id))
    if snapshot.type_id is None or client.describe_type(snapshot.type_id).get("title") != "Design":
        raise ArtifactSafetyError("Artifact sync supports native Design artifacts only.")
    receipt: dict[str, Any] = {
        "schema_version": ARTIFACT_SYNC_SCHEMA_VERSION,
        "identity": client.identity(),
        "review_id": uuid.uuid4().hex,
        "artifact_id": snapshot.id,
        "version": snapshot.version,
        "type_id": snapshot.type_id,
        "direction": args.direction,
        "state": "reviewed",
        "created_at": int(time.time()),
        "pairs": [],
    }
    directory = review_directory(root, receipt["review_id"])
    workspace.ensure_state_ignored(root)
    sections, classifications, total = [], [], 0
    for index, mapping in enumerate(pairs):
        local_path, local_exists, local = workspace.read_optional_local(root, mapping.local_path)
        row = snapshot.files.get(mapping.remote_path)
        remote = client.read_file(snapshot, mapping.remote_path) if row else b""
        total += len(local) + len(remote)
        if total > ARTIFACT_MAX_SYNC_BYTES:
            raise ArtifactSafetyError("Artifact review exceeds 32 MiB; use a smaller batch.")
        local_digest = content_sha256(local) if local_exists else None
        remote_etag = row.sha256 if row else "0"
        entry: dict[str, Any] = {
            "remote_path": mapping.remote_path,
            "local_path": local_path,
            "local_exists": local_exists,
            "local_sha256": local_digest,
            "remote_exists": row is not None,
            "remote_sha256": row.sha256 if row else None,
            "remote_etag": remote_etag,
        }
        path = ledger_path(root, receipt, entry)
        baseline = workspace.read_json(root, path) if path.exists() else None
        if baseline is not None and (
            baseline.get("review_digest") != canonical_digest(baseline)
            or baseline.get("identity") != receipt["identity"]
            or baseline.get("artifact_id") != snapshot.id
            or baseline.get("remote_path") != entry["remote_path"]
            or baseline.get("local_path") != local_path
        ):
            raise ValueError("Artifact sync baseline changed unexpectedly.")
        classification = classify_pair(
            baseline,
            remote_exists=row is not None,
            remote_etag=remote_etag,
            local_exists=local_exists,
            local_sha256=local_digest,
        )
        classifications.append(classification)
        entry["classification"] = classification
        for side, data in (("local", local), ("remote", remote)):
            path = directory / "snapshots" / f"{index:03d}-{side}.bin"
            workspace.atomic_write_local(path, data, force=False, workspace_root=root, authorized_external_paths=[])
            entry[f"{side}_snapshot"] = path.relative_to(root).as_posix()
        sections.append(workspace.diff_bytes(remote, local, old_label=mapping.remote_path, new_label=local_path))
        receipt["pairs"].append(entry)
    diff = b"\n".join(sections)
    if len(diff) > ARTIFACT_MAX_SYNC_DIFF_BYTES:
        raise ArtifactSafetyError("Artifact review diff is too large; use a smaller batch.")
    diff_path = directory / "diff.patch"
    workspace.atomic_write_local(diff_path, diff, force=False, workspace_root=root, authorized_external_paths=[])
    receipt["diff_path"] = diff_path.relative_to(root).as_posix()
    receipt["classification"] = aggregate_classification(classifications)
    save(root, receipt)
    return receipt


def current(client: ArtifactClient, root: Path, receipt: dict[str, Any], *, local: bool) -> ArtifactSnapshot:
    if client.identity() != receipt["identity"]:
        raise ArtifactSafetyError("Artifact login changed since review; prepare a new review.")
    snapshot = client.snapshot(receipt["artifact_id"])
    if snapshot.type_id != receipt["type_id"] or snapshot.version != receipt.get("applied_version", receipt["version"]):
        raise ArtifactConflict("Artifact version changed since review; prepare a new review.")
    for pair in receipt["pairs"]:
        row = snapshot.files.get(pair["remote_path"])
        expected = pair.get("applied_remote_sha256", pair["remote_sha256"])
        if (row.sha256 if row else None) != expected:
            raise ArtifactConflict("Artifact file changed since review; prepare a new review.")
        if local:
            _, exists, data = workspace.read_optional_local(root, pair["local_path"])
            if exists != pair["local_exists"] or (content_sha256(data) if exists else None) != pair["local_sha256"]:
                raise ArtifactConflict("Local source changed since review; prepare a new review.")
    return snapshot


def snapshot_bytes(root: Path, pair: dict[str, Any], side: str) -> bytes:
    data = workspace.read_snapshot(root, pair[f"{side}_snapshot"])
    expected = pair[f"{side}_sha256"] or content_sha256(b"")
    if content_sha256(data) != expected:
        raise ArtifactSafetyError("Artifact review snapshot changed; prepare a new review.")
    return data


def apply(args: argparse.Namespace, client: ArtifactClient, root: Path, receipt: dict[str, Any]) -> None:
    if receipt["state"] != "reviewed":
        raise ArtifactSafetyError("This artifact review has already been consumed; prepare a fresh review.")
    if not args.allow_write:
        raise ArtifactSafetyError("Applying an artifact review requires --allow-write and explicit user approval.")
    if receipt["classification"] == "both-changed" and not args.reconciled:
        raise ArtifactSafetyError("Both sides changed; reconcile them, review again, and approve with --reconciled.")
    snapshot = current(client, root, receipt, local=True)
    side = "local" if receipt["direction"] == "to-design" else "remote"
    approved = [snapshot_bytes(root, pair, side) for pair in receipt["pairs"]]
    if any(pair[f"{side}_exists"] is not True for pair in receipt["pairs"]):
        raise ArtifactSafetyError("Artifact sync does not apply deletions or missing sources.")
    if side == "local":
        files = {pair["remote_path"]: data for pair, data in zip(receipt["pairs"], approved, strict=True)}
        files = {
            path: data
            for path, data in files.items()
            if path not in snapshot.files or content_sha256(data) != snapshot.files[path].sha256
        }
        matches = {pair["remote_path"]: pair["remote_sha256"] or "0" for pair in receipt["pairs"]}
        if files:
            matches = {path: matches[path] for path in files}
            client.validate_design(snapshot, files)
            client.require_write_window()
            receipt["state"] = "applying"
            save(root, receipt)
            try:
                result = client.push(snapshot, files, matches)
            except ArtifactConflict:
                receipt["state"] = "stale"
                save(root, receipt)
                raise
            except Exception as error:
                receipt["state"] = "unknown"
                save(root, receipt)
                raise ArtifactOutcomeUnknown(
                    "Artifact apply lacks verified completion; reconcile before a new review."
                ) from error
            receipt["applied_version"] = result["version"]
            receipt["mutated"] = True
        for pair, data in zip(receipt["pairs"], approved, strict=True):
            pair["applied_remote_sha256"] = content_sha256(data)
    receipt["state"] = "awaiting_verification"
    save(root, receipt)
    if args.open_browser:
        workspace.open_durable_url(artifact_url(snapshot.id))


def finish(client: ArtifactClient, root: Path, receipt: dict[str, Any]) -> None:
    if receipt["state"] != "awaiting_verification":
        raise ArtifactSafetyError("Finish requires a successfully applied review awaiting verification.")
    snapshot = current(client, root, receipt, local=receipt["direction"] == "to-design")
    for pair in receipt["pairs"]:
        row = snapshot.files.get(pair["remote_path"])
        if row:
            client.read_file(snapshot, pair["remote_path"])
    client.validate_design(snapshot, {})
    current(client, root, receipt, local=receipt["direction"] == "to-design")
    for pair in receipt["pairs"]:
        _, exists, data = workspace.read_optional_local(root, pair["local_path"])
        if not exists:
            raise ArtifactSafetyError("Implement every declared local path before finishing the artifact handoff.")
        baseline = {
            "identity": receipt["identity"],
            "artifact_id": receipt["artifact_id"],
            "remote_path": pair["remote_path"],
            "local_path": pair["local_path"],
            "remote_exists": pair["remote_path"] in snapshot.files,
            "remote_etag": snapshot.files[pair["remote_path"]].sha256 if pair["remote_path"] in snapshot.files else "0",
            "local_exists": exists,
            "local_sha256": content_sha256(data),
        }
        path = ledger_path(root, receipt, pair)
        workspace.write_json(root, path, seal_receipt(baseline), force=path.exists())
    receipt["state"] = "complete"
    save(root, receipt)
    for pair in receipt["pairs"]:
        for side in ("local", "remote"):
            path = workspace.resolve_local_path(
                str(root / pair[f"{side}_snapshot"]),
                workspace_root=root,
                authorized_external_paths=[],
                require_file=True,
            )
            path.unlink()
    path = review_directory(root, receipt["review_id"]) / "diff.patch"
    path = workspace.resolve_local_path(str(path), workspace_root=root, authorized_external_paths=[], require_file=True)
    path.unlink()


def run_sync(args: argparse.Namespace, factory: Callable[[], Any], root: Path) -> int:
    command = args.sync_command
    if command == "status":
        if args.review_id:
            payload = public(load(root, args.review_id))
        else:
            directory = root.joinpath(*ARTIFACT_SYNC_PARTS, "reviews")
            workspace.resolve_local_path(
                str(directory), workspace_root=root, authorized_external_paths=[], require_file=False
            )
            payload = {
                "reviews": [
                    public(load(root, path.name))
                    for path in sorted(directory.glob("*"))
                    if REVIEW_ID_PATTERN.fullmatch(path.name)
                ],
            }
        workspace.print_result(payload, json_mode=args.json)
        return 0
    if command == "review":
        receipt = review(args, factory(), root)
        workspace.print_result(public(receipt), json_mode=args.json)
        return 0
    receipt = load(root, args.review_id)
    with operation_lock("artifact-sync:" + str(root) + ":" + receipt["artifact_id"]):
        receipt = load(root, args.review_id)
        try:
            if command == "apply":
                apply(args, factory(), root, receipt)
            else:
                finish(factory(), root, receipt)
        except ArtifactConflict:
            receipt["state"] = "stale"
            save(root, receipt)
            workspace.print_result(public(receipt), json_mode=args.json)
            return 3
        except ArtifactOutcomeUnknown:
            workspace.print_result(public(receipt), json_mode=args.json)
            return 2
        workspace.print_result(public(receipt), json_mode=args.json)
    return 0
