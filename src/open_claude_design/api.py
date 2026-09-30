"""First-party design-system API using the existing scoped Design login.

Only reviewed methods are exposed. File mutations continue through MCP's atomic
etag checks; this API supplements it with raw reads and design-system creation.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from open_claude_design.config import (
    CLAUDE_DESIGN_GRANTS_ENDPOINT,
    CLAUDE_DESIGN_HTTP_TIMEOUT_SECONDS,
    CLAUDE_DESIGN_MAX_READ_ATTEMPTS,
    CLAUDE_DESIGN_MAX_READ_RETRY_SECONDS,
    CLAUDE_DESIGN_MAX_RPC_RESPONSE_BYTES,
    CLAUDE_DESIGN_MAX_TOOL_PAGES,
    CLAUDE_DESIGN_MAX_TOOLS,
    CLAUDE_DESIGN_MAX_TRANSFER_FILE_BYTES,
    CLAUDE_DESIGN_PROJECT_TYPES,
    CLAUDE_DESIGN_RPC_ENDPOINT,
    VERSION,
)
from open_claude_design.errors import ClaudeDesignAuthError, ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.operation_locks import operation_lock


@dataclass(frozen=True)
class RemoteFile:
    """Original bytes with a revision suitable for optimistic concurrency."""

    data: bytes
    etag: str
    content_type: str
    binary: bool


def read_retry_delay(error: urllib.error.HTTPError, attempt: int) -> float | None:
    """Honor short Retry-After values without creating unbounded waits."""
    if error.code not in {429, 502, 503, 504} or attempt >= CLAUDE_DESIGN_MAX_READ_ATTEMPTS - 1:
        return None
    raw = error.headers.get("Retry-After") if error.headers else None
    try:
        delay = float(raw) if raw is not None else 0.2 * (2**attempt)
    except ValueError:
        return None
    if not math.isfinite(delay) or delay < 0 or delay > CLAUDE_DESIGN_MAX_READ_RETRY_SECONDS:
        return None
    return delay


class DesignAPI:
    """A bounded, redirect-resistant API client; credentials never leave memory."""

    def __init__(
        self,
        *,
        token_reader: Callable[[], str],
        opener: Callable[..., Any],
        timeout: int = CLAUDE_DESIGN_HTTP_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        lock_factory: Callable[[str], AbstractContextManager[None]] = operation_lock,
    ) -> None:
        self._token_reader = token_reader
        self._opener = opener
        self._timeout = timeout
        self._sleep = sleep
        self._lock_factory = lock_factory

    def _request(
        self,
        method: str,
        arguments: dict[str, object],
        *,
        read_only: bool,
        grants: bool = False,
        http_method: str = "POST",
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            CLAUDE_DESIGN_GRANTS_ENDPOINT if grants else CLAUDE_DESIGN_RPC_ENDPOINT + method,
            data=None if http_method == "GET" else json.dumps(arguments).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token_reader()}",
                "Content-Type": "application/json",
                "User-Agent": f"open-claude-design/{VERSION}",
                "X-Anthropic-Client": "open-claude-design",
            },
            method=http_method,
        )
        for attempt in range(CLAUDE_DESIGN_MAX_READ_ATTEMPTS):
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read(CLAUDE_DESIGN_MAX_RPC_RESPONSE_BYTES + 1)
                if len(body) > CLAUDE_DESIGN_MAX_RPC_RESPONSE_BYTES:
                    raise ClaudeDesignProtocolError("Claude Design API response exceeds the safety limit.")
                result = json.loads(body) if body else {}
                if not isinstance(result, dict):
                    raise ClaudeDesignProtocolError("Claude Design API returned a non-object response.")
                return result
            except urllib.error.HTTPError as error:
                delay = read_retry_delay(error, attempt) if read_only else None
                if delay is not None:
                    error.close()
                    self._sleep(delay)
                    continue
                if error.code in {401, 403}:
                    raise ClaudeDesignAuthError(
                        f"Claude Design API refused this operation (HTTP {error.code}). "
                        "Check the signed-in account's Design access and permissions."
                    ) from error
                raise ClaudeDesignProtocolError(f"Claude Design API {method} failed (HTTP {error.code}).") from error
            except (urllib.error.URLError, TimeoutError) as error:
                raise ClaudeDesignProtocolError(f"Could not reach Claude Design API for {method}.") from error
            except (ValueError, UnicodeError, RecursionError) as error:
                raise ClaudeDesignProtocolError("Claude Design API returned an unreadable response.") from error
        raise ClaudeDesignProtocolError("Claude Design API exhausted its bounded read attempts.")

    def get_file(self, project_id: str, path: str) -> RemoteFile:
        result = self._request("GetFile", {"projectId": project_id, "path": path, "raw": True}, read_only=True)
        content, version = result.get("content"), result.get("version")
        if not isinstance(content, str) or not isinstance(version, str) or not version:
            raise ClaudeDesignProtocolError("Claude Design raw read returned no content or revision.")
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ClaudeDesignProtocolError("Claude Design raw file has invalid base64 encoding.") from error
        if len(data) > CLAUDE_DESIGN_MAX_TRANSFER_FILE_BYTES:
            raise ClaudeDesignProtocolError("Claude Design file exceeds the 16 MiB transfer limit.")
        content_type = result.get("contentType", "application/octet-stream")
        if not isinstance(content_type, str):
            raise ClaudeDesignProtocolError("Claude Design raw file has an invalid content type.")
        return RemoteFile(data, version, content_type, result.get("isBase64") is True)

    def list_projects(self, project_type: str | None = None) -> list[dict[str, Any]]:
        if project_type is None:
            return self.list_projects("project") + self.list_projects("design-system")
        if project_type is not None and project_type not in CLAUDE_DESIGN_PROJECT_TYPES:
            raise ValueError("Choose project or design-system as the project type.")
        projects: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = ""
        for _page in range(CLAUDE_DESIGN_MAX_TOOL_PAGES):
            arguments: dict[str, object] = {}
            if project_type:
                arguments["type"] = CLAUDE_DESIGN_PROJECT_TYPES[project_type]
            if cursor:
                arguments["cursor"] = cursor
            result = self._request("ListOrgProjects", arguments, read_only=True)
            items = result.get("items", [])
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ClaudeDesignProtocolError("Claude Design API returned invalid projects.")
            projects.extend(items)
            if len(projects) > CLAUDE_DESIGN_MAX_TOOLS:
                raise ClaudeDesignProtocolError("Claude Design API returned too many projects.")
            next_cursor = result.get("cursor", "")
            if not next_cursor:
                return projects
            if not isinstance(next_cursor, str) or next_cursor in seen:
                raise ClaudeDesignProtocolError("Claude Design API repeated a project cursor.")
            seen.add(next_cursor)
            cursor = next_cursor
        raise ClaudeDesignProtocolError("Claude Design API returned too many project pages.")

    def create_design_system(self, name: str) -> str:
        if not name.strip() or len(name) > 200:
            raise ValueError("A design-system name must contain 1 to 200 characters.")
        result = self._request(
            "CreateProject",
            {"name": name, "type": CLAUDE_DESIGN_PROJECT_TYPES["design-system"]},
            read_only=False,
        )
        project_id = result.get("projectId")
        if not isinstance(project_id, str) or not project_id:
            raise ClaudeDesignProtocolError("Claude Design did not return the new design-system id.")
        return project_id

    def settings(self) -> dict[str, Any]:
        return self._request("GetOrgSettings", {}, read_only=True)

    def project_metadata(self, project_id: str) -> dict[str, Any]:
        project = self._request("GetProject", {"projectId": project_id}, read_only=True)
        return {
            key: value
            for key, value in project.items()
            if key
            in {
                "projectId",
                "name",
                "type",
                "publishedAt",
                "callerCanEdit",
                "callerCanPublish",
                "callerCanDelete",
                "version",
                "designSystems",
            }
        }

    @contextlib.contextmanager
    def project_grant(self, project_id: str, *, allow_creation: bool) -> Iterator[None]:
        with (
            self._lock_factory("project-grant:" + project_id),
            self._project_grant_unlocked(project_id, allow_creation=allow_creation),
        ):
            yield

    @contextlib.contextmanager
    def _project_grant_unlocked(self, project_id: str, *, allow_creation: bool) -> Iterator[None]:
        result = self._request("grants", {}, read_only=True, grants=True, http_method="GET")
        grants = result.get("grants")
        if not isinstance(grants, list):
            raise ClaudeDesignProtocolError("Claude Design returned no project-grant inventory.")
        if self._has_grant(grants, project_id):
            yield
            return
        if not allow_creation:
            raise ClaudeDesignSafetyError(
                "Publishing requires a server project grant. Use --allow-project-grant only after "
                "authorization for this exact project; the temporary grant is revoked after the operation."
            )
        try:
            self._request("grants", {"project_id": project_id}, read_only=False, grants=True)
            yield
        finally:
            try:
                self._request("grants", {"project_id": project_id}, read_only=False, grants=True, http_method="DELETE")
                remaining = self._request("grants", {}, read_only=True, grants=True, http_method="GET").get("grants")
                if not isinstance(remaining, list) or self._has_grant(remaining, project_id):
                    raise ClaudeDesignProtocolError("The temporary project grant is still present.")
            except ClaudeDesignAuthError as error:
                raise ClaudeDesignAuthError(
                    f"Authentication failed while revoking the temporary grant for {project_id}. "
                    "Reconnect and revoke this exact project's grant before continuing."
                ) from error
            except ClaudeDesignProtocolError as error:
                raise ClaudeDesignProtocolError(
                    f"Could not verify revocation of the temporary grant for {project_id}; reconcile its permissions."
                ) from error

    @staticmethod
    def _has_grant(grants: list[Any], project_id: str) -> bool:
        return any(
            grant == project_id
            or (isinstance(grant, dict) and grant.get("project_id", grant.get("projectId")) == project_id)
            for grant in grants
        )

    def set_published(self, project_id: str, published: bool, *, allow_grant: bool) -> dict[str, Any]:
        with self.project_grant(project_id, allow_creation=allow_grant):
            self._request("SetProjectPublished", {"projectId": project_id, "published": published}, read_only=False)
            metadata = self.project_metadata(project_id)
            if bool(metadata.get("publishedAt")) != published:
                raise ClaudeDesignProtocolError("Design-system publication did not match the requested state.")
        return metadata

    def set_default(self, project_id: str, *, expected_current: str) -> dict[str, Any]:
        with self._lock_factory("organization-default"):
            before = self.settings()
            if before.get("defaultDesignSystemProjectUuid", "") != expected_current:
                raise ClaudeDesignSafetyError(
                    "The organization default changed after review; read settings and review again."
                )
            if expected_current == project_id:
                return {"verified": True, "mutated": False, "settings": before}
            self._request("UpdateOrgSettings", {"defaultDesignSystemProjectUuid": project_id}, read_only=False)
            current = self.settings()
            if current.get("defaultDesignSystemProjectUuid", "") != project_id:
                raise ClaudeDesignProtocolError("The organization default could not be verified after its update.")
            return {"verified": True, "mutated": True, "settings": current}

    def rename_project(self, project_id: str, name: str, *, allow_grant: bool) -> dict[str, Any]:
        if not name.strip() or len(name) > 200:
            raise ValueError("A project name must contain 1 to 200 characters.")
        with self.project_grant(project_id, allow_creation=allow_grant):
            self._request("UpdateProject", {"projectId": project_id, "name": name}, read_only=False)
            project = self.project_metadata(project_id)
            if project.get("name") != name:
                raise ClaudeDesignProtocolError("The new project name could not be verified.")
        return project

    def bind_systems(
        self,
        project_id: str,
        system_ids: list[str],
        *,
        expected_current: list[str],
        allow_grant: bool,
    ) -> dict[str, Any]:
        with self.project_grant(project_id, allow_creation=allow_grant):
            before = self.project_metadata(project_id).get("designSystems", [])
            current = [binding["dsProjectId"] for binding in before]
            if current != expected_current:
                raise ClaudeDesignSafetyError("Project bindings changed after review; inspect the project again.")
            bindings = [{"dsProjectId": system_id} for system_id in system_ids]
            self._request(
                "UpdateProjectDesignSystems", {"projectId": project_id, "designSystems": bindings}, read_only=False
            )
            project = self.project_metadata(project_id)
            actual = [binding["dsProjectId"] for binding in project.get("designSystems", [])]
            if set(actual) != set(system_ids) or len(actual) != len(system_ids):
                raise ClaudeDesignProtocolError("The project's design-system bindings could not be verified.")
        return project

    def delete_project(self, project_id: str, *, expected_version: str, allow_grant: bool) -> None:
        with self.project_grant(project_id, allow_creation=allow_grant):
            before = self.project_metadata(project_id)
            if before.get("version") != expected_version:
                raise ClaudeDesignSafetyError(
                    "Project metadata changed after review; inspect it again before deletion."
                )
            if before.get("callerCanDelete") is not True:
                raise ClaudeDesignSafetyError("This account cannot delete the selected project.")
            if self.settings().get("defaultDesignSystemProjectUuid") == project_id:
                raise ClaudeDesignSafetyError("Choose or clear the organization default explicitly before deleting it.")
            self._request("DeleteProject", {"projectId": project_id}, read_only=False)
            if any(project.get("projectId") == project_id for project in self.list_projects()):
                raise ClaudeDesignProtocolError("Project deletion could not be verified by the complete inventory.")
            self._request("grants", {"project_id": project_id}, read_only=False, grants=True, http_method="DELETE")
            remaining = self._request("grants", {}, read_only=True, grants=True, http_method="GET").get("grants", [])
            if self._has_grant(remaining, project_id):
                raise ClaudeDesignProtocolError("The deleted project's grant is still present.")

    def list_assets(self, project_id: str) -> list[dict[str, Any]]:
        result = self._request("ListProjectAssets", {"projectId": project_id}, read_only=True)
        assets = result.get("assets", [])
        if not isinstance(assets, list) or not all(isinstance(asset, dict) for asset in assets):
            raise ClaudeDesignProtocolError("Claude Design returned invalid asset cards.")
        return assets

    def register_asset(self, project_id: str, asset: dict[str, object], *, allow_grant: bool) -> None:
        with self.project_grant(project_id, allow_creation=allow_grant):
            self._request("RecordAsset", {**asset, "projectId": project_id}, read_only=False)
            registered = next(
                (entry for entry in self.list_assets(project_id) if entry.get("path") == asset["path"]), None
            )
            if not isinstance(registered, dict) or any(registered.get(key) != value for key, value in asset.items()):
                raise ClaudeDesignProtocolError("The asset card did not match its requested metadata.")

    def unregister_asset(self, project_id: str, path: str, *, allow_grant: bool) -> None:
        with self.project_grant(project_id, allow_creation=allow_grant):
            self._request("DeleteAsset", {"projectId": project_id, "path": path}, read_only=False)
            if any(asset.get("path") == path for asset in self.list_assets(project_id)):
                raise ClaudeDesignProtocolError("The asset card is still registered.")
