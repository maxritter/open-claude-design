"""Experimental frame protocol, with separate control- and content-plane credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from open_claude_design.artifact_auth import load_artifact_credential
from open_claude_design.auth import DesignAuthError
from open_claude_design.config import (
    ARTIFACT_API_ORIGIN,
    ARTIFACT_API_PREFIX,
    ARTIFACT_ASSET_CONTENT_TYPES,
    ARTIFACT_CONTENT_HOST_SUFFIX,
    ARTIFACT_FILE_KINDS,
    ARTIFACT_MAX_DIAGNOSTIC_BYTES,
    ARTIFACT_MAX_FILE_BYTES,
    ARTIFACT_MAX_FILES,
    ARTIFACT_MAX_LIST_PAGES,
    ARTIFACT_MAX_PROFILE_IDS,
    ARTIFACT_MAX_RESPONSE_BYTES,
    ARTIFACT_MAX_WRITE_BYTES,
    ARTIFACT_MAX_WRITE_FILES,
    ARTIFACT_OAUTH_BETA,
    ARTIFACT_PROTOCOL_CLIENT_VERSION,
    ARTIFACT_SHARE_ACCESS,
    ARTIFACT_SHARE_MODES,
    ARTIFACT_STORE_KINDS,
    ARTIFACT_TEXT_CONTENT_TYPES,
    ARTIFACT_TYPE_KINDS,
    ARTIFACT_TYPE_OWNED_PATHS,
    CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS,
    VERSION,
)
from open_claude_design.errors import ClaudeDesignAuthError, ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.migration import resolve_target
from open_claude_design.validation import validate_html

ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
SHORT_ID = re.compile(r"[1-9A-HJ-NP-Za-km-z]{22}")
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
REVISION = re.compile(r"[A-Za-z0-9_.-]{1,64}")
CONTRACT = re.compile(r"\d{1,4}\.\d{1,5}\.\d{1,6}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")
USER_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PROFILE_ID = re.compile(r"u_[A-Za-z0-9_-]{22}")
DS_FOLDER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
CAPABILITY = re.compile(r"[a-z][a-z0-9_-]{0,63}")
# Kinds whose guides keep fonts or media as published files; Design and Slides keep them as uploaded assets.
BINARY_FILE_KINDS = frozenset({None, "design-system"})
RUNTIME_BLOCK = re.compile(rb"<!-- frame-runtime -->.*?<!-- /frame-runtime -->", re.DOTALL)


class ArtifactConflict(ClaudeDesignSafetyError):
    """The server refused this entire conditional write; no file was overwritten."""


class ArtifactOutcomeUnknown(ClaudeDesignProtocolError):
    """A submitted mutation lacks enough evidence to report its outcome."""


class ArtifactHTTPError(ClaudeDesignProtocolError):
    """A definite non-success answer, with the service's sanitized error code when it gave one."""

    def __init__(self, message: str, *, status: int, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(_NoRedirect())


def _short_to_uuid(value: str) -> str | None:
    if SHORT_ID.fullmatch(value) is None:
        return None
    number = 0
    for character in value:
        number = number * 58 + BASE58.index(character)
    return str(uuid.UUID(int=number)) if number < 1 << 128 else None


def artifact_id(value: str) -> str:
    """Accept an artifact slug, a share-link short id, or any supported artifact URL."""
    if not isinstance(value, str):
        raise ValueError("Artifact id must be a string.")
    if ID.fullmatch(value):
        return _short_to_uuid(value) or value
    resolved = resolve_target(value)
    if resolved["backend"] != "artifact" or ID.fullmatch(resolved["resource_id"]) is None:
        raise ValueError("Use an artifact id or Claude artifact URL; standalone project URLs use project commands.")
    return _short_to_uuid(resolved["resource_id"]) or resolved["resource_id"]


def artifact_url(value: str) -> str:
    return f"https://claude.ai/code/artifact/{artifact_id(value)}"


def file_path(value: str, *, write: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Artifact file path must be a string.")
    if len(value) > 512 or PATH.fullmatch(value) is None or any(len(part) > 200 for part in value.split("/")):
        raise ValueError("Artifact file paths must be canonical relative paths without spaces or traversal.")
    if write and not value.startswith("project/"):
        raise ClaudeDesignSafetyError(
            "Typed artifact writes are restricted to project/; the artifact type owns its runtime files."
        )
    return value


def _revision(value: object) -> str:
    if not isinstance(value, str) or REVISION.fullmatch(value) is None:
        raise ClaudeDesignProtocolError("Artifact service returned an invalid version.")
    return value


def _clean(value: object, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    text = "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Co"} else c for c in value).strip()
    return text[:limit] or None


def _error_detail(raw: bytes) -> tuple[str | None, str | None]:
    """Return a bounded, control-stripped error code and message from a refusal body."""
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        return None, _clean(raw.decode("utf-8", "replace"))
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return _clean(error.get("code"), 64), _clean(error.get("message"))
        return _clean(body.get("reason") or body.get("code"), 64), _clean(error or body.get("message"))
    return None, None


def content_type_for(path: str) -> str | None:
    return ARTIFACT_TEXT_CONTENT_TYPES.get(path.rsplit(".", 1)[-1].lower()) if "." in path else None


def now_rfc3339() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    capabilities: dict[str, Any] = field(default_factory=dict)
    type_versions: dict[str, Any] = field(default_factory=dict)
    live_version: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "backend": "artifact",
            "experimental": True,
            "id": self.id,
            "url": artifact_url(self.id),
            "version": self.version,
            **({"live_version": self.live_version} if self.live_version not in {None, self.version} else {}),
            "title": self.title,
            "role": self.role,
            "read_mode": self.read_mode,
            "type_id": self.type_id,
            **({"type_versions": self.type_versions} if self.type_versions else {}),
            "contract": self.contract,
            "capabilities": sorted(self.capabilities),
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
        self._types: dict[str, dict[str, Any]] = {}

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

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        mutation: bool | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        allow_status: frozenset[int] = frozenset(),
    ) -> Any:
        """Call one frame control route; ``mutation`` defaults to any non-GET method."""
        if not path.startswith(ARTIFACT_API_PREFIX) or "\\" in path or any(ord(c) < 32 for c in path):
            raise ValueError("Invalid artifact control route.")
        sent = {
            "Authorization": "Bearer " + self.credentials()["accessToken"],
            "anthropic-beta": ARTIFACT_OAUTH_BETA,
            "Accept": "application/json, application/vnd.ant.frame-refusal+json",
            "User-Agent": f"open-claude-design/{VERSION}",
            "X-Frame-CP": "go",
            "X-Frame-Surface": "code",
            "X-Frame-Platform": "cli",
            "X-Frame-Client-Version": ARTIFACT_PROTOCOL_CLIENT_VERSION,
            "X-Frame-Session-Id": self._session,
            **(headers or {}),
        }
        data = body
        if data is None and payload is not None:
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if data is not None:
            if len(data) > ARTIFACT_MAX_WRITE_BYTES:
                raise ClaudeDesignSafetyError("Artifact request exceeds the 15 MiB encoded request limit.")
            sent["Content-Type"] = content_type
        request = urllib.request.Request(ARTIFACT_API_ORIGIN + path, data=data, headers=sent, method=method)
        mutation = method != "GET" if mutation is None else mutation
        try:
            with self._opener(request, timeout=timeout) as response:
                raw = response.read(ARTIFACT_MAX_RESPONSE_BYTES + 1)
                received = response.headers.get("Content-Type", "")
            if len(raw) > ARTIFACT_MAX_RESPONSE_BYTES:
                if mutation:
                    raise ArtifactOutcomeUnknown(
                        "Artifact write returned oversized evidence; reconcile before retrying."
                    )
                raise ClaudeDesignProtocolError("Artifact control response exceeds the safety limit.")
            if not raw:
                return {}
            return json.loads(raw) if "json" in received else raw.decode("utf-8")
        except urllib.error.HTTPError as error:
            try:
                raw_error = error.read(16384) or b""
            except OSError:
                raw_error = b""
            code, message = _error_detail(raw_error)
            if error.code in allow_status:
                return {"__status__": error.code, "code": code, "message": message}
            if error.code == 409 and mutation:
                if code == "precondition_failed":
                    raise ArtifactConflict(
                        "Artifact changed since review; the conditional write was refused."
                    ) from error
                raise ArtifactOutcomeUnknown(
                    "Artifact write is unsettled without definite evidence; reconcile."
                ) from error
            if error.code == 412 and mutation:
                raise ArtifactConflict("Artifact changed since it was read; nothing was applied.") from error
            if code in {"capability_disabled", "not_declared"}:
                raise ClaudeDesignSafetyError(
                    "This artifact does not declare the capability this needs (assets for uploads, db for documents, "
                    "user as well for data/users/me, comments for threads). A plain page adds it with "
                    "`push --capabilities` (keeping the ones it has); typed artifacts inherit theirs from the type."
                ) from error
            if error.code in {401, 403}:
                detail = f" ({code})" if code else ""
                raise ClaudeDesignAuthError(
                    f"Artifact access refused (HTTP {error.code}){detail}; "
                    "check artifact login and resource permissions."
                ) from error
            if mutation and (error.code >= 500 or 300 <= error.code < 400):
                raise ArtifactOutcomeUnknown(
                    "Artifact write returned a server failure; reconcile before retrying."
                ) from error
            detail = f": {code}" if code else ""
            raise ArtifactHTTPError(
                f"Artifact service returned HTTP {error.code}{detail}.", status=error.code, code=code
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

    # Contract, inventory, and types

    def contract(self, version: str = "latest") -> dict[str, Any]:
        route = "latest" if version == "latest" else version
        if route != "latest" and CONTRACT.fullmatch(route) is None:
            raise ValueError("Use --contract latest or an exact contract version such as 0.2.87.")
        contract = self.request("GET", ARTIFACT_API_PREFIX + "contract/" + route)
        if not isinstance(contract, dict) or not isinstance(contract.get("capabilities"), list):
            raise ClaudeDesignProtocolError("Artifact contract is not a supported capability roster.")
        _revision(contract.get("version"))
        return contract

    def status(self) -> dict[str, Any]:
        contract = self.contract()
        return {
            "authenticated": True,
            "backend": "artifact",
            "implemented": True,
            "experimental": True,
            "contract_version": contract["version"],
            "server_capabilities": contract["capabilities"],
            "supported_workflows": [
                "list",
                "types",
                "create",
                "inspect",
                "files",
                "pull",
                "push",
                "publish",
                "preview",
                "render",
                "sync",
                "versions",
                "retitle",
                "pin",
                "delete",
                "share",
                "diagnostics",
                "assets",
                "comments",
                "db",
                "profiles",
                "design-system",
            ],
            "unimplemented_workflows": ["room", "page_endpoints", "watch"],
            "protocol_client_version": ARTIFACT_PROTOCOL_CLIENT_VERSION,
        }

    def _pages(self, route: str, key: str, params: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = ""
        seen: set[str] = set()
        result: dict[str, Any] = {}
        for _page in range(ARTIFACT_MAX_LIST_PAGES):
            query = dict(params)
            if cursor:
                query["page_token"] = cursor
            result = self.request("GET", ARTIFACT_API_PREFIX + route + "?" + urlencode(query))
            if not isinstance(result, dict):
                raise ClaudeDesignProtocolError("Artifact inventory is not an object.")
            rows = result.get(key)
            if rows is None and key == "instances":
                rows = []
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ClaudeDesignProtocolError("Artifact inventory is incomplete.")
            items.extend(rows)
            if len(items) > ARTIFACT_MAX_FILES:
                raise ClaudeDesignProtocolError("Artifact inventory exceeds the safety limit.")
            next_page = result.get("next_page_token")
            if not next_page:
                return items, result
            if not isinstance(next_page, str) or len(next_page) > 4096 or next_page in seen:
                raise ClaudeDesignProtocolError("Artifact inventory repeated or malformed its cursor.")
            seen.add(next_page)
            cursor = next_page
        raise ClaudeDesignProtocolError("Artifact inventory exceeds the page limit.")

    def list(self, *, types: bool = False, scope: str = "mine") -> list[dict[str, Any]]:
        if types:
            return self._pages("types", "types", {"scopes": "anthropic"})[0]
        if scope not in {"mine", "shared", "all"}:
            raise ValueError("Artifact list scope must be mine, shared, or all.")
        params = {"limit": "100", **({"rel": "mine"} if scope == "mine" else {})}
        rows = self._pages("frames", "frames", params)[0]
        return rows if scope != "shared" else [row for row in rows if row.get("rel") == "shared"]

    def describe_type(self, value: str) -> dict[str, Any]:
        value = artifact_id(value)
        if value not in self._types:
            result = self.request("GET", ARTIFACT_API_PREFIX + "types/" + value)
            if not isinstance(result, dict) or result.get("slug") != value:
                raise ClaudeDesignProtocolError("Artifact type description does not match the requested id.")
            self._types[value] = result
        return self._types[value]

    def type_kind(self, type_id: str | None) -> str | None:
        """Map a type to the content model it uses; untyped artifacts are plain pages (None)."""
        if type_id is None:
            return None
        title = self.describe_type(type_id).get("title")
        return ARTIFACT_TYPE_KINDS.get(title, "other") if isinstance(title, str) else "other"

    def resolve_type(self, value: str) -> str:
        """Resolve a type title (Design, Slides, Design System, ...), kind, or id to its type id."""
        wanted = value.strip().lower()
        rows = self.list(types=True)
        for row in rows:
            title = row.get("title")
            slug = row.get("slug")
            if not isinstance(slug, str) or not isinstance(title, str):
                continue
            if wanted in {title.lower(), ARTIFACT_TYPE_KINDS.get(title, "").lower(), slug.lower()}:
                return artifact_id(slug)
        resolved = artifact_id(value) if ID.fullmatch(value) or value.startswith("https://") else ""
        if USER_UUID.fullmatch(resolved):
            return resolved
        raise ClaudeDesignProtocolError(
            f"No artifact type named {value!r} is available to this account; run `artifacts types`. "
            "On Enterprise plans an Owner enables Design, Slides, and Design systems under Templates."
        )

    def design_type(self) -> str:
        return self.resolve_type("Design")

    def type_instances(self, value: str, *, scope: str = "all") -> dict[str, Any]:
        type_id = artifact_id(value)
        if scope not in {"mine", "shared", "all"}:
            raise ValueError("Instance scope must be mine, shared, or all.")
        params = {"limit": "50", **({} if scope == "all" else {"rel": scope})}
        rows, last = self._pages(f"types/{type_id}/instances", "instances", params)
        default = last.get("default")
        default_slug = default.get("slug") if isinstance(default, dict) else default
        items = []
        for row in rows:
            slug = row.get("slug")
            if not isinstance(slug, str) or ID.fullmatch(slug) is None:
                continue
            items.append(
                {
                    "id": slug,
                    "title": _clean(row.get("title"), 2048) or "Untitled",
                    "url": artifact_url(slug),
                    "share_url": row.get("url") if isinstance(row.get("url"), str) else None,
                    "rel": row.get("rel"),
                    "audience": row.get("audience"),
                    "empty": row.get("empty") is True,
                    "default": isinstance(default_slug, str) and slug == default_slug,
                    "published_at": row.get("published_at"),
                }
            )
        return {"type_id": type_id, "items": items, "default": default_slug if isinstance(default_slug, str) else None}

    def type_file(self, type_id: str, path: str) -> str:
        path = file_path(path)
        response = self.request("GET", f"{ARTIFACT_API_PREFIX}types/{artifact_id(type_id)}/files/{path}")
        if not isinstance(response, dict) or not isinstance(response.get("text"), str) or response.get("truncated"):
            raise ClaudeDesignProtocolError("Artifact type returned incomplete authoring guidance.")
        return response["text"]

    def create(self, title: str, idempotency_key: str, *, type_value: str = "Design") -> dict[str, Any]:
        if not title.strip() or len(title) > 2048 or any(ord(c) < 32 for c in title):
            raise ValueError("Artifact title must contain 1–2048 printable characters.")
        try:
            uuid.UUID(idempotency_key)
        except ValueError as error:
            raise ValueError(
                "Creation requires a UUID --idempotency-key; retain it when reconciling an unknown outcome."
            ) from error
        self.require_write_window()
        type_id = self.resolve_type(type_value)
        description = self.describe_type(type_id)
        if description.get("creatable") is False:
            raise ClaudeDesignSafetyError(
                "This account cannot create artifacts from that type; an Enterprise Owner may need to enable it."
            )
        result = self.request(
            "POST",
            ARTIFACT_API_PREFIX + f"types/{type_id}/create?" + urlencode({"idempotency_key": idempotency_key}),
            {"title": title, "target_type_version": None},
            timeout=60,
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
        kind = self.type_kind(type_id)
        index = ARTIFACT_FILE_KINDS.get(kind or "", ("", 0))[0]
        public = snapshot.public()
        return {
            **public,
            "files": {path: row for path, row in public["files"].items() if path.startswith("project/")},
            "kind": kind,
            "created": True,
            "verified": True,
            "content_ready": bool(index) and index in snapshot.files,
            "replayed": result.get("replayed") is True,
        }

    # Content plane

    def _content(self, value: str, version: str, path: str, asset_token: str, maximum: int) -> bytes:
        value, version, path = artifact_id(value), _revision(version), file_path(path)
        url = f"https://{value}{ARTIFACT_CONTENT_HOST_SUFFIX}/_f/{version}/{quote(path, safe='/')}?" + urlencode(
            {"__frame_t": asset_token}
        )
        return self._fetch_content(url, maximum)

    def _fetch_content(self, url: str, maximum: int) -> bytes:
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

    def read_metadata(self, value: str) -> dict[str, Any]:
        metadata = self.request("GET", ARTIFACT_API_PREFIX + "read/" + artifact_id(value))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("public"), bool):
            raise ClaudeDesignProtocolError("Artifact returned incomplete visibility metadata.")
        return metadata

    def snapshot(self, value: str, *, version: str | None = None) -> ArtifactSnapshot:
        value = artifact_id(value)
        metadata = self.read_metadata(value)
        contract = _revision(metadata.get("contract"))
        pinned = "" if version is None else "&" + urlencode({"ver": _revision(version)})
        boot = self.request("GET", ARTIFACT_API_PREFIX + value + "?via=model_read&bk=probe" + pinned)
        if not isinstance(boot, dict):
            raise ClaudeDesignProtocolError("Artifact returned an invalid snapshot.")
        live = _revision(boot.get("live") or boot.get("ver"))
        selected = _revision(boot.get("ver")) if version is None else _revision(version)
        token = boot.get("assetToken")
        perm = boot.get("perm")
        if not isinstance(token, str) or not token or len(token) > 16384 or not isinstance(perm, dict):
            raise ClaudeDesignProtocolError("Artifact has no member-scoped content capability or permissions.")
        title, role, read_mode = boot.get("title"), perm.get("role"), perm.get("mode")
        if not isinstance(title, str) or role not in {"owner", "writer", "reader"} or not isinstance(read_mode, str):
            raise ClaudeDesignProtocolError("Artifact returned incomplete identity or permission metadata.")
        raw = self._content(value, selected, "_files.json", token, ARTIFACT_MAX_RESPONSE_BYTES)
        try:
            manifest = json.loads(raw)
        except ValueError as error:
            raise ClaudeDesignProtocolError("Artifact file inventory is not valid JSON.") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("ver") != selected
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
        capabilities = metadata.get("capabilities")
        type_versions = metadata.get("type")
        return ArtifactSnapshot(
            value,
            selected,
            title,
            role,
            read_mode,
            type_id,
            files,
            metadata["public"],
            token,
            contract,
            capabilities if isinstance(capabilities, dict) else {},
            {
                key: type_versions.get(key)
                for key in ("current", "latest", "target")
                if isinstance(type_versions, dict) and type_versions.get(key) is not None
            },
            live,
        )

    def read_file(self, snapshot: ArtifactSnapshot, path: str) -> bytes:
        path = file_path(path)
        row = snapshot.files.get(path)
        if row is None:
            raise ClaudeDesignProtocolError("Artifact file does not exist in the reviewed inventory.")
        if row.size > ARTIFACT_MAX_FILE_BYTES:
            raise ClaudeDesignProtocolError("Artifact file exceeds the 16 MiB transfer limit.")
        data = self._content(snapshot.id, snapshot.version, path, snapshot.asset_token, ARTIFACT_MAX_FILE_BYTES)
        if (
            len(data) != row.size or hashlib.sha256(data).hexdigest() != row.sha256
        ) and row.content_type == "text/html":
            # The content host injects its runtime into served pages; the manifest hash covers the published source.
            data = RUNTIME_BLOCK.sub(b"", data, count=1)
        if len(data) != row.size or hashlib.sha256(data).hexdigest() != row.sha256:
            raise ClaudeDesignProtocolError("Artifact file bytes do not match their published size and hash.")
        return data

    def read_blob(self, snapshot: ArtifactSnapshot, asset: str, maximum: int) -> bytes:
        if re.fullmatch(r"[0-9a-f]{32}", asset) is None:
            raise ValueError("Asset ids are 32 lowercase hexadecimal characters.")
        return self._content(snapshot.id, snapshot.version, f"_blob/{asset}", snapshot.asset_token, maximum)

    # Writes

    def _capability_fields(
        self,
        snapshot: ArtifactSnapshot | None,
        capabilities: dict[str, Any] | None,
        contract: str | None,
        replace_capabilities: bool,
    ) -> dict[str, Any]:
        if capabilities is None and contract is None:
            return {}
        roster = self.contract("latest")
        fields: dict[str, Any] = {}
        if capabilities is not None:
            if not isinstance(capabilities, dict) or any(
                not isinstance(name, str) or CAPABILITY.fullmatch(name) is None for name in capabilities
            ):
                raise ValueError("Capabilities must be a JSON object keyed by capability name.")
            unknown = sorted(set(capabilities) - set(roster["capabilities"]))
            if unknown:
                raise ClaudeDesignSafetyError(
                    f"The current contract does not offer {', '.join(unknown)}; nothing was published."
                )
            stored = set(snapshot.capabilities) if snapshot else set()
            dropped = sorted(stored - set(capabilities) - {"flags"})
            if dropped and not replace_capabilities:
                raise ClaudeDesignSafetyError(
                    f"This declaration would revoke stored capabilities {', '.join(dropped)}; include them or pass "
                    "--replace-capabilities after the user approves removing them."
                )
            fields["capabilities"] = capabilities
            contract = contract or "latest"
        if contract is not None:
            fields["contract"] = roster["version"] if contract == "latest" else self.contract(contract)["version"]
        return fields

    def _manifest_entry(self, path: str, data: bytes, expected: str, *, binary: bool = False) -> dict[str, Any]:
        mime = content_type_for(path)
        if mime is None:
            suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            binary_mime = ARTIFACT_ASSET_CONTENT_TYPES.get(suffix)
            if not binary or binary_mime is None or len(data) > ARTIFACT_MAX_FILE_BYTES:
                raise ClaudeDesignSafetyError(
                    "This file type cannot be published as a file here; upload images, fonts, video, and PDFs "
                    "with `artifacts assets upload` and reference the returned /_blob/<id>."
                )
            # The deploy route carries non-text files base64-encoded under their media type.
            return {
                "content": base64.b64encode(data).decode("ascii"),
                "contentType": binary_mime,
                "ifMatch": None if expected == "0" else expected,
            }
        try:
            content = data.decode("utf-8")
        except UnicodeError as error:
            raise ClaudeDesignSafetyError("Artifact files must be UTF-8; upload binary files as assets.") from error
        if len(data) > ARTIFACT_MAX_FILE_BYTES or "�" in content:
            raise ClaudeDesignSafetyError("Artifact file is too large or contains a replacement character.")
        return {"content": content, "contentType": mime, "ifMatch": None if expected == "0" else expected}

    def push(
        self,
        snapshot: ArtifactSnapshot,
        files: dict[str, bytes],
        matches: dict[str, str],
        *,
        removals: dict[str, str] | None = None,
        allow_public: bool = False,
        capabilities: dict[str, Any] | None = None,
        contract: str | None = None,
        replace_capabilities: bool = False,
        title: str | None = None,
    ) -> dict[str, Any]:
        removals = removals or {}
        if snapshot.publicly_shared and not allow_public:
            raise ClaudeDesignSafetyError(
                "This artifact is public: a write publishes to everyone with the link. Pass --allow-public only "
                "when the user asked to update the public artifact."
            )
        if snapshot.role not in {"owner", "writer"}:
            raise ClaudeDesignSafetyError("Artifact requires edit access before writing.")
        if snapshot.version != snapshot.live_version and snapshot.live_version is not None:
            raise ArtifactConflict("A historical version cannot be the base of a write; read the live version.")
        kind = self.type_kind(snapshot.type_id)
        if kind in ARTIFACT_STORE_KINDS:
            raise ClaudeDesignSafetyError(ARTIFACT_STORE_KINDS[kind])
        if kind == "other":
            raise ClaudeDesignSafetyError("This artifact type has no documented file model; nothing was written.")
        if not files and not removals:
            raise ValueError("Declare at least one file to write or remove.")
        if (
            len(files) + len(removals) > ARTIFACT_MAX_WRITE_FILES
            or set(files) != set(matches)
            or set(files) & set(removals)
        ):
            raise ValueError("Declare 1–256 exact files and one reviewed SHA-256 (or 0 for absence) for every path.")
        if kind is not None and (capabilities is not None or contract is not None):
            raise ClaudeDesignSafetyError(
                "Typed artifacts inherit capabilities and contract from their type; do not declare them."
            )
        self.require_write_window()
        for path in [*files, *removals]:
            file_path(path, write=kind is not None)
            if kind is None and path.startswith(ARTIFACT_TYPE_OWNED_PATHS[1:]):
                raise ClaudeDesignSafetyError("SKILL.md and artifact-type/ belong to artifact types.")
        validation: dict[str, Any] = {}
        if kind in ARTIFACT_FILE_KINDS:
            validation = self.validate_kind(snapshot, kind, files, set(removals))
        elif "index.html" not in snapshot.files and "index.html" not in files:
            raise ClaudeDesignSafetyError("A plain artifact page needs index.html.")
        if "index.html" in removals and kind is None:
            raise ClaudeDesignSafetyError("A plain artifact page cannot remove its index.html.")
        manifest: dict[str, Any] = {}
        for path, data in files.items():
            row = snapshot.files.get(path)
            expected = row.sha256 if row else "0"
            if matches[path] != expected:
                raise ArtifactConflict("Artifact file changed since review; no mutation was submitted.")
            manifest[path] = self._manifest_entry(path, data, expected, binary=kind in BINARY_FILE_KINDS)
        for path, expected in removals.items():
            row = snapshot.files.get(path)
            if row is None or row.sha256 != expected:
                raise ArtifactConflict("A file to remove changed or is absent; no mutation was submitted.")
            manifest[path] = {"delete": True, "ifMatch": expected}
        body = {
            "slug": snapshot.id,
            "title": title if title is not None else snapshot.title,
            "mode": "patch",
            "baseVersion": snapshot.version,
            "manifest": manifest,
            **self._capability_fields(snapshot, capabilities, contract, replace_capabilities),
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
            after = self._published(snapshot.id, _revision(result["version"]))
            for path, data in files.items():
                if self.read_file(after, path) != data:
                    raise ClaudeDesignProtocolError("Artifact readback differs from the approved bytes.")
            for path in removals:
                if path in after.files:
                    raise ClaudeDesignProtocolError("A removed artifact file is still published.")
            for path, row in snapshot.files.items():
                if path not in files and path not in removals and after.files.get(path) != row:
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
            "kind": kind,
            "version": after.version,
            **({"live_version": after.live_version} if after.live_version != after.version else {}),
            "written": sorted(files),
            "removed": sorted(removals),
            **{key: validation[key] for key in ("pending", "pending_index") if validation.get(key)},
            "verified": True,
            "mutated": True,
            "render_executed": False,
        }

    def _published(self, value: str, version: str) -> ArtifactSnapshot:
        """Snapshot of exactly the version this write published.

        A typed artifact's first content makes the type publish once more (it adopts the index title), so
        live may already be newer; ``live_version`` reports it.
        """
        return self.snapshot(value, version=version)

    def publish_new(
        self,
        title: str,
        files: dict[str, bytes],
        *,
        capabilities: dict[str, Any] | None = None,
        contract: str | None = None,
        favicon: str | None = None,
    ) -> dict[str, Any]:
        """Create a new private plain-page artifact from index.html plus supporting files."""
        if not title.strip() or len(title) > 2048 or any(ord(c) < 32 for c in title):
            raise ValueError("Artifact title must contain 1–2048 printable characters.")
        if "index.html" not in files or len(files) > ARTIFACT_MAX_WRITE_FILES:
            raise ValueError("A new artifact page needs index.html and at most 256 files.")
        if favicon is not None and (not favicon or len(favicon) > 16):
            raise ValueError("Use a short emoji favicon.")
        self.require_write_window()
        manifest = {}
        for path, data in files.items():
            file_path(path)
            entry = self._manifest_entry(path, data, "0", binary=True)
            entry.pop("ifMatch")
            manifest[path] = entry
        body = {
            "title": title,
            **({"favicon": favicon} if favicon else {}),
            "mode": "replace",
            "manifest": manifest,
            **self._capability_fields(None, capabilities, contract, False),
        }
        result = self.request(
            "POST", ARTIFACT_API_PREFIX + "deploy/direct?" + urlencode({"attempt_id": str(uuid.uuid4())}), body
        )
        if not isinstance(result, dict) or not isinstance(result.get("slug"), str):
            raise ArtifactOutcomeUnknown("Artifact publish returned no verified id; list artifacts before retrying.")
        value = artifact_id(result["slug"])
        try:
            after = self.snapshot(value)
            for path, data in files.items():
                if self.read_file(after, path) != data:
                    raise ClaudeDesignProtocolError("Artifact readback differs from the approved bytes.")
            if after.read_mode != "owner" or after.publicly_shared:
                raise ClaudeDesignSafetyError("New artifact visibility could not be verified as private.")
        except Exception as error:
            raise ArtifactOutcomeUnknown(
                f"Artifact {value} was published but readback is unverified; reconcile it."
            ) from error
        return {
            **after.public(),
            "created": True,
            "written": sorted(files),
            "verified": True,
            "mutated": True,
        }

    # Content-model validation

    def _index(self, snapshot: ArtifactSnapshot, changes: dict[str, bytes], path: str) -> tuple[dict[str, Any], bool]:
        data = changes.get(path)
        created = path not in snapshot.files
        if data is None:
            if created:
                raise ClaudeDesignSafetyError(f"Write {path} with the first content so the type can show it.")
            data = self.read_file(snapshot, path)
        try:
            index = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ClaudeDesignSafetyError(f"{path} is not valid JSON.") from error
        if not isinstance(index, dict):
            raise ClaudeDesignSafetyError(f"{path} must be a JSON object.")
        return index, created

    @staticmethod
    def _created_marker(index: dict[str, Any], created: bool, path: str) -> None:
        marker = index.get("createdOnFiles")
        if created and (not isinstance(marker, dict) or marker.get("v") != 1 or not isinstance(marker.get("at"), str)):
            raise ClaudeDesignSafetyError(
                f'A new {path} needs "createdOnFiles": {{"v": 1, "at": "<now, RFC 3339>"}} so the type reads its files.'
            )

    @staticmethod
    def _design_systems(index: dict[str, Any], available: set[str]) -> None:
        records = index.get("designSystems", [])
        if not isinstance(records, list):
            raise ClaudeDesignSafetyError("designSystems must be a list of installed system records.")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("namespace"), str):
                raise ClaudeDesignSafetyError("Each designSystems record needs its install folder as namespace.")
            if DS_FOLDER.fullmatch(record["namespace"]) is None:
                raise ClaudeDesignSafetyError("A design-system folder must match [a-z0-9][a-z0-9_-]{0,63}.")
            if f"project/ds/{record['namespace']}/tokens.json" not in available:
                raise ClaudeDesignSafetyError("A designSystems record needs its project/ds/<folder>/tokens.json.")

    def validate_kind(
        self, snapshot: ArtifactSnapshot, kind: str, changes: dict[str, bytes], removed: set[str] | None = None
    ) -> dict[str, Any]:
        removed = removed or set()
        if kind == "design":
            return self.validate_design(snapshot, changes, removed)
        index_path, schema = ARTIFACT_FILE_KINDS[kind]
        if index_path in removed:
            raise ClaudeDesignSafetyError("The type index cannot be removed.")
        available = (set(snapshot.files) | set(changes)) - removed
        generated = {"project/tokens.css", "project/manifest.json"}
        if kind == "design-system":
            if any(path in generated or path.startswith("project/api/") for path in changes):
                raise ClaudeDesignSafetyError("tokens.css, manifest.json, and api/ cards are generated by the type.")
            if index_path not in available:
                # A new system's index goes last, so its files may arrive first.
                return {"index_verified": False, "pending_index": index_path, "render_executed": False}
        index, created = self._index(snapshot, changes, index_path)
        if index.get("v") != schema:
            raise ClaudeDesignSafetyError(f"{index_path} must declare schema version {schema}.")
        self._created_marker(index, created, index_path)
        self._design_systems(index, available)
        if kind == "slides":
            order = index.get("order")
            if (
                not isinstance(order, list)
                or not order
                or any(
                    not isinstance(slide, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", slide) is None for slide in order
                )
            ):
                raise ClaudeDesignSafetyError("Deck order must list 1 or more slide ids.")
            if len(order) != len(set(order)):
                raise ClaudeDesignSafetyError("Deck order must name each slide once.")
            pending = [slide for slide in order if f"project/slides/{slide}.html" not in available]
            if len(pending) == len(order):
                raise ClaudeDesignSafetyError("Send the cover slide's file with the first deck index.")
            for path, data in changes.items():
                match = re.fullmatch(r"project/slides/([A-Za-z0-9_-]{1,64})\.html", path)
                if match is None:
                    continue
                if match.group(1) not in order:
                    raise ClaudeDesignSafetyError("Declare every written slide in the deck order.")
                if re.search(rb'<section\b[^>]*\bid="' + re.escape(match.group(1)).encode() + b'"', data) is None:
                    raise ClaudeDesignSafetyError("Each slide file holds one <section> whose id is the slide id.")
            return {"index_verified": True, "slides": order, "pending": pending, "render_executed": False}
        if index.get("layout") != "files" or not isinstance(index.get("title"), str):
            raise ClaudeDesignSafetyError('A design-system index needs "layout": "files" and a title.')
        if not isinstance(index.get("createdOnFiles"), dict) and not isinstance(index.get("convertedFrom"), dict):
            raise ClaudeDesignSafetyError(
                "A design-system.json without a createdOnFiles or convertedFrom marker is not an index; "
                "the page opens it read-only, so nothing was written."
            )
        return {"index_verified": True, "render_executed": False}

    def validate_design(
        self, snapshot: ArtifactSnapshot, changes: dict[str, bytes], removed: set[str] | None = None
    ) -> dict[str, Any]:
        removed = removed or set()
        index_path = "project/canvas.json"
        if index_path in removed:
            raise ClaudeDesignSafetyError("The canvas index cannot be removed.")
        index, created = self._index(snapshot, changes, index_path)
        if index.get("v") != 3 or not isinstance(index.get("boards"), dict) or not isinstance(index.get("order"), list):
            raise ClaudeDesignSafetyError("Artifact requires a v3 canvas index with boards and order.")
        if created:
            self._created_marker(index, created, index_path)
        boards, order = index["boards"], index["order"]
        if (
            any(not isinstance(path, str) for path in order)
            or len(order) != len(set(order))
            or set(order) != set(boards)
        ):
            raise ClaudeDesignSafetyError("Canvas order must name each artboard exactly once.")
        available = (set(snapshot.files) | set(changes)) - removed
        self._design_systems(index, available)
        pending = []
        for relative, board in boards.items():
            path = file_path("project/" + relative, write=True)
            if not path.endswith(".dc.html") or not isinstance(board, dict):
                raise ClaudeDesignSafetyError("Canvas index names an invalid artboard.")
            if path not in available:
                # The guide sends the index first with every planned artboard, then the rest in later calls.
                pending.append(relative)
            for dimension in ("w", "h"):
                value = board.get(dimension)
                if not isinstance(value, int | float) or isinstance(value, bool) or not 40 <= value <= 8000:
                    raise ClaudeDesignSafetyError("Artboard dimensions must be between 40 and 8000 pixels.")
            for coordinate in ("x", "y"):
                value = board.get(coordinate)
                if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
                    raise ClaudeDesignSafetyError("Artboard coordinates must be finite numbers.")
        for collection, limit in (("pages", 40), ("notes", 200)):
            value = index.get(collection)
            if value is not None and (not isinstance(value, list | dict) or len(value) > limit):
                raise ClaudeDesignSafetyError(f"Canvas {collection} must hold at most {limit} entries.")
        for path in removed:
            if path.endswith(".dc.html") and path.removeprefix("project/") in boards:
                raise ClaudeDesignSafetyError("Remove an artboard's boards entry and order slot with its file.")
        if len(pending) == len(boards) and boards:
            raise ClaudeDesignSafetyError("Send the entry artboard's file with the first canvas index.")
        sources = (
            changes
            if changes
            else {
                "project/" + relative: self.read_file(snapshot, "project/" + relative)
                for relative in order
                if relative not in pending
            }
        )
        for path, data in sources.items():
            if path.endswith(".dc.html") and not path.startswith("project/ds/"):
                if path.removeprefix("project/") not in boards:
                    raise ClaudeDesignSafetyError("Declare every written artboard in project/canvas.json.")
                runtime_path = path.rsplit("/", 1)[0] + "/support.js"
                check = validate_html(path, data, available | {runtime_path})
                if check["valid"] is not True:
                    raise ClaudeDesignSafetyError("Artifact artboard violates the editable Design Component structure.")
        return {"index_verified": True, "artboards": list(order), "pending": pending, "render_executed": False}

    # Artifact administration

    def versions(self, value: str) -> dict[str, Any]:
        value = artifact_id(value)
        result = self.request("GET", ARTIFACT_API_PREFIX + "versions/" + value)
        if not isinstance(result, dict) or not isinstance(result.get("history"), list):
            raise ClaudeDesignProtocolError("Artifact version history is incomplete.")
        listed = result.get("versions")
        rows: dict[str, Any] = listed if isinstance(listed, dict) else {}
        history = []
        for version in result["history"]:
            if not isinstance(version, str) or REVISION.fullmatch(version) is None:
                continue
            found = rows.get(version)
            row: dict[str, Any] = found if isinstance(found, dict) else {}
            history.append(
                {
                    "version": version,
                    "title": _clean(row.get("title"), 2048),
                    "created_at": row.get("created_at"),
                    "seq": row.get("seq"),
                    "live": version == result.get("live"),
                    "shared": version == result.get("shared"),
                }
            )
        return {
            "backend": "artifact",
            "id": value,
            "url": artifact_url(value),
            "live": result.get("live"),
            "shared": result.get("shared") or None,
            "versions": history,
        }

    def retitle(self, value: str, title: str) -> dict[str, Any]:
        value = artifact_id(value)
        if not title.strip() or len(title) > 2048 or any(ord(c) < 32 for c in title):
            raise ValueError("Artifact title must contain 1–2048 printable characters.")
        self.require_write_window()
        self.request("POST", ARTIFACT_API_PREFIX + "retitle/" + value, {"title": title})
        try:
            after = self.snapshot(value)
        except Exception as error:
            raise ArtifactOutcomeUnknown("Artifact rename was submitted but could not be read back.") from error
        if after.title != title:
            raise ArtifactOutcomeUnknown("Artifact rename readback shows a different title; reconcile it.")
        return {"backend": "artifact", "id": value, "url": artifact_url(value), "title": title, "verified": True}

    def pin(self, value: str, pinned: bool) -> dict[str, Any]:
        value = artifact_id(value)
        self.request("POST" if pinned else "DELETE", ARTIFACT_API_PREFIX + "favorite/" + value)
        return {"backend": "artifact", "id": value, "url": artifact_url(value), "pinned": pinned, "mutated": True}

    def delete(self, value: str) -> dict[str, Any]:
        value = artifact_id(value)
        self.require_write_window()
        result = self.request("DELETE", ARTIFACT_API_PREFIX + value, allow_status=frozenset({404}))
        if isinstance(result, dict) and result.get("__status__") == 404:
            raise ArtifactHTTPError("No artifact at that id is yours to delete; nothing changed.", status=404)
        gone = self.request("GET", ARTIFACT_API_PREFIX + "read/" + value, allow_status=frozenset({404, 410}))
        if not (isinstance(gone, dict) and gone.get("__status__") in {404, 410}):
            raise ArtifactOutcomeUnknown("Artifact delete was submitted but the artifact still answers; reconcile.")
        return {"backend": "artifact", "id": value, "deleted": True, "verified": True}

    def diagnostics(self, value: str, version: str | None = None) -> dict[str, Any]:
        value = artifact_id(value)
        version = _revision(version) if version else self.snapshot(value).version
        result = self.request("GET", f"{ARTIFACT_API_PREFIX}diag/{value}/{version}", allow_status=frozenset({404}))
        if isinstance(result, dict) and result.get("__status__") == 404:
            return {"backend": "artifact", "id": value, "version": version, "state": "no_row", "entries": []}
        if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
            raise ClaudeDesignProtocolError("Artifact diagnostics response is incomplete.")
        kept, total = [], 0
        for entry in result["entries"]:
            size = len(json.dumps(entry, ensure_ascii=False))
            if total + size > ARTIFACT_MAX_DIAGNOSTIC_BYTES:
                continue
            kept.append(entry)
            total += size
        return {
            "backend": "artifact",
            "id": value,
            "version": version,
            "state": "loaded",
            "entries": kept,
            "dropped": len(result["entries"]) - len(kept),
            "truncated": result.get("truncated") is True,
            "untrusted": True,
        }

    def profiles(self, value: str, ids: list[str]) -> dict[str, Any]:
        value = artifact_id(value)
        if not ids or len(ids) > ARTIFACT_MAX_PROFILE_IDS or any(PROFILE_ID.fullmatch(i) is None for i in ids):
            raise ValueError("Pass 1–64 person ids shaped u_ plus 22 characters.")
        result = self.request(
            "POST", ARTIFACT_API_PREFIX + "user/profiles/" + value, {"ids": list(dict.fromkeys(ids))}, mutation=False
        )
        if not isinstance(result, dict):
            raise ClaudeDesignProtocolError("Artifact profile lookup is incomplete.")
        nested = result.get("profiles")
        rows: dict[str, Any] = nested if isinstance(nested, dict) else result
        return {
            "backend": "artifact",
            "id": value,
            "profiles": {
                key: {
                    "name": _clean(row.get("name") or row.get("display_name"), 200),
                    "guest": row.get("guest") is True,
                }
                for key, row in rows.items()
                if PROFILE_ID.fullmatch(key) and isinstance(row, dict)
            },
            "untrusted": True,
        }

    # Sharing

    def share_status(self, value: str) -> dict[str, Any]:
        value = artifact_id(value)
        perm = self.request("GET", ARTIFACT_API_PREFIX + "perm/" + value)
        if (
            not isinstance(perm, dict)
            or not isinstance(perm.get("read"), dict)
            or not isinstance(perm.get("version"), str)
        ):
            raise ClaudeDesignProtocolError("Artifact sharing settings are incomplete.")
        return perm

    @staticmethod
    def share_public(value: str, perm: dict[str, Any]) -> dict[str, Any]:
        read = perm["read"]
        return {
            "backend": "artifact",
            "id": value,
            "url": artifact_url(value),
            "read_mode": read.get("mode"),
            "people": read.get("users", []) if read.get("mode") == "users" else [],
            "viewers": perm.get("viewers", []),
            "commenters": perm.get("commenters", []),
            "editors": perm.get("editors", []),
            "write_mode": (perm.get("write") or {}).get("mode"),
            "assignable_read_modes": perm.get("assignableReadModes", []),
            "frozen": perm.get("readModeFrozen") is True,
            "org_read_level": perm.get("orgReadLevel"),
            "live": perm.get("live"),
            "shared_version": perm.get("shared") or None,
        }

    def share(
        self, value: str, mode: str, *, people: list[str] | None = None, access: str = "comment"
    ) -> dict[str, Any]:
        value = artifact_id(value)
        if mode not in ARTIFACT_SHARE_MODES or access not in ARTIFACT_SHARE_ACCESS:
            raise ValueError("Share mode is private, org, people, or public; access is view or comment.")
        people = [person.strip().lower() for person in people or []]
        if mode == "people" and (not people or any(USER_UUID.fullmatch(person) is None for person in people)):
            raise ValueError("Sharing with people needs their organization account UUIDs (--person).")
        self.require_write_window()
        perm = self.share_status(value)
        if perm.get("readModeFrozen") is True:
            raise ClaudeDesignSafetyError("This artifact's audience is frozen; manage it from the Share menu.")
        if not perm.get("owner_account"):
            raise ClaudeDesignSafetyError("Only artifacts with a personal owner are shared this way.")
        current = perm["read"].get("mode") or "owner"
        wire_mode = {"private": "owner", "org": "org", "people": "users", "public": "public"}[mode]
        assignable = perm.get("assignableReadModes")
        if (
            isinstance(assignable, list)
            and wire_mode not in assignable
            and wire_mode != current
            and not (wire_mode == "users" and perm.get("peopleRouteEnabled"))
        ):
            raise ClaudeDesignSafetyError(
                f"Sharing mode {mode} is not available for this artifact on this plan; available: "
                f"{', '.join(str(item) for item in assignable)}."
            )
        body: dict[str, Any]
        if mode == "people":
            owner = str(perm.get("owner_account", "")).lower()
            existing = [user.lower() for user in perm["read"].get("users", [])] if current == "users" else []
            added = [person for person in people if person != owner and person not in existing]
            body = {"read": {"mode": "org" if current == "org" else "users", "users": [*existing, *added]}}
            viewers = [user.lower() for user in perm.get("viewers", [])]
            commenters = [user.lower() for user in perm.get("commenters", [])]
            if access == "view":
                if perm.get("viewersEnabled") is not True:
                    raise ClaudeDesignSafetyError("View-only sharing with named people is unavailable here.")
                body["viewers"] = list(dict.fromkeys([*viewers, *added]))
            elif perm.get("commentersEnabled") is True:
                body["commenters"] = list(dict.fromkeys([*commenters, *added]))
        else:
            body = {"read": {"mode": wire_mode, **({"users": []} if wire_mode in {"org", "owner"} else {})}}
        if wire_mode == current and mode != "people":
            return {**self.share_public(value, perm), "unchanged": True, "verified": True}
        self.request(
            "PATCH",
            ARTIFACT_API_PREFIX + "perm/" + value,
            body,
            headers={"If-Match": perm["version"]},
        )
        try:
            after = self.share_status(value)
        except Exception as error:
            raise ArtifactOutcomeUnknown("The share was submitted but could not be read back.") from error
        if (after["read"].get("mode") or "owner") != body["read"]["mode"]:
            raise ArtifactOutcomeUnknown("Sharing readback does not show the requested audience; reconcile it.")
        return {**self.share_public(value, after), "unchanged": False, "verified": True, "mutated": True}
