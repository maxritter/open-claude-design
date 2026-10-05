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


@pytest.mark.parametrize(
    ("body", "issue"),
    [
        ("<div>{{ count + 1 }}</div>", "Template hole {{ count + 1 }} is an expression"),
        ('<div title="{{ a ? b : c }}"></div>', "Template hole {{ a ? b : c }} is an expression"),
        ('<Card item="{{ it }}"></Card>', "Capitalized tag <Card>"),
        ("<ul><li>One<li>Two</ul>", "Element <li> is closed implicitly"),
        ("<div><p>Unclosed</div>", "Element <p> is closed implicitly"),
    ],
)
def test_editor_contract_violations_block_a_design_component(body: str, issue: str) -> None:
    result = validate_html("page.dc.html", VALID_DC.replace("<div>Design</div>", body).encode())

    assert not result["valid"]
    assert any(issue in found for found in result["issues"])


def test_editor_contract_accepts_lookups_literals_and_what_claude_design_writes() -> None:
    body = (
        "<div class=\"{{ item.tone }}\">{{ $index }} {{ true }} {{ 3 }} {{ 'x' }}</div>"
        '<svg viewBox="0 0 4 4"><path d="M0 0h4"/><line x1="0" y1="0" x2="4" y2="4"/></svg>'
        '<dc-import name="SiteFooter" hint-size="100%,320px"></dc-import>'
    )
    styled = VALID_DC.replace("<helmet></helmet>", "<helmet><style>a{color:#111}a:hover{color:#333}</style></helmet>")
    result = validate_html("page.dc.html", styled.replace("<div>Design</div>", body).encode())
    assert result["valid"], result["issues"]
    assert result["warnings"] == []

    # Static pages without logic, and logic marked type="text/plain", are both Claude Design's own output.
    static = '<script src="./support.js"></script><x-dc><helmet></helmet><main>Static</main></x-dc>'
    assert validate_html("page.dc.html", static.encode())["valid"]
    plain = VALID_DC.replace('type="text/x-dc"', 'type="text/plain"')
    assert validate_html("page.dc.html", plain.encode())["valid"]
    doubled = VALID_DC + '<script type="text/x-dc" data-dc-script>class Component extends DCLogic {}</script>'
    assert not validate_html("page.dc.html", doubled.encode())["valid"]


def test_editor_advice_warns_without_blocking_and_reports_user_edits() -> None:
    body = (
        '<deck-stage width="1280" height="720"><sc-for list="{{ slides }}" as="s"><section></section></sc-for>'
        '</deck-stage><div data-comment-anchor="c1">Pinned</div>'
    )
    source = VALID_DC.replace("<helmet></helmet>", '<helmet><style id="__om-edit-overrides">.x{}</style></helmet>')
    source = source.replace("<div>Design</div>", body).replace("return {};", "window.scrollIntoView; return {};")
    result = validate_html("page.dc.html", source.encode())

    assert result["valid"], result["issues"]
    assert result["editor_overrides"] is True
    assert result["comment_anchors"] == 1
    warnings = " ".join(result["warnings"])
    assert "direct child of <deck-stage>" in warnings
    assert "scrollIntoView" in warnings
    assert "a:hover" in warnings


class Inventory:
    """A project whose list_files inventory is fixed; any other call is a failure."""

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        assert name == "list_files", "project pages must stay read-only"
        return {
            "structuredContent": [
                {"path": path, "type": "file", "etag": f"etag-{index}", "size": 1}
                for index, path in enumerate(self.paths)
            ]
        }


def _pages_check(client: Inventory, tmp_path: Path) -> int:
    args = build_parser().parse_args(["project", "pages", "p", "--json"])
    return run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)


def test_project_pages_passes_when_every_page_is_at_the_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Inventory(["Home.dc.html", "About.html", "support.js", "assets/logo.svg", "assets/fonts/a.woff2"])

    code = _pages_check(client, tmp_path)

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report == {
        "project_id": "p",
        "ok": True,
        "listed_pages": ["About.html", "Home.dc.html"],
        "nested_pages": [],
        "root_support_js": True,
    }
    assert [name for name, _arguments in client.calls] == ["list_files"]
    assert client.calls[0][1] == {"project_id": "p", "path": "", "depth": -1}


def test_project_pages_lists_nested_pages_with_the_root_path_to_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Inventory(
        [
            "website/QualityLayer Website v8.dc.html",
            "website/support.js",
            "website/assets/hero.png",
            "Home.dc.html",
            "other/Home.dc.html",
            "partials/nav.html",
        ]
    )

    code = _pages_check(client, tmp_path)

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["ok"] is False
    assert report["listed_pages"] == ["Home.dc.html"]
    assert report["root_support_js"] is False
    assert report["nested_pages"] == [
        {"path": "other/Home.dc.html", "suggested_root_path": "other-Home.dc.html", "root_path_taken": True},
        {"path": "partials/nav.html", "suggested_root_path": "nav.html", "root_path_taken": False},
        {
            "path": "website/QualityLayer Website v8.dc.html",
            "suggested_root_path": "QualityLayer Website v8.dc.html",
            "root_path_taken": False,
        },
    ]
    assert "Pages menu lists only" in report["guidance"]
    assert "support.js at the project root" in report["guidance"]
    assert [name for name, _arguments in client.calls] == ["list_files"]


def test_project_pages_reports_a_project_without_pages_as_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Inventory(["styles.css", "assets/logo.svg"])

    code = _pages_check(client, tmp_path)

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["listed_pages"] == [] and report["nested_pages"] == []


class ProjectStub:
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls: list[str] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(name)
        assert name == "get_project", "the live window must stay read-only"
        return {"structuredContent": {"id": arguments["project_id"], "url": self.url}}


def test_project_live_appends_embed_to_the_url_claude_design_returned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import open_claude_design.bridge as bridge_module

    opened: list[str] = []
    monkeypatch.setattr(bridge_module, "_open_preview_url", opened.append)
    client = ProjectStub("https://claude.ai/design/p/p?embed=0")
    args = build_parser().parse_args(["project", "live", "p", "--open", "--json"])

    assert run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"project_id": "p", "live_url": "https://claude.ai/design/p/p?embed=1", "opened": True}
    assert opened == ["https://claude.ai/design/p/p?embed=1"]
    assert client.calls == ["get_project"]


def test_project_live_refuses_a_url_outside_claude_ai(tmp_path: Path) -> None:
    args = build_parser().parse_args(["project", "live", "p", "--json"])
    client = ProjectStub("https://claude.ai.attacker.example/design/p/p")

    with pytest.raises(ClaudeDesignProtocolError, match="durable preview URL"):
        run_design_command(args, client_factory=lambda: client, workspace_root=tmp_path)
