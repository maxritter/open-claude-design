"""Validation tests for Design Component (.dc.html) artboards and references."""

from __future__ import annotations

import pytest

from open_claude_artifacts.validation import validate_html

pytestmark = pytest.mark.unit

VALID_DC = (
    '<!doctype html><html><head><script src="./support.js"></script></head><body>'
    "<x-dc><helmet><style>a{color:#111}a:hover{color:#000}</style></helmet>"
    "<div>Design</div></x-dc>"
    '<script type="text/x-dc" data-dc-script>class Component extends DCLogic { renderVals() { return {}; } }</script>'
    "</body></html>"
)


def test_valid_dc_artboard_passes_structure_and_script_checks() -> None:
    result = validate_html("project/Main.dc.html", VALID_DC.encode(), {"project/support.js"})
    assert result["valid"], result["issues"]
    assert result["dependencies"] == ["project/support.js"]


def test_editor_contract_accepts_lookups_literals_and_rejects_expressions() -> None:
    valid = VALID_DC.replace("<div>Design</div>", "<div>{{ user.name }} {{ 'ok' }} {{ 42 }}</div>")
    assert validate_html("project/Main.dc.html", valid.encode(), {"project/support.js"})["valid"]

    expr = VALID_DC.replace("<div>Design</div>", "<div>{{ a + b }}</div>")
    res = validate_html("project/Main.dc.html", expr.encode(), {"project/support.js"})
    assert not res["valid"]
    assert any("expression" in issue for issue in res["issues"])

    doubled = VALID_DC.replace("<x-dc>", "<x-dc><Capitalized/>")
    assert not validate_html("project/Main.dc.html", doubled.encode())["valid"]


@pytest.mark.parametrize(
    "body",
    [
        '<img src="/_blob/0123abcdef4567" alt="">',
        '<link rel="stylesheet" href="/_blob/9f8e7d6c5b4a">',
        '<img src="{{ thumb }}" alt="">',
        '<img src="{{palImg}}" alt="">',
        '<img src="captures/{{ shot.file }}" alt="">',
        '<img src="{{ \'https://example.com/image.png?size=small\' }}" alt="">',
        '<img src="{{ \'still.png#frame\' }}" alt="">',
        '<img src="captures/{{ shot.file }}?v=2" alt="">',
    ],
)
def test_uploaded_assets_and_bound_sources_are_not_project_files(body: str) -> None:
    # PR #20: Claude Design's artboards reference uploads as /_blob/<id> and bind sources in renderVals().
    result = validate_html(
        "project/Main.dc.html", VALID_DC.replace("<div>Design</div>", body).encode(), {"project/support.js"}
    )
    assert result["valid"], result["issues"]
    assert result["dependencies"] == ["project/support.js"]


def test_a_bound_source_on_a_root_artboard_is_not_an_escape() -> None:
    result = validate_html(
        "page.dc.html", VALID_DC.replace("<div>Design</div>", '<img src="{{ thumb }}" alt="">').encode(), {"support.js"}
    )
    assert result["valid"], result["issues"]


@pytest.mark.parametrize(
    ("body", "issue"),
    [
        ('<img src="/_blob/../canvas.json" alt="">', "escapes the project"),
        ('<img src="/_blob/" alt="">', "escapes the project"),
        ('<img src="/etc/passwd" alt="">', "escapes the project"),
        ('<img src="../../{{ thumb }}" alt="">', "escapes the project"),
        ('<img src="missing.png" alt="">', "Missing project resource: project/missing.png"),
        ('<img src="missing.png?v={{ version }}" alt="">', "Missing project resource: project/missing.png"),
        ('<img src="../../{{ \'a?b\' }}" alt="">', "escapes the project"),
    ],
)
def test_blob_and_template_exemptions_keep_escape_and_missing_file_checks(body: str, issue: str) -> None:
    result = validate_html(
        "project/Main.dc.html", VALID_DC.replace("<div>Design</div>", body).encode(), {"project/support.js"}
    )
    assert not result["valid"]
    assert any(issue in found for found in result["issues"]), result["issues"]


def test_editor_advice_warns_without_blocking_and_reports_user_edits() -> None:
    body = (
        '<deck-stage width="1280" height="720"><sc-for list="{{ slides }}" as="s"><section></section></sc-for>'
        '</deck-stage><style id="__om-edit-overrides">.a{color:red}</style><div data-comment-anchor="c1"></div>'
    )
    result = validate_html(
        "project/Main.dc.html", VALID_DC.replace("<div>Design</div>", body).encode(), {"project/support.js"}
    )
    assert result["valid"]
    assert result["editor_overrides"] is True
    assert result["comment_anchors"] == 1
    assert any("deck-stage" in w for w in result["warnings"])
