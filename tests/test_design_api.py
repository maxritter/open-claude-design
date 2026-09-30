"""Raw-transfer, retry, publication, and temporary-grant behavioral contracts."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import struct
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from open_claude_design.api import DesignAPI
from open_claude_design.binary import PNG_SIGNATURE, original_png_bytes
from open_claude_design.bridge import ClaudeDesignClient
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.operation_locks import operation_lock

pytestmark = pytest.mark.unit


class Response:
    def __init__(self, value: dict[str, Any] | None) -> None:
        self.body = b"" if value is None else json.dumps(value).encode()

    def read(self, size: int) -> bytes:
        return self.body[:size]

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def test_raw_read_keeps_binary_bytes_and_revision() -> None:
    data = bytes(range(256)) * 2048
    requests: list[urllib.request.Request] = []

    def opener(request: urllib.request.Request, **_kwargs: object) -> Response:
        requests.append(request)
        return Response({"content": base64.b64encode(data).decode(), "version": "17", "isBase64": True})

    remote = DesignAPI(token_reader=lambda: "test-scoped-token", opener=opener).get_file("project", "asset.bin")
    assert remote.data == data
    assert remote.etag == "17"
    assert remote.binary
    assert json.loads(requests[0].data or b"{}") == {"projectId": "project", "path": "asset.bin", "raw": True}


@pytest.mark.parametrize(
    "payload", [{"content": "!!!", "version": "1"}, {"content": "YQ=="}, {"content": [], "version": "1"}]
)
def test_raw_read_rejects_missing_revision_and_invalid_encoding(payload: dict[str, Any]) -> None:
    api = DesignAPI(token_reader=lambda: "test-token", opener=lambda *_args, **_kwargs: Response(payload))
    with pytest.raises(ClaudeDesignProtocolError):
        api.get_file("p", "a")


def test_only_reads_retry_a_transient_http_error() -> None:
    count = 0
    sleeps: list[float] = []

    def opener(request: urllib.request.Request, **_kwargs: object) -> Response:
        nonlocal count
        count += 1
        if count == 1:
            headers = Message()
            headers["Retry-After"] = "0"
            raise urllib.error.HTTPError(request.full_url, 429, "limited", headers, io.BytesIO())
        return Response({"items": []})

    api = DesignAPI(token_reader=lambda: "test-token", opener=opener, sleep=sleeps.append)
    assert api.list_projects("design-system") == []
    assert count == 2 and sleeps == [0]
    count = 0
    with pytest.raises(ClaudeDesignProtocolError, match="HTTP 429"):
        api.create_design_system("System")
    assert count == 1


def test_long_retry_after_fails_without_sleeping() -> None:
    sleeps: list[float] = []

    def opener(request: urllib.request.Request, **_kwargs: object) -> Response:
        headers = Message()
        headers["Retry-After"] = "120"
        raise urllib.error.HTTPError(request.full_url, 429, "limited", headers, io.BytesIO())

    api = DesignAPI(token_reader=lambda: "test-token", opener=opener, sleep=sleeps.append)
    with pytest.raises(ClaudeDesignProtocolError):
        api.list_projects("design-system")
    assert sleeps == []


def test_project_pagination_rejects_repeated_cursor() -> None:
    api = DesignAPI(
        token_reader=lambda: "test-token", opener=lambda *_args, **_kwargs: Response({"items": [], "cursor": "same"})
    )
    with pytest.raises(ClaudeDesignProtocolError, match="repeated"):
        api.list_projects("design-system")


class GrantAPI(DesignAPI):
    def __init__(self, *, existing: bool = False, fail_publish: bool = False, fail_revoke: bool = False) -> None:
        super().__init__(
            token_reader=lambda: "test-token",
            opener=lambda *_args, **_kwargs: Response({}),
            lock_factory=lambda _key: contextlib.nullcontext(),
        )
        self.granted = existing
        self.fail_publish = fail_publish
        self.fail_revoke = fail_revoke
        self.published = False
        self.calls: list[tuple[str, str]] = []

    def _request(
        self,
        method: str,
        arguments: dict[str, object],
        *,
        read_only: bool,
        grants: bool = False,
        http_method: str = "POST",
    ) -> dict[str, Any]:
        self.calls.append((method, http_method))
        if grants:
            if http_method == "GET":
                return {"grants": [{"project_id": "p"}] if self.granted else []}
            if http_method == "DELETE":
                if self.fail_revoke:
                    raise ClaudeDesignProtocolError("synthetic cleanup failure")
                self.granted = False
            else:
                self.granted = True
            return {}
        if method == "SetProjectPublished":
            if self.fail_publish:
                raise ClaudeDesignProtocolError("synthetic publish failure")
            self.published = arguments["published"] is True
            return {}
        if method == "GetProject":
            return {"projectId": "p", "publishedAt": "today" if self.published else None, "data": "private-chat-data"}
        raise AssertionError(method)


def test_publication_verifies_state_and_revokes_its_temporary_grant() -> None:
    api = GrantAPI()
    metadata = api.set_published("p", True, allow_grant=True)
    assert metadata["publishedAt"] == "today"
    assert "data" not in metadata
    assert not api.granted
    assert api.calls[-2:] == [("grants", "DELETE"), ("grants", "GET")]


def test_publication_preserves_a_preexisting_grant() -> None:
    api = GrantAPI(existing=True)
    api.set_published("p", False, allow_grant=False)
    assert api.granted
    assert ("grants", "DELETE") not in api.calls


def test_publication_without_grant_authority_makes_no_mutation() -> None:
    api = GrantAPI()
    with pytest.raises(ClaudeDesignSafetyError, match="allow-project-grant"):
        api.set_published("p", True, allow_grant=False)
    assert api.calls == [("grants", "GET")]


def test_failed_publication_still_revokes_the_temporary_grant() -> None:
    api = GrantAPI(fail_publish=True)
    with pytest.raises(ClaudeDesignProtocolError, match="publish failure"):
        api.set_published("p", True, allow_grant=True)
    assert not api.granted


def test_failed_grant_cleanup_is_an_explicit_failure() -> None:
    api = GrantAPI(fail_revoke=True)
    with pytest.raises(ClaudeDesignProtocolError, match="revocation"):
        api.set_published("p", True, allow_grant=True)
    assert api.granted


class SettingsAPI(DesignAPI):
    def __init__(self) -> None:
        super().__init__(
            token_reader=lambda: "test-token",
            opener=lambda *_args, **_kwargs: Response({}),
            lock_factory=lambda _key: contextlib.nullcontext(),
        )
        self.current = {"defaultDesignSystemProjectUuid": "old", "disablePublicLinksAndArtifacts": True}
        self.writes: list[dict[str, object]] = []

    def _request(
        self,
        method: str,
        arguments: dict[str, object],
        *,
        read_only: bool,
        grants: bool = False,
        http_method: str = "POST",
    ) -> dict[str, Any]:
        if method == "GetOrgSettings":
            return self.current.copy()
        assert method == "UpdateOrgSettings" and not read_only
        self.writes.append(arguments)
        self.current.update(arguments)
        return {}


def test_default_change_only_updates_the_reviewed_default_field() -> None:
    api = SettingsAPI()
    result = api.set_default("new", expected_current="old")
    assert result["verified"] is True
    assert api.writes == [{"defaultDesignSystemProjectUuid": "new"}]
    assert api.current["disablePublicLinksAndArtifacts"] is True


def test_stale_or_unchanged_default_never_mutates() -> None:
    api = SettingsAPI()
    with pytest.raises(ClaudeDesignSafetyError, match="changed after review"):
        api.set_default("new", expected_current="stale")
    assert api.writes == []
    assert api.set_default("old", expected_current="old")["mutated"] is False
    assert api.writes == []


class ProjectsAPI(GrantAPI):
    def __init__(self) -> None:
        super().__init__(existing=True)
        self.project: dict[str, Any] = {"projectId": "p", "version": "1", "callerCanDelete": True, "designSystems": []}
        self.deleted = False
        self.mutations: list[str] = []

    def _request(
        self,
        method: str,
        arguments: dict[str, object],
        *,
        read_only: bool,
        grants: bool = False,
        http_method: str = "POST",
    ) -> dict[str, Any]:
        if grants:
            return super()._request(method, arguments, read_only=read_only, grants=grants, http_method=http_method)
        if method == "GetProject":
            return self.project.copy()
        if method == "GetOrgSettings":
            return {"defaultDesignSystemProjectUuid": "other"}
        if method == "ListOrgProjects":
            assert arguments.get("type") in {"PROJECT_TYPE_PROJECT", "PROJECT_TYPE_DESIGN_SYSTEM"}
            return {"items": [] if self.deleted else [self.project]}
        self.mutations.append(method)
        if method == "UpdateProjectDesignSystems":
            self.project["designSystems"] = arguments["designSystems"]
        elif method == "DeleteProject":
            self.deleted = True
        else:
            raise AssertionError(method)
        return {}


def test_binding_changes_verify_ids_and_reject_stale_reviews() -> None:
    api = ProjectsAPI()
    result = api.bind_systems("p", ["modern", "legacy"], expected_current=[], allow_grant=False)
    assert result["designSystems"] == [
        {"dsProjectId": "modern"},
        {"dsProjectId": "legacy"},
    ]
    with pytest.raises(ClaudeDesignSafetyError, match="changed after review"):
        api.bind_systems("p", [], expected_current=[], allow_grant=False)
    assert api.mutations == ["UpdateProjectDesignSystems"]


def test_cli_client_forwards_the_reviewed_binding_contract() -> None:
    client = ClaudeDesignClient(token_reader=lambda: "test-token")
    client._api = ProjectsAPI()
    result = client.bind_design_systems("p", ["system"], expected_current=[], allow_grant=False)
    assert result["designSystems"] == [{"dsProjectId": "system"}]


def test_project_deletion_refuses_stale_metadata_and_verifies_absence() -> None:
    api = ProjectsAPI()
    with pytest.raises(ClaudeDesignSafetyError, match="metadata changed"):
        api.delete_project("p", expected_version="stale", allow_grant=False)
    assert not api.mutations
    api.delete_project("p", expected_version="1", allow_grant=False)
    assert api.deleted
    assert api.mutations == ["DeleteProject"]


def test_complete_project_inventory_always_supplies_a_valid_type_filter() -> None:
    requests = []

    def opener(request: urllib.request.Request, **_kwargs: object) -> Response:
        data = json.loads(request.data or b"{}")
        requests.append(data)
        return Response({"items": []})

    api = DesignAPI(token_reader=lambda: "test-token", opener=opener)
    assert api.list_projects() == []
    assert requests == [{"type": "PROJECT_TYPE_PROJECT"}, {"type": "PROJECT_TYPE_DESIGN_SYSTEM"}]


def test_operation_lock_prevents_overlapping_local_grant_transactions(tmp_path: Path) -> None:
    with (
        operation_lock("p", home=tmp_path),
        pytest.raises(ClaudeDesignSafetyError, match="Another local agent"),
        operation_lock("p", home=tmp_path, timeout=0.05),
    ):
        pytest.fail("A concurrent permission transaction acquired the same lock")
    with operation_lock("p", home=tmp_path, timeout=0.05):
        pass


def test_operation_lock_refuses_a_symlinked_directory(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    (tmp_path / ".config").symlink_to(actual, target_is_directory=True)
    with pytest.raises(ClaudeDesignSafetyError, match="unsafe"), operation_lock("p", home=tmp_path):
        pytest.fail("The symlinked lock directory was accepted")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + b"\0" * 4


def test_read_added_provenance_is_removed_only_against_the_stored_byte_count() -> None:
    original = PNG_SIGNATURE + _chunk(b"IHDR", b"header") + _chunk(b"IDAT", b"image") + _chunk(b"IEND", b"")
    enhanced = original[:8] + _chunk(b"caBX", b"read-added-provenance") + original[8:]
    assert original_png_bytes(enhanced, len(original)) == original
    assert original_png_bytes(enhanced, len(enhanced)) == enhanced
    with pytest.raises(ClaudeDesignProtocolError):
        original_png_bytes(enhanced, len(original) - 1)


def test_ambiguous_or_truncated_png_recovery_is_rejected() -> None:
    chunks = _chunk(b"caBX", b"one") + _chunk(b"caBX", b"two") + _chunk(b"IEND", b"")
    enhanced = PNG_SIGNATURE + chunks
    with pytest.raises(ClaudeDesignProtocolError):
        original_png_bytes(enhanced, len(enhanced) - 15)
    with pytest.raises(ClaudeDesignProtocolError):
        original_png_bytes(enhanced[:-1], 8)
