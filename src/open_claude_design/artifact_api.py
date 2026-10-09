"""Experimental frame protocol, with separate control- and content-plane credentials."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from open_claude_design.artifact_auth import load_artifact_credential
from open_claude_design.auth import DesignAuthError
from open_claude_design.config import (
    ARTIFACT_API_ORIGIN,
    ARTIFACT_API_PREFIX,
    ARTIFACT_MAX_FILE_BYTES,
    ARTIFACT_MAX_FILES,
    ARTIFACT_MAX_LIST_PAGES,
    ARTIFACT_MAX_RESPONSE_BYTES,
    ARTIFACT_MAX_WRITE_BYTES,
    ARTIFACT_MAX_WRITE_FILES,
    ARTIFACT_OAUTH_BETA,
    ARTIFACT_PROTOCOL_CLIENT_VERSION,
    CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS,
    VERSION,
)
from open_claude_design.errors import ClaudeDesignAuthError, ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.migration import resolve_target
from open_claude_design.validation import validate_html

ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
REVISION = re.compile(r"[A-Za-z0-9_.-]{1,64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")


class ArtifactConflict(ClaudeDesignSafetyError):
    """The server refused this entire conditional write; no file was overwritten."""


class ArtifactOutcomeUnknown(ClaudeDesignProtocolError):
    """A submitted mutation lacks enough evidence to report its outcome."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(_NoRedirect())


def artifact_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Artifact id must be a string.")
    if ID.fullmatch(value):
        return value
    resolved = resolve_target(value)
    if resolved["backend"] != "artifact" or ID.fullmatch(resolved["resource_id"]) is None:
        raise ValueError("Use an artifact id or Claude artifact URL; standalone project URLs use project commands.")
    return resolved["resource_id"]


def artifact_url(value: str) -> str:
    return f"https://claude.ai/code/artifact/{artifact_id(value)}"


def file_path(value: str, *, write: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Artifact file path must be a string.")
    if len(value) > 512 or PATH.fullmatch(value) is None or any(len(part) > 200 for part in value.split("/")):
        raise ValueError("Artifact file paths must be canonical relative paths without spaces or traversal.")
    if write and not value.startswith("project/"):
        raise ClaudeDesignSafetyError(
            "Design artifact writes are restricted to project/; the host owns the runtime files."
        )
    return value


def _revision(value: object) -> str:
    if not isinstance(value, str) or REVISION.fullmatch(value) is None:
        raise ClaudeDesignProtocolError("Artifact service returned an invalid version.")
    return value


@dataclass(frozen=True)
class ArtifactFile:
    sha256: str
    size: int
    content_type: str


@dataclass(frozen=True)
class ArtifactSnapshot:
    id: str
    version: str
    title: str
    role: str
    read_mode: str
    type_id: str | None
    files: dict[str, ArtifactFile]
    publicly_shared: bool
    asset_token: str = field(repr=False)
    contract: str | None

    def public(self) -> dict[str, Any]:
        return {
            "backend": "artifact",
            "experimental": True,
            "id": self.id,
            "url": artifact_url(self.id),
            "version": self.version,
            "title": self.title,
            "role": self.role,
            "read_mode": self.read_mode,
            "type_id": self.type_id,
            "contract": self.contract,
            "publicly_shared": self.publicly_shared,
            "files": {
                path: {"sha256": f.sha256, "bytes": f.size, "content_type": f.content_type}
                for path, f in self.files.items()
            },
        }


class ArtifactClient:
    def __init__(
        self,
        *,
        credential_reader: Callable[[], dict[str, Any]] = load_artifact_credential,
        opener: Callable[..., Any] = OPENER.open,
    ) -> None:
        self._credentials = credential_reader
        self._opener = opener
        self._session = str(uuid.uuid4())

    def credentials(self) -> dict[str, Any]:
        try:
            return self._credentials()
        except DesignAuthError as error:
            raise ClaudeDesignAuthError(str(error)) from error

    def identity(self) -> str:
        identity = self.credentials().get("identity")
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{32}", identity) is None:
            raise ClaudeDesignAuthError("Artifact login lacks an identity; reconnect with login --backend artifact.")
        return hashlib.sha256(identity.encode()).hexdigest()

    def require_write_window(self) -> None:
        expiry = self.credentials().get("expiresAt", 0)
        if not isinstance(expiry, int) or expiry / 1000 - time.time() < CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS:
            raise ClaudeDesignAuthError("Artifact login is too close to expiry for a write; reconnect first.")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith(ARTIFACT_API_PREFIX) or "\\" in path or any(ord(c) < 32 for c in path):
            raise ValueError("Invalid artifact control route.")
        headers = {
            "Authorization": "Bearer " + self.credentials()["accessToken"],
            "anthropic-beta": ARTIFACT_OAUTH_BETA,
            "Accept": "application/json, application/vnd.ant.frame-refusal+json",
            "User-Agent": f"open-claude-design/{VERSION}",
            "X-Frame-CP": "go",
            "X-Frame-Surface": "code",
            "X-Frame-Platform": "cli",
            "X-Frame-Client-Version": ARTIFACT_PROTOCOL_CLIENT_VERSION,
            "X-Frame-Session-Id": self._session,
        }
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if data is not None:
            if len(data) > ARTIFACT_MAX_WRITE_BYTES:
                raise ClaudeDesignSafetyError("Artifact write exceeds the 15 MiB encoded request limit.")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(ARTIFACT_API_ORIGIN + path, data=data, headers=headers, method=method)
        mutation = method != "GET"
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read(ARTIFACT_MAX_RESPONSE_BYTES + 1)
                content_type = response.headers.get("Content-Type", "")
            if len(raw) > ARTIFACT_MAX_RESPONSE_BYTES:
                if mutation:
                    raise ArtifactOutcomeUnknown(
                        "Artifact write returned oversized evidence; reconcile before retrying."
                    )
                raise ClaudeDesignProtocolError("Artifact control response exceeds the safety limit.")
            return json.loads(raw) if "json" in content_type else raw.decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code == 409 and mutation:
                try:
                    conflict = json.loads(error.read(16384))
                except (ValueError, UnicodeError):
                    conflict = None
                if isinstance(conflict, dict) and conflict.get("reason") == "precondition_failed":
                    raise ArtifactConflict(
                        "Artifact files changed since review; the conditional write was refused."
                    ) from error
                raise ArtifactOutcomeUnknown(
                    "Artifact write is unsettled without definite evidence; reconcile."
                ) from error
            if error.code in {401, 403}:
                raise ClaudeDesignAuthError(
                    f"Artifact access refused (HTTP {error.code}); check artifact login and resource permissions."
                ) from error
            if mutation and (error.code >= 500 or 300 <= error.code < 400):
                raise ArtifactOutcomeUnknown(
                    "Artifact write returned a server failure; reconcile before retrying."
                ) from error
            raise ClaudeDesignProtocolError(
                f"Artifact service returned HTTP {error.code}; no response body was exposed."
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if mutation:
                raise ArtifactOutcomeUnknown(
                    "Artifact write lost its response; reconcile from current state before retrying."
                ) from error
            raise ClaudeDesignProtocolError("Could not reach the artifact service.") from error
        except (ValueError, UnicodeError) as error:
            if mutation:
                raise ArtifactOutcomeUnknown(
                    "Artifact write returned unreadable evidence; reconcile before retrying."
                ) from error
            raise ClaudeDesignProtocolError("Artifact service returned unreadable data.") from error

    def status(self) -> dict[str, Any]:
        contract = self.request("GET", ARTIFACT_API_PREFIX + "contract/latest")
        if not isinstance(contract, dict) or not isinstance(contract.get("capabilities"), list):
            raise ClaudeDesignProtocolError("Artifact contract is not a supported capability roster.")
        _revision(contract.get("version"))
        return {
            "authenticated": True,
            "backend": "artifact",
            "implemented": True,
            "experimental": True,
            "contract_version": contract["version"],
            "server_capabilities": contract["capabilities"],
            "supported_workflows": ["list", "types", "create", "inspect", "files", "pull", "push", "preview", "sync"],
            "unimplemented_workflows": ["binary_upload", "sharing", "comments", "design_system_admin", "delete"],
            "protocol_client_version": ARTIFACT_PROTOCOL_CLIENT_VERSION,
        }

    def list(self, *, types: bool = False) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = ""
        seen: set[str] = set()
        for _page in range(ARTIFACT_MAX_LIST_PAGES):
            params = {"scopes": "anthropic"} if types else {"limit": "100", "rel": "mine"}
            if cursor:
                params["page_token"] = cursor
            result = self.request("GET", ARTIFACT_API_PREFIX + ("types?" if types else "frames?") + urlencode(params))
            if not isinstance(result, dict):
                raise ClaudeDesignProtocolError("Artifact inventory is not an object.")
            rows = result.get("types" if types else "frames")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ClaudeDesignProtocolError("Artifact inventory is incomplete.")
            items.extend(rows)
            if len(items) > ARTIFACT_MAX_FILES:
                raise ClaudeDesignProtocolError("Artifact inventory exceeds the safety limit.")
            next_page = result.get("next_page_token")
            if not next_page:
                return items
            if not isinstance(next_page, str) or len(next_page) > 4096 or next_page in seen:
                raise ClaudeDesignProtocolError("Artifact inventory repeated or malformed its cursor.")
            seen.add(next_page)
            cursor = next_page
        raise ClaudeDesignProtocolError("Artifact inventory exceeds the page limit.")

    def describe_type(self, value: str) -> dict[str, Any]:
        result = self.request("GET", ARTIFACT_API_PREFIX + "types/" + artifact_id(value))
        if not isinstance(result, dict) or result.get("slug") != artifact_id(value):
            raise ClaudeDesignProtocolError("Artifact type description does not match the requested id.")
        return result

    def design_type(self) -> str:
        choices = [row for row in self.list(types=True) if row.get("title") == "Design"]
        if len(choices) != 1 or not isinstance(choices[0].get("slug"), str):
            raise ClaudeDesignProtocolError("The native Design type is missing or ambiguous; inspect artifacts types.")
        return artifact_id(choices[0]["slug"])

    def create(self, title: str, idempotency_key: str) -> dict[str, Any]:
        if not title.strip() or len(title) > 2048 or any(ord(c) < 32 for c in title):
            raise ValueError("Artifact title must contain 1–2048 printable characters.")
        try:
            uuid.UUID(idempotency_key)
        except ValueError as error:
            raise ValueError(
                "Creation requires a UUID --idempotency-key; retain it when reconciling an unknown outcome."
            ) from error
        self.require_write_window()
        type_id = self.design_type()
        result = self.request(
            "POST",
            ARTIFACT_API_PREFIX + f"types/{type_id}/create?" + urlencode({"idempotency_key": idempotency_key}),
            {"title": title, "target_type_version": None},
        )
        if not isinstance(result, dict) or not isinstance(result.get("slug"), str):
            raise ArtifactOutcomeUnknown(
                "Artifact creation returned no verified id; inspect inventory before retrying."
            )
        try:
            value = artifact_id(result["slug"])
        except ValueError as error:
            raise ArtifactOutcomeUnknown(
                "Creation returned an invalid id; reconcile inventory with the retained key."
            ) from error
        try:
            snapshot = self.snapshot(value)
            if snapshot.type_id != type_id or snapshot.read_mode != "owner" or snapshot.publicly_shared:
                raise ClaudeDesignSafetyError("New artifact type or private visibility could not be verified.")
        except Exception as error:
            raise ArtifactOutcomeUnknown(
                f"Artifact {value} was created but verification failed; reconcile that id."
            ) from error
        return {
            **snapshot.public(),
            "created": True,
            "verified": True,
            "content_ready": "project/canvas.json" in snapshot.files,
            "replayed": result.get("replayed") is True,
        }

    def _content(self, value: str, version: str, path: str, asset_token: str, maximum: int) -> bytes:
        value, version, path = artifact_id(value), _revision(version), file_path(path)
        url = f"https://{value}.frame.claudeusercontent.com/_f/{version}/{quote(path, safe='/')}?" + urlencode(
            {"__frame_t": asset_token}
        )
        request = urllib.request.Request(url, headers={"User-Agent": f"open-claude-design/{VERSION}"})
        try:
            with self._opener(request, timeout=30) as response:
                data = response.read(maximum + 1)
            if len(data) > maximum:
                raise ClaudeDesignProtocolError("Artifact file exceeds the bounded transfer limit.")
            return data
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise ClaudeDesignProtocolError(
                "Artifact content fetch failed; capability URLs were not exposed."
            ) from error

    def snapshot(self, value: str) -> ArtifactSnapshot:
        value = artifact_id(value)
        metadata = self.request("GET", ARTIFACT_API_PREFIX + "read/" + value)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("public"), bool):
            raise ClaudeDesignProtocolError("Artifact returned incomplete visibility metadata.")
        contract = _revision(metadata.get("contract"))
        boot = self.request("GET", ARTIFACT_API_PREFIX + value + "?via=model_read&bk=probe")
        if not isinstance(boot, dict):
            raise ClaudeDesignProtocolError("Artifact returned an invalid snapshot.")
        version = _revision(boot.get("ver"))
        token = boot.get("assetToken")
        perm = boot.get("perm")
        if not isinstance(token, str) or not token or len(token) > 16384 or not isinstance(perm, dict):
            raise ClaudeDesignProtocolError("Artifact has no member-scoped content capability or permissions.")
        title, role, read_mode = boot.get("title"), perm.get("role"), perm.get("mode")
        if not isinstance(title, str) or role not in {"owner", "writer", "reader"} or not isinstance(read_mode, str):
            raise ClaudeDesignProtocolError("Artifact returned incomplete identity or permission metadata.")
        raw = self._content(value, version, "_files.json", token, ARTIFACT_MAX_RESPONSE_BYTES)
        try:
            manifest = json.loads(raw)
        except ValueError as error:
            raise ClaudeDesignProtocolError("Artifact file inventory is not valid JSON.") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("ver") != version
            or not isinstance(manifest.get("files"), dict)
            or manifest.get("narrowed") is True
            or manifest.get("truncated") is True
        ):
            raise ClaudeDesignProtocolError("Artifact file inventory does not match its version.")
        rows = manifest["files"]
        if len(rows) > ARTIFACT_MAX_FILES:
            raise ClaudeDesignProtocolError("Artifact file inventory exceeds the file limit.")
        files: dict[str, ArtifactFile] = {}
        for path, row in rows.items():
            file_path(path)
            if not isinstance(row, dict):
                raise ClaudeDesignProtocolError("Artifact returned an invalid file entry.")
            digest, size, mime = row.get("sha256"), row.get("size"), row.get("contentType")
            if (
                not isinstance(digest, str)
                or not SHA256.fullmatch(digest)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(mime, str)
            ):
                raise ClaudeDesignProtocolError("Artifact file has incomplete integrity metadata.")
            files[path] = ArtifactFile(digest, size, mime)
        type_row = boot.get("type")
        type_id = type_row.get("slug") if isinstance(type_row, dict) else None
        if type_id is not None:
            type_id = artifact_id(type_id)
        return ArtifactSnapshot(
            value,
            version,
            title,
            role,
            read_mode,
            type_id,
            files,
            metadata["public"],
            token,
            contract,
        )

    def read_file(self, snapshot: ArtifactSnapshot, path: str) -> bytes:
        path = file_path(path)
        row = snapshot.files.get(path)
        if row is None:
            raise ClaudeDesignProtocolError("Artifact file does not exist in the reviewed inventory.")
        if row.size > ARTIFACT_MAX_FILE_BYTES:
            raise ClaudeDesignProtocolError("Artifact file exceeds the 16 MiB transfer limit.")
        data = self._content(snapshot.id, snapshot.version, path, snapshot.asset_token, ARTIFACT_MAX_FILE_BYTES)
        if len(data) != row.size or hashlib.sha256(data).hexdigest() != row.sha256:
            raise ClaudeDesignProtocolError("Artifact file bytes do not match their published size and hash.")
        return data

    def push(self, snapshot: ArtifactSnapshot, files: dict[str, bytes], matches: dict[str, str]) -> dict[str, Any]:
        if snapshot.publicly_shared:
            raise ClaudeDesignSafetyError("Experimental artifact writes support private artifacts only.")
        if snapshot.role not in {"owner", "writer"} or snapshot.type_id is None:
            raise ClaudeDesignSafetyError("Artifact requires edit access and a native Design type before writing.")
        description = self.describe_type(snapshot.type_id)
        if description.get("title") != "Design":
            raise ClaudeDesignSafetyError("This write workflow supports native Design artifacts only.")
        if not files or len(files) > ARTIFACT_MAX_WRITE_FILES or set(files) != set(matches):
            raise ValueError("Declare 1–256 exact files and one reviewed SHA-256 (or 0 for absence) for every path.")
        self.require_write_window()
        manifest = {}
        self.validate_design(snapshot, files)
        for path, data in files.items():
            file_path(path, write=True)
            row = snapshot.files.get(path)
            expected = row.sha256 if row else "0"
            if matches[path] != expected:
                raise ArtifactConflict("Artifact file changed since review; no mutation was submitted.")
            try:
                content = data.decode("utf-8")
            except UnicodeError as error:
                raise ClaudeDesignSafetyError(
                    "Artifact push currently supports UTF-8 text; binary asset uploads are unimplemented."
                ) from error
            if len(data) > ARTIFACT_MAX_FILE_BYTES or "\ufffd" in content:
                raise ClaudeDesignSafetyError("Artifact file is too large or contains a replacement character.")
            suffix = path.rsplit(".", 1)[-1].lower()
            mime = {
                "html": "text/html",
                "json": "application/json",
                "css": "text/css",
                "js": "text/javascript",
                "md": "text/markdown",
                "txt": "text/plain",
            }.get(suffix)
            if mime is None:
                raise ClaudeDesignSafetyError("Artifact push supports HTML, JSON, CSS, JS, Markdown, and text files.")
            manifest[path] = {"content": content, "contentType": mime, "ifMatch": None if expected == "0" else expected}
        body = {
            "slug": snapshot.id,
            "title": snapshot.title,
            "mode": "patch",
            "baseVersion": snapshot.version,
            "manifest": manifest,
        }
        result = self.request(
            "POST", ARTIFACT_API_PREFIX + "deploy/direct?" + urlencode({"attempt_id": str(uuid.uuid4())}), body
        )
        if (
            not isinstance(result, dict)
            or result.get("slug") != snapshot.id
            or not isinstance(result.get("version"), str)
        ):
            raise ArtifactOutcomeUnknown(
                "Artifact write returned incomplete publication evidence; reconcile before retrying."
            )
        try:
            after = self.snapshot(snapshot.id)
            if after.version != result["version"]:
                raise ClaudeDesignProtocolError("Artifact changed after publication; reconcile its current version.")
            for path, data in files.items():
                if self.read_file(after, path) != data:
                    raise ClaudeDesignProtocolError("Artifact readback differs from the approved bytes.")
            for path, row in snapshot.files.items():
                if path not in files and after.files.get(path) != row:
                    raise ClaudeDesignProtocolError("An undeclared artifact file changed during publication.")
        except Exception as error:
            raise ArtifactOutcomeUnknown(
                f"Artifact {snapshot.id} was updated but readback is unverified; reconcile it."
            ) from error
        return {
            "backend": "artifact",
            "experimental": True,
            "id": snapshot.id,
            "url": artifact_url(snapshot.id),
            "version": after.version,
            "written": sorted(files),
            "verified": True,
            "mutated": True,
            "render_executed": False,
        }

    def validate_design(self, snapshot: ArtifactSnapshot, changes: dict[str, bytes]) -> dict[str, Any]:
        index_path = "project/canvas.json"
        index_bytes = changes.get(index_path)
        if index_bytes is None:
            if index_path not in snapshot.files:
                raise ClaudeDesignSafetyError(
                    "Write project/canvas.json with the first artboard so it appears on the canvas."
                )
            index_bytes = self.read_file(snapshot, index_path)
        try:
            index = json.loads(index_bytes)
        except (ValueError, UnicodeError) as error:
            raise ClaudeDesignSafetyError("Artifact canvas index is not valid JSON.") from error
        if (
            not isinstance(index, dict)
            or index.get("v") != 3
            or not isinstance(index.get("boards"), dict)
            or not isinstance(index.get("order"), list)
        ):
            raise ClaudeDesignSafetyError("Artifact requires a v3 canvas index with boards and order.")
        boards, order = index["boards"], index["order"]
        if (
            any(not isinstance(path, str) for path in order)
            or len(order) != len(set(order))
            or set(order) != set(boards)
        ):
            raise ClaudeDesignSafetyError("Canvas order must name each artboard exactly once.")
        available = set(snapshot.files) | set(changes)
        for relative, board in boards.items():
            path = file_path("project/" + relative, write=True)
            if not path.endswith(".dc.html") or path not in available or not isinstance(board, dict):
                raise ClaudeDesignSafetyError("Canvas index names a missing or invalid artboard.")
            for dimension in ("w", "h"):
                value = board.get(dimension)
                if not isinstance(value, int | float) or isinstance(value, bool) or not 40 <= value <= 8000:
                    raise ClaudeDesignSafetyError("Artboard dimensions must be between 40 and 8000 pixels.")
            for coordinate in ("x", "y"):
                value = board.get(coordinate)
                if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
                    raise ClaudeDesignSafetyError("Artboard coordinates must be finite numbers.")
        sources = (
            changes
            if changes
            else {"project/" + relative: self.read_file(snapshot, "project/" + relative) for relative in order}
        )
        for path, data in sources.items():
            if path.endswith(".dc.html"):
                if path.removeprefix("project/") not in boards:
                    raise ClaudeDesignSafetyError("Declare every written artboard in project/canvas.json.")
                runtime_path = path.rsplit("/", 1)[0] + "/support.js"
                check = validate_html(path, data, available | {runtime_path})
                if check["valid"] is not True:
                    raise ClaudeDesignSafetyError("Artifact artboard violates the editable Design Component structure.")
        return {"index_verified": True, "artboards": list(order), "render_executed": False}
