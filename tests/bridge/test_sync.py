"""Revision-bound code and Claude Design synchronization contracts."""

from __future__ import annotations

import json
import stat
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

import open_claude_design.bridge as claude_design
from open_claude_design.bridge import (
    ClaudeDesignAuthError,
    ClaudeDesignProtocolError,
    ClaudeDesignSafetyError,
    run_design_command,
)

pytestmark = pytest.mark.unit


class SyncStubClient:
    """Stateful Claude Design stub for revision-aware synchronization."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.remote: dict[str, tuple[str, str]] = {
            "Example.dc.html": ("remote-1", "<main>remote</main>\n"),
            "support.js": ("support-1", "runtime\n"),
        }
        self.write_preflights = 0
        self.fail_reads = False
        self.conflict_on_write = False

    def require_write_window(self) -> None:
        self.write_preflights += 1

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "list_files":
            parent = str(arguments.get("path", ""))
            entries = [
                {"path": path, "type": "file", "etag": etag, "size": len(body.encode())}
                for path, (etag, body) in sorted(self.remote.items())
                if (Path(path).parent.as_posix() if "/" in path else "") == parent
            ]
            return {"content": [{"type": "text", "text": json.dumps(entries)}]}
        if name == "read_file":
            if self.fail_reads:
                raise ClaudeDesignProtocolError("synthetic readback failure")
            path = str(arguments["path"])
            if path not in self.remote:
                return {"isError": True, "content": [{"type": "text", "text": "missing"}]}
            etag, body = self.remote[path]
            if arguments.get("if_none_match") == etag:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"unchanged": True, "etag": etag, "path": path}),
                        }
                    ]
                }
            escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f'<untrusted-project-content path="{path}" etag="{etag}">\n'
                            f"{escaped}\n</untrusted-project-content>"
                        ),
                    }
                ]
            }
        if name == "finalize_plan":
            writes = arguments.get("writes")
            assert isinstance(writes, list)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "plan_token": "internal-sync-plan",
                                "base_etags": {
                                    path: self.remote[path][0] if path in self.remote else "0" for path in writes
                                },
                            }
                        ),
                    }
                ]
            }
        if name == "write_files":
            files = arguments.get("files")
            assert isinstance(files, list)
            if self.conflict_on_write:
                for item in files:
                    assert isinstance(item, dict)
                    path = str(item["path"])
                    self.remote[path] = ("remote-concurrent", "<main>concurrent</main>\n")
                return {"structuredContent": {"status": "conflict", "paths": []}}
            etags: dict[str, str] = {}
            for item in files:
                assert isinstance(item, dict)
                path = str(item["path"])
                body = str(item["data"])
                next_etag = f"remote-{int(self.remote.get(path, ('remote-0', ''))[0].split('-')[-1]) + 1}"
                self.remote[path] = (next_etag, body)
                etags[path] = next_etag
            return {
                "structuredContent": {"status": "written", "paths": sorted(etags), "etags": etags},
                "content": [{"type": "text", "text": "written"}],
            }
        if name == "render_preview":
            return {
                "structuredContent": {
                    "open_url": "https://claude.ai/design/p/project-1",
                    "serve_url": "https://preview.claudeusercontent.com/short-lived",
                }
            }
        raise AssertionError(f"unexpected tool call: {name}")


class ExpiringSyncStubClient(SyncStubClient):
    def require_write_window(self) -> None:
        raise ClaudeDesignAuthError("synthetic credential expiry")


def _review_args(local: Path, *, direction: str = "to-design") -> Namespace:
    return Namespace(
        design_command="sync",
        sync_command="review",
        project_id="project-1",
        direction=direction,
        pairs=[f"Example.dc.html={local}"],
        json=True,
    )


def _receipt_id(capsys: pytest.CaptureFixture[str]) -> str:
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "reviewed"
    assert payload["requires_approval"] is True
    return str(payload["review_id"])


def test_sync_review_records_exact_revisions_without_printing_file_bodies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()

    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "reviewed"
    assert payload["classification"] == "unknown"
    assert payload["requires_approval"] is True
    assert payload["mutated"] is False
    assert "remote-1" not in json.dumps(payload)
    assert "<main>" not in json.dumps(payload)
    assert (tmp_path / payload["receipt_path"]).is_file()
    assert (tmp_path / payload["diff_path"]).is_file()
    assert stat.S_IMODE((tmp_path / payload["receipt_path"]).stat().st_mode) == 0o600


def test_sync_review_represents_binary_content_without_printing_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_bytes(b"\xff\x00")
    client = SyncStubClient()

    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0

    payload = json.loads(capsys.readouterr().out)
    diff = (tmp_path / payload["diff_path"]).read_text(encoding="utf-8")
    assert "binary revisions differ" in diff
    assert "ff00" not in json.dumps(payload)


def test_sync_state_is_locally_excluded_from_git_status_without_tracked_changes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    subprocess.run(["git", "add", "Example.dc.html"], cwd=tmp_path, check=True)
    client = SyncStubClient()

    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()

    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".open-claude-design" not in status
    exclude = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (tmp_path / exclude).read_text(encoding="utf-8").splitlines().count(".open-claude-design/") == 1


def test_unavailable_git_exclude_does_not_block_sync(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    original_run = subprocess.run

    def fail_git_only(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "rev-parse"]:
            raise subprocess.TimeoutExpired(command, 5)
        return original_run(command, **kwargs)

    monkeypatch.setattr("open_claude_design.bridge.subprocess.run", fail_git_only)

    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "reviewed"


def test_sync_apply_refuses_changed_local_revision_before_any_remote_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.calls.clear()

    local.write_text("<main>changed after approval</main>\n", encoding="utf-8")
    args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["requires_reapproval"] is True
    assert payload["mutated"] is False
    assert payload["changed"] == [{"side": "local", "path": "Example.dc.html"}]
    assert client.calls == []
    assert client.write_preflights == 0


def test_sync_apply_refuses_changed_remote_revision_before_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.calls.clear()
    client.remote["Example.dc.html"] = ("remote-2", "<main>changed in design</main>\n")

    args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["changed"] == [{"side": "remote", "path": "Example.dc.html"}]
    assert "current-design/Example.dc.html" in (tmp_path / payload["diff_path"]).read_text(encoding="utf-8")
    assert "write_files" not in [name for name, _arguments in client.calls]


def test_sync_apply_treats_server_etag_conflict_as_stale_without_our_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.conflict_on_write = True

    args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["mutated"] is False
    assert payload["changed"] == [{"side": "remote", "path": "Example.dc.html"}]


def test_sync_apply_rejects_tampered_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    reviewed = json.loads(capsys.readouterr().out)
    receipt_path = tmp_path / reviewed["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["direction"] = "to-code"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    client.calls.clear()

    args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=reviewed["review_id"],
        allow_write=True,
        json=True,
    )
    with pytest.raises(ValueError, match="changed after it was created"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.calls == []


def test_sync_apply_requires_exact_review_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.calls.clear()

    args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=False,
        json=True,
    )
    with pytest.raises(ClaudeDesignSafetyError, match="approved the exact recorded review"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.calls == []


def test_sync_preflight_auth_failure_keeps_review_pending(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    review_client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: review_client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    expiring_client = ExpiringSyncStubClient()

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    with pytest.raises(ClaudeDesignAuthError, match="credential expiry"):
        run_design_command(apply_args, client_factory=lambda: expiring_client, workspace_root=tmp_path)

    status_args = Namespace(design_command="sync", sync_command="status", review_id=review_id, json=True)
    assert run_design_command(status_args, client_factory=lambda: expiring_client, workspace_root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "reviewed"
    assert expiring_client.calls == []


def test_sync_apply_rejects_local_symlink_swap_before_remote_calls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    outside = tmp_path / "outside.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    outside.write_text("<main>outside</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.calls.clear()
    local.unlink()
    local.symlink_to(outside)

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    with pytest.raises(ClaudeDesignSafetyError, match="symlink"):
        run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.calls == []


def test_sync_to_design_applies_reviewed_bytes_once_and_finishes_verified_ledger(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["state"] == "awaiting_verification"
    assert applied["mutated"] is True
    assert applied["open_urls"] == ["https://claude.ai/design/p/project-1"]
    assert applied["verification"] == {
        "verified": True,
        "previews": [
            {
                "path": "Example.dc.html",
                "open_url": "https://claude.ai/design/p/project-1",
                "opened": False,
            }
        ],
    }
    assert client.remote["Example.dc.html"] == ("remote-2", "<main>local</main>\n")
    assert client.write_preflights == 1

    finish_args = Namespace(
        design_command="sync",
        sync_command="finish",
        review_id=review_id,
        json=True,
    )
    assert run_design_command(finish_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    finished = json.loads(capsys.readouterr().out)
    assert finished["state"] == "complete"
    assert finished["mutated"] is False
    assert [name for name, _arguments in client.calls] == [
        "list_files",
        "read_file",
        "list_files",
        "finalize_plan",
        "write_files",
        "read_file",
        "render_preview",
        "list_files",
    ]

    client.calls.clear()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    unchanged = json.loads(capsys.readouterr().out)
    assert unchanged == {
        "state": "in_sync",
        "classification": "unchanged",
        "requires_approval": False,
        "mutated": False,
    }
    assert [name for name, _arguments in client.calls] == ["list_files"]


def test_sync_to_design_open_verifies_the_browser_preview(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    opened: list[str] = []
    monkeypatch.setattr(claude_design, "_open_preview_url", opened.append)

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        open_browser=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    applied = json.loads(capsys.readouterr().out)
    assert opened == ["https://preview.claudeusercontent.com/short-lived"]
    assert applied["verification"]["previews"][0]["opened"] is True


def test_sync_browser_failure_keeps_durable_preview_and_marks_receipt_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)

    def fail_open(_url: str) -> None:
        raise ClaudeDesignSafetyError("synthetic browser open failure")

    monkeypatch.setattr(claude_design, "_open_preview_url", fail_open)
    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        open_browser=True,
        json=True,
    )

    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 2
    applied = json.loads(capsys.readouterr().out)
    assert applied["state"] == "unknown"
    assert applied["verification"]["previews"] == [
        {
            "path": "Example.dc.html",
            "open_url": "https://claude.ai/design/p/project-1",
            "opened": False,
        }
    ]
    assert "browser open failure" in applied["error"]


def test_sync_to_design_supports_approved_remote_file_creation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>new design</main>\n", encoding="utf-8")
    client = SyncStubClient()
    client.remote.clear()
    client.remote["support.js"] = ("support-1", "runtime\n")
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "awaiting_verification"
    assert client.remote["Example.dc.html"] == ("remote-1", "<main>new design</main>\n")


def test_sync_to_design_refuses_dc_creation_without_support_before_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>new design</main>\n", encoding="utf-8")
    client = SyncStubClient()
    client.remote.clear()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.calls.clear()

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    with pytest.raises(ClaudeDesignSafetyError, match="support.js"):
        run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path)

    assert [name for name, _arguments in client.calls] == ["list_files"]
    assert "Example.dc.html" not in client.remote


def test_sync_marks_ambiguous_post_write_failure_unknown_and_status_is_local_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    client.fail_reads = True

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "unknown"
    assert payload["mutated"] is True

    status_args = Namespace(
        design_command="sync",
        sync_command="status",
        review_id=review_id,
        json=True,
    )
    assert (
        run_design_command(
            status_args,
            client_factory=lambda: pytest.fail("sync status must not create a remote client"),
            workspace_root=tmp_path,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "unknown"


def test_sync_to_code_revalidates_code_then_returns_immutable_handoff(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "src" / "Example.tsx"
    local.parent.mkdir()
    local.write_text("export const Example = () => <main>old</main>;\n", encoding="utf-8")
    client = SyncStubClient()
    assert (
        run_design_command(
            _review_args(local, direction="to-code"),
            client_factory=lambda: client,
            workspace_root=tmp_path,
        )
        == 0
    )
    review_id = _receipt_id(capsys)
    client.calls.clear()

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0

    applied = json.loads(capsys.readouterr().out)
    assert applied["state"] == "awaiting_verification"
    assert applied["mutated"] is False
    assert len(applied["handoff_paths"]) == 1
    assert (tmp_path / applied["handoff_paths"][0]).read_text(encoding="utf-8") == "<main>remote</main>\n"
    assert [name for name, _arguments in client.calls] == ["read_file"]
    assert client.calls[0][1]["if_none_match"] == "remote-1"

    local.write_text("export const Example = () => <main>implemented</main>;\n", encoding="utf-8")
    finish_args = Namespace(
        design_command="sync",
        sync_command="finish",
        review_id=review_id,
        json=True,
    )
    assert run_design_command(finish_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "complete"
    assert [name for name, _arguments in client.calls] == ["read_file", "list_files"]


def test_sync_to_code_refuses_remote_deletion_after_approval(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "src" / "Example.tsx"
    local.parent.mkdir()
    local.write_text("export const Example = () => <main>old</main>;\n", encoding="utf-8")
    client = SyncStubClient()
    assert (
        run_design_command(
            _review_args(local, direction="to-code"),
            client_factory=lambda: client,
            workspace_root=tmp_path,
        )
        == 0
    )
    review_id = _receipt_id(capsys)
    del client.remote["Example.dc.html"]

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["changed"] == [{"side": "remote", "path": "Example.dc.html"}]
    assert payload["mutated"] is False


def test_sync_to_code_binds_approved_local_nonexistence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "src" / "NewExample.tsx"
    client = SyncStubClient()
    assert (
        run_design_command(
            _review_args(local, direction="to-code"),
            client_factory=lambda: client,
            workspace_root=tmp_path,
        )
        == 0
    )
    review_id = _receipt_id(capsys)
    local.parent.mkdir()
    local.write_text("export const NewExample = true;\n", encoding="utf-8")
    client.calls.clear()

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] == [{"side": "local", "path": "src/NewExample.tsx"}]
    assert client.calls == []


def test_sync_batch_is_all_or_nothing_when_one_local_path_changes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "Example.dc.html"
    second = tmp_path / "Other.dc.html"
    first.write_text("<main>first</main>\n", encoding="utf-8")
    second.write_text("<main>second</main>\n", encoding="utf-8")
    client = SyncStubClient()
    client.remote["Other.dc.html"] = ("other-1", "<main>remote other</main>\n")
    args = Namespace(
        design_command="sync",
        sync_command="review",
        project_id="project-1",
        direction="to-design",
        pairs=[f"Example.dc.html={first}", f"Other.dc.html={second}"],
        json=True,
    )
    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    second.write_text("<main>changed</main>\n", encoding="utf-8")
    client.calls.clear()

    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] == [{"side": "local", "path": "Other.dc.html"}]
    assert client.calls == []


def test_sync_review_marks_both_changed_for_explicit_reconciliation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()
    finish_args = Namespace(design_command="sync", sync_command="finish", review_id=review_id, json=True)
    assert run_design_command(finish_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()

    local.write_text("<main>new code</main>\n", encoding="utf-8")
    client.remote["Example.dc.html"] = ("remote-3", "<main>new design</main>\n")
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classification"] == "both-changed"
    assert payload["requires_reconciliation"] is True

    conflict_apply = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=payload["review_id"],
        allow_write=True,
        json=True,
    )
    with pytest.raises(ClaudeDesignSafetyError, match="--reconciled"):
        run_design_command(conflict_apply, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.remote["Example.dc.html"] == ("remote-3", "<main>new design</main>\n")

    conflict_apply.reconciled = True
    assert run_design_command(conflict_apply, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert client.remote["Example.dc.html"][1] == "<main>new code</main>\n"


def test_completed_sync_receipt_cannot_be_replayed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>local</main>\n", encoding="utf-8")
    client = SyncStubClient()
    assert run_design_command(_review_args(local), client_factory=lambda: client, workspace_root=tmp_path) == 0
    review_id = _receipt_id(capsys)
    apply_args = Namespace(
        design_command="sync",
        sync_command="apply",
        review_id=review_id,
        allow_write=True,
        json=True,
    )
    assert run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()
    finish_args = Namespace(
        design_command="sync",
        sync_command="finish",
        review_id=review_id,
        json=True,
    )
    assert run_design_command(finish_args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    capsys.readouterr()

    with pytest.raises(ValueError, match="state is complete"):
        run_design_command(apply_args, client_factory=lambda: client, workspace_root=tmp_path)


@pytest.mark.parametrize("direction", ["to-design", "to-code"])
def test_sync_review_records_baseline_for_identical_bytes_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    direction: str,
) -> None:
    local = tmp_path / "Example.dc.html"
    local.write_text("<main>remote</main>\n", encoding="utf-8")
    client = SyncStubClient()

    assert (
        run_design_command(
            _review_args(local, direction=direction), client_factory=lambda: client, workspace_root=tmp_path
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "state": "in_sync",
        "classification": "unchanged",
        "requires_approval": False,
        "mutated": False,
        "baseline_recorded": True,
    }
    assert "write_files" not in [name for name, _arguments in client.calls]
    assert not (tmp_path / ".open-claude-design" / "sync" / "reviews").exists()

    local.write_text("<main>edited locally</main>\n", encoding="utf-8")
    assert (
        run_design_command(
            _review_args(local, direction=direction), client_factory=lambda: client, workspace_root=tmp_path
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["classification"] == "local-only"
