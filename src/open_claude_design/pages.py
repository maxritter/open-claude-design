"""Claude Design page-listing rules shared by every write path and the project check.

Claude Design's editor builds its Pages menu from the `.html` and `.dc.html` files at the
project root only. A page written under a folder still renders by direct `?file=` link, so
readback and a durable preview both succeed, but the user opens the project to an empty
Pages menu and a blank canvas. The helpers here keep that distinction in one place.
"""

from __future__ import annotations

from collections.abc import Iterable

from open_claude_design.config import CLAUDE_DESIGN_MAX_NESTED_PAGE_EXAMPLES, CLAUDE_DESIGN_PAGE_SUFFIX

ALLOW_NESTED_PAGE_FLAG = "--allow-nested-page"


def is_page_path(path: str) -> bool:
    """Return whether a project path is a renderable page (`.html` or `.dc.html`)."""
    return path.lower().endswith(CLAUDE_DESIGN_PAGE_SUFFIX)


def page_listed(path: str) -> bool:
    """Return whether the editor's Pages menu lists this path: a page at the project root."""
    return is_page_path(path) and "/" not in path


def nested_pages(paths: Iterable[str]) -> list[str]:
    """Return the pages among `paths` that sit below the project root, sorted and unique."""
    return sorted({path for path in paths if is_page_path(path) and "/" in path})


def root_page_suggestions(paths: Iterable[str], *, taken: Iterable[str] = ()) -> dict[str, str]:
    """Map each nested page to the root path that would list it.

    The root path is the file name. When that name is already used at the root, or another
    nested page needs the same name, the folder names are folded in so no page overwrites
    another.
    """
    occupied = set(taken)
    suggestions: dict[str, str] = {}
    for path in nested_pages(paths):
        *folders, name = path.split("/")
        candidate = name
        if candidate in occupied:
            candidate = "-".join([*folders, name])
        suffix = 2
        while candidate in occupied:
            stem, dot, extension = name.partition(".")
            candidate = f"{'-'.join([*folders, stem])}-{suffix}{dot}{extension}"
            suffix += 1
        occupied.add(candidate)
        suggestions[path] = candidate
    return suggestions


def nested_page_guidance() -> str:
    """Return the standing explanation and fix for a nested page."""
    return (
        "Claude Design's Pages menu lists only .html and .dc.html files at the project root. A page under a "
        "folder renders by direct link but never appears in the Pages menu, so the user opens an empty project. "
        "Write every page at the project root and keep assets (images, fonts, scripts, styles) in subfolders "
        "referenced by relative paths."
    )


def nested_page_message(paths: Iterable[str], *, taken: Iterable[str] = ()) -> str:
    """Describe nested pages with the root path each should use."""
    suggestions = root_page_suggestions(paths, taken=taken)
    shown = list(suggestions.items())[:CLAUDE_DESIGN_MAX_NESTED_PAGE_EXAMPLES]
    listing = ", ".join(f"{path} -> {root}" for path, root in shown)
    if len(suggestions) > len(shown):
        listing += f", and {len(suggestions) - len(shown)} more"
    return f"{nested_page_guidance()} Nested page(s) and their root path: {listing}."


def write_target_paths(arguments: dict[str, object]) -> list[str]:
    """Collect the destination paths a generic mutating tool call would write.

    Deletion paths are deliberately excluded: removing a nested page never hides one.
    """
    targets: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, str):
            targets.add(value)
        elif isinstance(value, list):
            targets.update(item for item in value if isinstance(item, str))

    for key in ("path", "dest", "paths", "writes"):
        add(arguments.get(key))
    files = arguments.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, str):
                targets.add(item)
            elif isinstance(item, dict):
                add(item.get("path"))
                add(item.get("dest"))
                leaves = item.get("leaf_if_match")
                if isinstance(leaves, dict):
                    add(list(leaves))
    return sorted(targets)
