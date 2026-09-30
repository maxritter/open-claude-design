"""Portable structural validation; never launches or controls a browser."""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


class DesignHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.dc_count = 0
        self.logic_count = 0
        self.support = False
        self.references: list[str] = []
        self.issues: list[str] = []
        self.logic_scripts: list[str] = []
        self._logic_script = False
        self._dc_depth = 0
        self._helmet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "x-dc":
            self.dc_count += 1
            self._dc_depth += 1
        if tag == "helmet":
            self._helmet_depth += 1
        if tag == "script":
            source = values.get("src", "") or ""
            if source in {"support.js", "./support.js"}:
                self.support = True
            if values.get("type") == "text/x-dc" and "data-dc-script" in values:
                self.logic_count += 1
                self._logic_script = True
                self.logic_scripts.append("")
            if self._dc_depth and not self._helmet_depth:
                self.issues.append("Scripts inside x-dc must be placed inside helmet.")
        for attribute in ("src", "href", "poster"):
            value = values.get(attribute)
            if value and not (tag == "a" and attribute == "href"):
                self.references.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._logic_script = False
        if tag == "x-dc":
            self._dc_depth = max(0, self._dc_depth - 1)
        if tag == "helmet":
            self._helmet_depth = max(0, self._helmet_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._logic_script:
            self.logic_scripts[-1] += data

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.issues.append(f"Non-void element {tag} must have an explicit closing tag.")
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def project_reference(path: str, reference: str) -> str | None:
    """Resolve an asset reference within its project; never follow external URLs."""
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or not parsed.path or reference.startswith("#"):
        return None
    raw = unquote(parsed.path)
    if "\\" in raw or "\x00" in raw:
        raise ValueError("An asset reference has an unsafe path.")
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), raw))
    if raw.startswith("/") or joined in {".", ".."} or joined.startswith("../"):
        raise ValueError("An asset reference escapes the project.")
    return joined


def validate_html(path: str, data: bytes, available: set[str] | None = None) -> dict[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return {"valid": False, "checks": "structure", "render_executed": False, "issues": ["HTML must be UTF-8 text."]}
    parser = DesignHTML()
    parser.feed(text)
    issues = list(parser.issues)
    syntax = "not-applicable"
    if parser.logic_scripts:
        from open_claude_design.installer import InstallError, resolve_skills_runtime

        try:
            node = resolve_skills_runtime().node
        except InstallError:
            syntax = "unavailable"
        else:
            syntax = "passed"
            environment = os.environ.copy()
            environment.pop("NODE_OPTIONS", None)
            for script in parser.logic_scripts:
                try:
                    result = subprocess.run(
                        [str(node), "--check"],
                        input=script.encode(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=environment,
                        timeout=10,
                        shell=False,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    syntax = "unavailable"
                    break
                if result.returncode != 0:
                    issues.append("The Design Component logic script has invalid JavaScript syntax.")
                    syntax = "failed"
    if parser._dc_depth or parser._helmet_depth:
        issues.append("A Design Component has an unclosed template or helmet element.")
    if not text.strip():
        issues.append("HTML is empty.")
    if path.endswith(".dc.html"):
        if parser.dc_count != 1:
            issues.append("A Design Component requires exactly one x-dc template.")
        if parser.logic_count != 1 or not re.search(r"class\s+Component\s+extends\s+DCLogic\b", text):
            issues.append("A Design Component requires its Component extends DCLogic logic script.")
        if not parser.support:
            issues.append("A Design Component must load ./support.js from its own directory.")
    dependencies: set[str] = set()
    for reference in parser.references:
        try:
            resolved = project_reference(path, reference)
        except ValueError as error:
            issues.append(str(error))
            continue
        if resolved:
            dependencies.add(resolved)
            if available is not None and resolved not in available:
                issues.append(f"Missing project resource: {resolved}")
    return {
        "valid": not issues,
        "checks": "structure-and-resources" if available is not None else "structure",
        "render_executed": False,
        "javascript_syntax": syntax,
        "issues": list(dict.fromkeys(issues)),
        "dependencies": sorted(dependencies),
    }
