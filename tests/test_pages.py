"""Claude Design lists only root-level pages in its Pages menu; these rules guard every write."""

from __future__ import annotations

import pytest

from open_claude_design.bridge import build_parser
from open_claude_design.pages import (
    ALLOW_NESTED_PAGE_FLAG,
    is_page_path,
    nested_page_message,
    nested_pages,
    page_listed,
    root_page_suggestions,
    write_target_paths,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "page", "listed"),
    [
        ("Home.dc.html", True, True),
        ("Home.html", True, True),
        ("Home.HTML", True, True),
        ("website/Home.dc.html", True, False),
        ("a/b/Home.html", True, False),
        ("support.js", False, False),
        ("assets/logo.svg", False, False),
        ("docs/notes.htm", False, False),
        ("styles.css", False, False),
    ],
)
def test_only_root_level_html_is_a_listed_page(path: str, page: bool, listed: bool) -> None:
    assert is_page_path(path) is page
    assert page_listed(path) is listed


def test_nested_pages_are_sorted_unique_and_exclude_assets_and_root_pages() -> None:
    paths = ["b/Two.dc.html", "Home.dc.html", "a/One.html", "b/Two.dc.html", "a/app.js", "a/logo.png"]

    assert nested_pages(paths) == ["a/One.html", "b/Two.dc.html"]


def test_root_suggestion_is_the_file_name() -> None:
    assert root_page_suggestions(["website/QualityLayer Website v8.dc.html"]) == {
        "website/QualityLayer Website v8.dc.html": "QualityLayer Website v8.dc.html"
    }


def test_root_suggestion_never_overwrites_an_existing_or_sibling_page() -> None:
    suggestions = root_page_suggestions(
        ["a/Home.dc.html", "b/Home.dc.html", "c/Home.dc.html", "x/About.dc.html"],
        taken={"Home.dc.html", "a-Home.dc.html"},
    )

    assert suggestions == {
        "a/Home.dc.html": "a-Home-2.dc.html",
        "b/Home.dc.html": "b-Home.dc.html",
        "c/Home.dc.html": "c-Home.dc.html",
        "x/About.dc.html": "About.dc.html",
    }
    assert len(set(suggestions.values())) == len(suggestions)


def test_message_explains_the_rule_the_fix_and_truncates_long_lists() -> None:
    paths = [f"folder/Page {index:02d}.dc.html" for index in range(12)]

    message = nested_page_message(paths)

    assert "Pages menu lists only .html and .dc.html files at the project root" in message
    assert "keep assets" in message
    assert "folder/Page 00.dc.html -> Page 00.dc.html" in message
    assert "and 4 more" in message
    assert "Page 11" not in message


def test_write_targets_cover_paths_destinations_leaves_and_never_deletions() -> None:
    arguments: dict[str, object] = {
        "project_id": "p",
        "path": "one/A.html",
        "writes": ["two/B.html"],
        "deletes": ["gone/C.html"],
        "files": [
            {"src": "s", "dest": "three/D.html", "if_match": "0"},
            {"src": "t", "dest": "dir", "leaf_if_match": {"dir/E.html": "0"}},
            {"path": "four/F.html"},
            "five/G.html",
            3,
        ],
    }

    assert write_target_paths(arguments) == [
        "dir",
        "dir/E.html",
        "five/G.html",
        "four/F.html",
        "one/A.html",
        "three/D.html",
        "two/B.html",
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["push", "p", "--file", "A.html=a", "--if-match", "A.html=0"],
        ["planned-call", "copy_files", "p", "--write", "A.html"],
        ["call", "some_tool"],
        ["sync", "review", "p", "--direction", "to-design", "--pair", "A.html=a"],
        ["sync", "apply", "review-id"],
    ],
)
def test_every_write_command_has_the_explicit_opt_out_and_refuses_by_default(argv: list[str]) -> None:
    parser = build_parser()

    assert parser.parse_args(argv).allow_nested_page is False
    assert parser.parse_args([*argv, ALLOW_NESTED_PAGE_FLAG]).allow_nested_page is True
