"""Portable structural validation; never launches or controls a browser."""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
# Claude Design's template holes are dotted lookups or literals; anything else fails silently at render.
TEMPLATE_HOLE = re.compile(r"\{\{(.*?)\}\}", re.S)
LOOKUP_OR_LITERAL = re.compile(
    r"\s*(?:\$?[A-Za-z_][\w$]*(?:\.[\w$]+)*|true|false|null|-?\d+(?:\.\d+)?|'[^'{}]*'|\"[^\"{}]*\")\s*"
)
STAGE_UNSAFE_CHILDREN = frozenset({"sc-if", "sc-for", "sc-else", "dc-import", "x-import"})
LINK_RULE = re.compile(r"(?:^|[\s,}>])a\s*[{,]")
LINK_HOVER_RULE = re.compile(r"(?:^|[\s,}>])a:hover\b")


class DesignHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.dc_count = 0
        self.logic_count = 0
        self.support = False
        self.references: list[str] = []
        self.issues: list[str] = []
        self.warnings: list[str] = []
        self.logic_scripts: list[str] = []
        self.helmet_css = ""
        self.editor_overrides = False
        self.comment_anchors = 0
        self._logic_script = False
        self._raw_text = ""
        self._dc_depth = 0
        self._helmet_depth = 0
        self._svg_depth = 0
        # Open elements inside the x-dc template, to find any closed implicitly.
        self._template: list[str] = []

    def _check_holes(self, text: str) -> None:
        for match in TEMPLATE_HOLE.finditer(text):
            if not LOOKUP_OR_LITERAL.fullmatch(match.group(1)):
                self.issues.append(
                    f"Template hole {match.group(0)[:60]} is an expression; compute it in renderVals() "
                    "and reference it by name."
                )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "x-dc":
            self.dc_count += 1
            self._dc_depth += 1
        if tag == "helmet":
            self._helmet_depth += 1
        if tag == "svg":
            self._svg_depth += 1
        if tag in {"script", "style"}:
            self._raw_text = tag
        if tag == "style" and values.get("id") == "__om-edit-overrides":
            self.editor_overrides = True
        if "data-comment-anchor" in values:
            self.comment_anchors += 1
        if tag == "script":
            source = values.get("src", "") or ""
            if source in {"support.js", "./support.js"}:
                self.support = True
            # The runtime selects the logic script by attribute; Claude Design itself also writes type="text/plain".
            if "data-dc-script" in values:
                self.logic_count += 1
                self._logic_script = True
                self.logic_scripts.append("")
            if self._dc_depth and not self._helmet_depth:
                self.issues.append("Scripts inside x-dc must be placed inside helmet.")
        if self._dc_depth:
            raw_name = re.match(r"<\s*([^\s/>]+)", self.get_starttag_text() or "")
            if raw_name and raw_name.group(1)[:1].isupper():
                self.issues.append(
                    f'Capitalized tag <{raw_name.group(1)}> is not a component; use <dc-import name="'
                    f'{raw_name.group(1)}"></dc-import>.'
                )
            if self._template and self._template[-1] == "deck-stage" and tag in STAGE_UNSAFE_CHILDREN:
                self.warnings.append(
                    f"<{tag}> is a direct child of <deck-stage>; keep every stage child a plain slide element "
                    "so the notes panel and thumbnails match the rendered slides."
                )
            for value in values.values():
                if value:
                    self._check_holes(value)
            if tag not in VOID_ELEMENTS:
                self._template.append(tag)
        for attribute in ("src", "href", "poster"):
            value = values.get(attribute)
            if value and not (tag == "a" and attribute == "href"):
                self.references.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._logic_script = False
        if tag == self._raw_text:
            self._raw_text = ""
        if tag in self._template:
            while self._template:
                open_tag = self._template.pop()
                if open_tag == tag:
                    break
                self.issues.append(f"Element <{open_tag}> is closed implicitly; write its </{open_tag}> explicitly.")
        if tag == "x-dc":
            self._dc_depth = max(0, self._dc_depth - 1)
        if tag == "helmet":
            self._helmet_depth = max(0, self._helmet_depth - 1)
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._logic_script:
            self.logic_scripts[-1] += data
        if self._raw_text == "style" and self._helmet_depth:
            self.helmet_css += data
        if self._dc_depth and not self._raw_text:
            self._check_holes(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # SVG is foreign content where <path/> is well-formed; Claude Design's own templates write it.
        if tag not in VOID_ELEMENTS and not self._svg_depth:
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
        return {
            "valid": False,
            "checks": "structure",
            "render_executed": False,
            "issues": ["HTML must be UTF-8 text."],
            "warnings": [],
        }
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
    warnings = list(parser.warnings)
    if "scrollIntoView" in text:
        warnings.append("scrollIntoView can move the Claude Design app itself; use the scroll container's scrollTo.")
    if path.endswith(".dc.html"):
        if parser.dc_count != 1:
            issues.append("A Design Component requires exactly one x-dc template.")
        # A static page needs no logic script; Claude Design writes such pages itself.
        if parser.logic_count > 1 or (
            parser.logic_count == 1 and not re.search(r"class\s+Component\s+extends\s+DCLogic\b", text)
        ):
            issues.append("A Design Component takes at most one logic script, defining Component extends DCLogic.")
        if not parser.support:
            issues.append("A Design Component must load ./support.js from its own directory.")
        if not (LINK_RULE.search(parser.helmet_css) and LINK_HOVER_RULE.search(parser.helmet_css)):
            warnings.append(
                "Define a and a:hover colors in the helmet style; links added later in the editor "
                "otherwise render browser-default blue."
            )
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
        "warnings": list(dict.fromkeys(warnings)),
        "editor_overrides": parser.editor_overrides,
        "comment_anchors": parser.comment_anchors,
        "dependencies": sorted(dependencies),
    }
