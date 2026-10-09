"""Artifact protocol boundaries, conditional writes, and retained sync approvals."""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from open_claude_design import artifact_auth, auth
from open_claude_design.artifact_api import (
    ArtifactClient,
    ArtifactConflict,
    ArtifactOutcomeUnknown,
    file_path,
)
from open_claude_design.artifact_sync import load, review_directory, save
from open_claude_design.bridge import build_parser, run_design_command
from open_claude_design.config import ARTIFACT_OAUTH_CLIENT_ID, ARTIFACT_OAUTH_SCOPES
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError

HTML = b'<html><head><script src="./support.js"></script></head><body><x-dc><div>Hello</div></x-dc></body></html>'
INDEX = json.dumps(
    {"v": 3, "boards": {"Main.dc.html": {"x": 0, "y": 0, "w": 480, "h": 320}}, "order": ["Main.dc.html"]}
).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Response:
    def __init__(self, body: Any) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def read(self, maximum: int) -> bytes:
        return self.body[:maximum]

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class Service:
    def __init__(self) -> None:
        self.files = {"project/Main.dc.html": HTML, "project/canvas.json": INDEX, "index.html": b"host"}
        self.version = "v1"
        self.calls: list[Any] = []
        self.writes: list[Any] = []
        self.failure: str | None = None
        self.narrowed = False
        self.public = False
        self.type_title = "Design"
        self.identity = "1" * 32

    def client(self) -> ArtifactClient:
        return ArtifactClient(
            credential_reader=lambda: {
                "accessToken": "test-bearer",
                "identity": self.identity,
                "expiresAt": int((time.time() + 3600) * 1000),
            },
            opener=self.open,
        )

    def open(self, request: Any, *, timeout: int) -> Response:
        self.calls.append(request)
        url = urlsplit(request.full_url)
        if url.hostname == "a.frame.claudeusercontent.com":
            assert request.get_header("Authorization") is None
            assert "test-capability" in url.query
            if url.path.endswith("/_files.json"):
                return Response(
                    {
                        "ver": self.version,
                        "narrowed": self.narrowed,
                        "files": {
                            path: {"sha256": digest(data), "size": len(data), "contentType": "text/plain"}
                            for path, data in self.files.items()
                        },
                    }
                )
            path = url.path.split("/", 3)[3]
            data = self.files[path]
            return Response(data + b"corrupt" if self.failure == "corrupt" else data)
        assert url.hostname == "api.anthropic.com"
        assert request.get_header("Authorization") == "Bearer test-bearer"
        assert request.get_header("X-frame-cp") == "go"
        assert request.get_header("X-frame-client-version") == "2.1.295"
        if url.path == "/api/frame/contract/latest":
            return Response({"version": "0.2.75", "capabilities": ["artifact", "files"]})
        if url.path == "/api/frame/read/a":
            return Response({"contract": "0.2.47", "owned": True, "public": self.public})
        if url.path == "/api/frame/a":
            return Response(
                {
                    "title": "Test",
                    "ver": self.version,
                    "assetToken": "test-capability",
                    "subscriptionToken": "test-subscription",
                    "perm": {"role": "owner", "mode": "owner"},
                    "type": {"slug": "design"},
                }
            )
        if url.path == "/api/frame/types/design":
            return Response({"slug": "design", "title": self.type_title})
        if url.path == "/api/frame/types":
            return Response({"types": [{"slug": "design", "title": "Design"}]})
        if url.path == "/api/frame/frames":
            return Response({"frames": [{"slug": "a", "title": "Test", "assetToken": "do-not-print"}]})
        if url.path == "/api/frame/types/design/create":
            self.writes.append(json.loads(request.data))
            return Response({"slug": "a", "version": self.version, "replayed": True})
        if url.path == "/api/frame/deploy/direct":
            body = json.loads(request.data)
            self.writes.append(body)
            if self.failure in {"conflict", "settling", "server", "redirect"}:
                status = {"conflict": 409, "settling": 409, "server": 503, "redirect": 302}[self.failure]
                reason = "precondition_failed" if self.failure == "conflict" else "publish_settling"
                raise urllib.error.HTTPError(
                    request.full_url, status, "refused", Message(), io.BytesIO(json.dumps({"reason": reason}).encode())
                )
            if self.failure == "timeout":
                raise TimeoutError("sensitive URL must stay hidden")
            assert body["baseVersion"] == self.version and body["mode"] == "patch" and body["title"] == "Test"
            for path, row in body["manifest"].items():
                assert row["ifMatch"] == (digest(self.files[path]) if path in self.files else None)
                self.files[path] = row["content"].encode()
            if self.failure == "readback":
                self.files["project/Main.dc.html"] += b"unexpected"
            self.version += "x"
            return Response({"slug": "a", "version": self.version})
        raise AssertionError(url.path)


def command(service: Service, root: Path, *values: str) -> int:
    args = build_parser().parse_args(["artifacts", *values, "--json"])
    return run_design_command(args, artifact_client_factory=service.client, workspace_root=root)


def test_control_and_content_credentials_are_separate_and_source_is_verified() -> None:
    service = Service()
    client = service.client()
    snapshot = client.snapshot("a")
    assert "test-capability" not in repr(snapshot)
    assert "test-capability" not in json.dumps(snapshot.public())
    assert client.read_file(snapshot, "project/Main.dc.html") == HTML
    service.failure = "corrupt"
    with pytest.raises(ClaudeDesignProtocolError, match="hash"):
        client.read_file(snapshot, "project/Main.dc.html")


def test_incomplete_inventory_is_never_used_as_absence() -> None:
    service = Service()
    service.narrowed = True
    with pytest.raises(ClaudeDesignProtocolError, match="inventory"):
        service.client().snapshot("a")


@pytest.mark.parametrize("path", ["../secret", "project/../secret", "/project/a", "project/a?token=x", "project/a\\b"])
def test_paths_cannot_escape_or_carry_capabilities(path: str) -> None:
    with pytest.raises(ValueError):
        file_path(path, write=True)


def test_conditional_patch_keeps_runtime_and_omitted_files_and_guards_new_files() -> None:
    service = Service()
    client = service.client()
    before = client.snapshot("a")
    changed = HTML.replace(b"Hello", b"Changed")
    result = client.push(
        before,
        {"project/Main.dc.html": changed, "project/notes.txt": b"Notes"},
        {"project/Main.dc.html": digest(HTML), "project/notes.txt": "0"},
    )
    assert result["verified"] and result["render_executed"] is False
    assert service.files["index.html"] == b"host" and service.files["project/canvas.json"] == INDEX
    assert service.writes[0]["manifest"]["project/notes.txt"]["ifMatch"] is None
    with pytest.raises(ArtifactConflict):
        client.push(client.snapshot("a"), {"project/Main.dc.html": HTML}, {"project/Main.dc.html": digest(HTML)})
    assert len(service.writes) == 1


@pytest.mark.parametrize(
    "failure,exception",
    [
        ("conflict", ArtifactConflict),
        ("settling", ArtifactOutcomeUnknown),
        ("server", ArtifactOutcomeUnknown),
        ("redirect", ArtifactOutcomeUnknown),
        ("timeout", ArtifactOutcomeUnknown),
    ],
)
def test_submitted_writes_are_never_retried_and_conflict_evidence_is_specific(failure: str, exception: type) -> None:
    service = Service()
    client = service.client()
    before = client.snapshot("a")
    service.failure = failure
    with pytest.raises(exception) as error:
        client.push(before, {"project/Main.dc.html": HTML}, {"project/Main.dc.html": digest(HTML)})
    assert len(service.writes) == 1 and "sensitive" not in str(error.value)


@pytest.mark.parametrize("failure", ["public", "wrong_type", "bad_canvas", "runtime_file"])
def test_unreviewed_artifact_writes_are_refused_before_submission(failure: str) -> None:
    service = Service()
    service.public = failure == "public"
    service.type_title = "Dashboard" if failure == "wrong_type" else "Design"
    client = service.client()
    snapshot = client.snapshot("a")
    files = {"project/Main.dc.html": HTML}
    if failure == "bad_canvas":
        files["project/canvas.json"] = b'{"v":3,"boards":{},"order":[]}'
    if failure == "runtime_file":
        files = {"index.html": b"overwrite"}
    matches = {path: digest(service.files[path]) for path in files}
    with pytest.raises(ClaudeDesignSafetyError):
        client.push(snapshot, files, matches)
    assert not service.writes


def test_create_requires_reusable_idempotency_key_and_private_verified_type() -> None:
    service = Service()
    client = service.client()
    with pytest.raises(ValueError):
        client.create("Test", "bad-key")
    assert not service.writes
    service.public = True
    with pytest.raises(ArtifactOutcomeUnknown):
        client.create("Test", "11111111-1111-4111-8111-111111111111")
    assert len(service.writes) == 1


def test_cli_auth_is_not_used_for_offline_status_and_listing_redacts_capabilities(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = Service()
    assert command(service, tmp_path, "sync", "status") == 0
    assert not service.calls
    assert command(service, tmp_path, "list") == 0
    assert "do-not-print" not in capsys.readouterr().out
    for name in ("status", "capabilities"):
        args = build_parser().parse_args([name, "--backend", "artifact", "--json"])
        assert (
            run_design_command(
                args,
                artifact_client_factory=service.client,
                client_factory=lambda: pytest.fail("standalone transport used"),
            )
            == 0
        )


def prepare(service: Service, root: Path, capsys: pytest.CaptureFixture[str], *, direction: str = "to-design") -> str:
    assert (
        command(
            service,
            root,
            "sync",
            "review",
            "a",
            "--direction",
            direction,
            "--pair",
            "project/Main.dc.html=Main.dc.html",
        )
        == 0
    )
    return json.loads(capsys.readouterr().out)["review_id"]


def test_sync_roundtrip_establishes_baseline_consumes_approval_and_removes_snapshots(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = Service()
    (tmp_path / "Main.dc.html").write_bytes(HTML.replace(b"Hello", b"Local"))
    review_id = prepare(service, tmp_path, capsys)
    assert command(service, tmp_path, "sync", "apply", review_id, "--allow-write") == 0
    capsys.readouterr()
    with pytest.raises(ClaudeDesignSafetyError, match="consumed"):
        command(service, tmp_path, "sync", "apply", review_id, "--allow-write")
    assert command(service, tmp_path, "sync", "finish", review_id) == 0
    capsys.readouterr()
    assert not list((review_directory(tmp_path, review_id) / "snapshots").glob("*.bin"))
    followup = prepare(service, tmp_path, capsys)
    assert load(tmp_path, followup)["classification"] == "unchanged"
    assert command(service, tmp_path, "sync", "apply", followup, "--allow-write") == 0
    capsys.readouterr()
    assert len(service.writes) == 1


@pytest.mark.parametrize("changed", ["local", "remote", "identity", "snapshot", "receipt"])
def test_sync_cannot_apply_changed_sources_account_or_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    changed: str,
) -> None:
    service = Service()
    (tmp_path / "Main.dc.html").write_bytes(HTML)
    review_id = prepare(service, tmp_path, capsys)
    if changed == "local":
        (tmp_path / "Main.dc.html").write_bytes(b"different")
    elif changed == "remote":
        service.version = "v2"
    elif changed == "identity":
        service.identity = "2" * 32
    elif changed == "snapshot":
        receipt = load(tmp_path, review_id)
        (tmp_path / receipt["pairs"][0]["local_snapshot"]).write_bytes(b"tampered")
    else:
        receipt = load(tmp_path, review_id)
        receipt["pairs"][0]["local_snapshot"] = "outside.bin"
        save(tmp_path, receipt)
    if changed in {"local", "remote"}:
        assert command(service, tmp_path, "sync", "apply", review_id, "--allow-write") == 3
    else:
        with pytest.raises((ClaudeDesignSafetyError, ValueError)):
            command(service, tmp_path, "sync", "apply", review_id, "--allow-write")
    assert not service.writes


def test_unknown_apply_is_consumed_and_does_not_advance_baseline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = Service()
    (tmp_path / "Main.dc.html").write_bytes(HTML.replace(b"Hello", b"Changed"))
    review_id = prepare(service, tmp_path, capsys)
    service.failure = "timeout"
    assert command(service, tmp_path, "sync", "apply", review_id, "--allow-write") == 2
    assert load(tmp_path, review_id)["state"] == "unknown"
    with pytest.raises(ClaudeDesignSafetyError, match="consumed"):
        command(service, tmp_path, "sync", "apply", review_id, "--allow-write")
    assert len(service.writes) == 1


def test_to_code_handoff_retains_remote_snapshot_until_local_implementation_finishes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = Service()
    review_id = prepare(service, tmp_path, capsys, direction="to-code")
    assert command(service, tmp_path, "sync", "apply", review_id, "--allow-write") == 0
    capsys.readouterr()
    receipt = load(tmp_path, review_id)
    assert (tmp_path / receipt["pairs"][0]["remote_snapshot"]).read_bytes() == HTML
    assert not (tmp_path / "Main.dc.html").exists()
    with pytest.raises(ClaudeDesignSafetyError, match="Implement"):
        command(service, tmp_path, "sync", "finish", review_id)
    (tmp_path / "Main.dc.html").write_bytes(HTML.replace(b"Hello", b"Implemented"))
    assert command(service, tmp_path, "sync", "finish", review_id) == 0
    assert not service.writes


def token() -> dict[str, object]:
    return {
        "access_token": "test-access",
        "refresh_token": "test-refresh",
        "expires_in": 3600,
        "scope": " ".join(ARTIFACT_OAUTH_SCOPES),
    }


def test_artifact_credential_store_and_refresh_do_not_read_standalone_or_other_harnesses(tmp_path: Path) -> None:
    payload = auth._credential_payload(
        token(),
        client_id=ARTIFACT_OAUTH_CLIENT_ID,
        required_scopes=ARTIFACT_OAUTH_SCOPES,
        record_key="artifactOauth",
        now_ms=0,
    )
    artifact_auth.save_artifact_credential(payload, platform="linux", home=tmp_path)
    path = artifact_auth.credential_file(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    original = artifact_auth.load_artifact_credential(platform="linux", home=tmp_path, now_ms=0)
    assert auth.load_standalone_credential(platform="linux", home=tmp_path, now_ms=0) is None
    requests = []

    def opener(request: Any, **kwargs: Any) -> Response:
        requests.append(json.loads(request.data))
        return Response(token())

    refreshed = artifact_auth.load_artifact_credential(
        platform="linux", home=tmp_path, now_ms=3_600_000, token_opener=opener
    )
    assert refreshed["identity"] == original["identity"]
    assert requests[0]["scope"] == " ".join(ARTIFACT_OAUTH_SCOPES)
    assert artifact_auth.delete_artifact_credential(platform="linux", home=tmp_path)
    with pytest.raises(auth.DesignAuthError, match="backend artifact"):
        artifact_auth.load_artifact_credential(platform="linux", home=tmp_path)


def test_readback_mismatch_is_unknown_after_exactly_one_submission() -> None:
    service = Service()
    client = service.client()
    before = client.snapshot("a")
    service.failure = "readback"
    with pytest.raises(ArtifactOutcomeUnknown, match="unverified"):
        client.push(before, {"project/Main.dc.html": HTML}, {"project/Main.dc.html": digest(HTML)})
    assert len(service.writes) == 1


def test_both_changed_requires_an_explicit_reconciled_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    (tmp_path / "Main.dc.html").write_bytes(HTML)
    first = prepare(service, tmp_path, capsys)
    assert command(service, tmp_path, "sync", "apply", first, "--allow-write") == 0
    capsys.readouterr()
    assert command(service, tmp_path, "sync", "finish", first) == 0
    capsys.readouterr()
    service.files["project/Main.dc.html"] = HTML.replace(b"Hello", b"Remote")
    service.version = "v2"
    (tmp_path / "Main.dc.html").write_bytes(HTML.replace(b"Hello", b"Reconciled local"))
    second = prepare(service, tmp_path, capsys)
    assert load(tmp_path, second)["classification"] == "both-changed"
    with pytest.raises(ClaudeDesignSafetyError, match="Both sides"):
        command(service, tmp_path, "sync", "apply", second, "--allow-write")
    assert not service.writes
    assert command(service, tmp_path, "sync", "apply", second, "--allow-write", "--reconciled") == 0
    assert len(service.writes) == 1


def test_local_symlink_cannot_be_read_or_overwritten_by_artifact_commands(tmp_path: Path) -> None:
    service = Service()
    target = tmp_path / "actual.dc.html"
    target.write_bytes(HTML)
    link = tmp_path / "linked.dc.html"
    link.symlink_to(target)
    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        command(service, tmp_path, "pull", "a", "project/Main.dc.html", "--output", str(link), "--force")
    assert target.read_bytes() == HTML and not service.calls
    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        command(
            service,
            tmp_path,
            "push",
            "a",
            "--file",
            f"project/Main.dc.html={link}",
            "--if-match",
            f"project/Main.dc.html={digest(HTML)}",
            "--allow-write",
        )
    assert not service.writes


def test_artifact_keychain_never_uses_the_standalone_service_or_secret_argv() -> None:
    import subprocess

    from open_claude_design.config import ARTIFACT_KEYCHAIN_ACCOUNT, ARTIFACT_KEYCHAIN_SERVICE

    calls = []
    payload = auth._credential_payload(
        token(), client_id=ARTIFACT_OAUTH_CLIENT_ID, required_scopes=ARTIFACT_OAUTH_SCOPES, record_key="artifactOauth"
    )

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if "-w" in command:
            assert ARTIFACT_KEYCHAIN_SERVICE in command and ARTIFACT_KEYCHAIN_ACCOUNT in command
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        assert command == ["/usr/bin/security", "-i"]
        assert "test-access" not in json.dumps(command)
        assert ARTIFACT_KEYCHAIN_SERVICE in kwargs["input"]
        return subprocess.CompletedProcess(command, 0, "", "")

    artifact_auth.save_artifact_credential(payload, platform="darwin", runner=runner)
    assert artifact_auth.load_artifact_credential(platform="darwin", runner=runner)["accessToken"] == "test-access"
    assert len(calls) == 2
