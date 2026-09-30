"""Regression tests for incomplete reads/copies and API-only workflows."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from open_claude_design.api import RemoteFile
from open_claude_design.bridge import (
    _decode_read_file_result,
    _planned_call_payload,
    _tool_exit_code,
    build_parser,
    run_design_command,
)
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.validation import validate_html

pytestmark = pytest.mark.unit

VALID_DC = (
    '<script src="./support.js"></script><x-dc><helmet></helmet><div>Design</div></x-dc>'
    '<script type="text/x-dc" data-dc-script>'
    "class Component extends DCLogic { renderVals() { return {}; } }</script>"
)


@pytest.mark.parametrize(
    "attributes",
    ['lines="1-2" total_lines="10"', 'lines="2-10" total_lines="10"', 'lines="1-1" total_lines="1" truncated_line="1"'],
)
def test_incomplete_wrapper_is_never_a_full_file(attributes: str) -> None:
    result = {
        "content": [
            {
                "type": "text",
                "text": f'<untrusted-project-content etag="e" {attributes}>\npartial\n</untrusted-project-content>',
            }
        ]
    }
    with pytest.raises(ClaudeDesignProtocolError, match="part of the file"):
        _decode_read_file_result(result)


class Files:
    def __init__(self) -> None:
        self.files = {"a.txt": b"text\n" * 60000, "assets/font.woff2": b"\x00\xfffont"}
        self.calls: list[str] = []
        self.changed = False

    def read_raw_file(self, project_id: str, path: str) -> RemoteFile:
        self.calls.append("raw")
        return RemoteFile(self.files[path], "1", "application/octet-stream", path.endswith(".woff2"))

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(name)
        if name == "list_files":
            if arguments.get("path") == "source":
                return {
                    "structuredContent": [
                        {"path": "source/a", "type": "file", "etag": "1"},
                        {"path": "source/b", "type": "file", "etag": "1"},
                    ]
                }
            return {
                "structuredContent": [
                    {
                        "path": path,
                        "type": "file",
                        "etag": "2" if self.changed and self.calls.count(name) > 1 else "1",
                        "size": len(data),
                    }
                    for path, data in self.files.items()
                ]
            }
        if name == "finalize_plan":
            return {"structuredContent": {"plan_token": "mock-value", "base_etags": {}}}
        raise AssertionError(name)


def test_partial_folder_guard_is_rejected_before_plan_or_copy() -> None:
    client = Files()
    args = build_parser().parse_args(
        [
            "planned-call",
            "copy_files",
            "p",
            "--args",
            '{"files":[{"src":"source","dest":"target","leaf_if_match":{"target/a":"0"}}]}',
            "--write",
            "target",
            "--allow-write",
            "--allow-destructive",
        ]
    )
    with pytest.raises(ClaudeDesignSafetyError, match="every source leaf"):
        _planned_call_payload(args, client)
    assert client.calls == ["list_files"]


def test_nested_copy_conflict_and_omitted_leaves_cannot_report_success() -> None:
    arguments = {
        "project_id": "p",
        "files": [{"src": "source", "dest": "target", "leaf_if_match": {"target/a": "0", "target/b": "0"}}],
    }
    result = {"structuredContent": {"copied": 1, "results": [{"status": "conflict"}], "etags": {"target/a": "2"}}}
    assert _tool_exit_code(result, tool="copy_files", mutation=True, arguments=arguments) == 2
    result["structuredContent"]["results"] = [{"status": "completed"}]
    assert _tool_exit_code(result, tool="copy_files", mutation=True, arguments=arguments) == 2


def test_raw_pull_supports_large_text_and_binary_without_printing_the_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Files()
    for path in client.files:
        target = tmp_path / Path(path).name
        args = build_parser().parse_args(["pull", "p", path, "--output", str(target), "--json"])
        assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
        assert target.read_bytes() == client.files[path]
    output = capsys.readouterr().out
    assert "text\\n" not in output and "font\\n" not in output


def test_zip_export_preserves_all_bytes_and_records_their_revisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Files()
    target = tmp_path / "project.zip"
    args = build_parser().parse_args(["export", "p", "--output", str(target), "--json"])
    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    with zipfile.ZipFile(target) as archive:
        assert archive.read("a.txt") == client.files["a.txt"]
        assert archive.read("assets/font.woff2") == client.files["assets/font.woff2"]
        manifest = json.loads(archive.read("__open_claude_design_export__/manifest.json"))
        assert len(manifest["files"]) == 2
        assert {entry["etag"] for entry in manifest["files"]} == {"1"}
    assert json.loads(capsys.readouterr().out)["verified"]


def test_zip_export_saves_nothing_when_a_file_changes(tmp_path: Path) -> None:
    client = Files()
    client.changed = True
    target = tmp_path / "project.zip"
    args = build_parser().parse_args(["export", "p", "--output", str(target), "--json"])
    with pytest.raises(ClaudeDesignSafetyError, match="changed during export"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
    assert not target.exists()


def test_zip_export_rejects_out_of_scope_paths(tmp_path: Path) -> None:
    client = Files()
    client.files = {"../escape": b"content"}
    args = build_parser().parse_args(["export", "p", "--output", str(tmp_path / "project.zip"), "--json"])
    with pytest.raises(ValueError):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.calls == ["list_files"]


class Batch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_tools(self) -> list[dict[str, Any]]:
        self.calls.append("catalog")
        return [{"name": "get_project", "annotations": {"readOnlyHint": True}}]

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(name)
        return {"structuredContent": {"id": arguments["project_id"]}}


def test_batch_validates_all_calls_before_executing_any(tmp_path: Path) -> None:
    client = Batch()
    args = build_parser().parse_args(
        [
            "batch",
            "--args",
            '{"calls":[{"tool":"get_project","args":{"project_id":"p"}},{"tool":"delete_files"}]}',
            "--json",
        ]
    )
    with pytest.raises(ClaudeDesignSafetyError):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
    assert client.calls == []


def test_batch_uses_one_catalog_and_keeps_call_order(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = Batch()
    args = build_parser().parse_args(
        [
            "batch",
            "--args",
            '{"calls":[{"tool":"get_project","args":{"project_id":"p"}},{"tool":"get_project","args":{"project_id":"q"}}]}',
            "--json",
        ]
    )
    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    assert client.calls == ["catalog", "get_project", "get_project"]
    assert json.loads(capsys.readouterr().out)["complete"]


def test_plain_html_cannot_masquerade_as_an_editable_design_component() -> None:
    assert not validate_html("page.dc.html", b"<html><body><h1>Hello</h1></body></html>")["valid"]
    result = validate_html("page.dc.html", VALID_DC.encode(), {"support.js"})
    assert result["valid"]
    assert result["render_executed"] is False


def test_structural_checks_catch_missing_dependencies_and_self_closing_components() -> None:
    assert not validate_html("page.dc.html", VALID_DC.encode(), set())["valid"]
    assert not validate_html(
        "page.dc.html", VALID_DC.replace("<div>Design</div>", '<dc-import name="Child"/>').encode()
    )["valid"]
