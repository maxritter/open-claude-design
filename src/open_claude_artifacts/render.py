"""Local headless rendering of Design artboards, Slides decks, and plain artifact pages."""

from __future__ import annotations

import glob
import html as html_lib
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from open_claude_artifacts.api import ArtifactClient, ArtifactSnapshot, content_type_for, file_path
from open_claude_artifacts.config import (
    ARTIFACT_FILE_KINDS,
    ARTIFACT_MAX_ASSET_BYTES,
    ARTIFACT_MAX_FILE_BYTES,
    ARTIFACT_RENDER_ALLOWED_HOSTS,
    ARTIFACT_RENDER_BROWSER_ENV,
    ARTIFACT_RENDER_BROWSERS,
    ARTIFACT_RENDER_DEFAULT_HEIGHT,
    ARTIFACT_RENDER_MAX_HEIGHT,
    ARTIFACT_RENDER_MAX_WIDTHS,
    ARTIFACT_RENDER_PARTS,
    ARTIFACT_RENDER_RUNTIME_PATH,
    ARTIFACT_RENDER_SETTLE_MS,
    ARTIFACT_RENDER_THEMES,
    ARTIFACT_RENDER_TIMEOUT_SECONDS,
    LEGACY_RENDER_BROWSER_ENV,
)
from open_claude_artifacts.errors import ArtifactProtocolError, ArtifactSafetyError
from open_claude_artifacts.store import ASSET_ID

VIEWPORT = "__oca_viewport"
SLIDE_VIEW = "__oca_slide"
CONSOLE = re.compile(r":(INFO|WARNING|ERROR):CONSOLE(?:\(\d+\))?\] \"(.*)\", source: (\S*) \((\d+)\)")
SLIDE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Base CSS matching Anthropic's Slides viewer.md specification, plus instant settlement of arrival animations.
_SLIDES_BASE_CSS = """
* { margin: 0; }
body { font: 32px/1.2 sans-serif; background: #000; overflow: hidden; }
body > section {
  width: __W__px !important; height: __H__px !important;
  overflow: hidden !important; box-sizing: border-box !important;
  position: relative; isolation: isolate;
}
section[hidden], aside, noscript { display: none !important; }
h1 { font-size: 96px; font-weight: 600; }
h2 { font-size: 64px; font-weight: 600; }
h3 { font-size: 44px; font-weight: 600; }
p, li, h1, h2, h3, td, th { overflow-wrap: break-word; text-wrap: pretty; }
table { width: 100%; border-collapse: separate; border-spacing: 0; border: solid #0003; border-width: 2px 0 0 2px; }
th, td { padding: .35em .6em; text-align: left; border: solid #0003; border-width: 0 2px 2px 0; }
x-shape, x-icon, x-embed { display: block; }
x-embed { background: #8884 !important; }
*, *::before, *::after {
  animation-delay: 0s !important; animation-duration: 0.001s !important;
  transition-duration: 0s !important;
}
"""


def _playwright_browser_candidates() -> list[str]:
    home = Path.home()
    mac_testing = (
        "Library/Caches/ms-playwright/chromium-*/chrome-mac*/"
        "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    )
    patterns = [
        str(home / mac_testing),
        str(home / "Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        str(home / ".cache/ms-playwright/chromium-*/chrome-linux/chrome"),
        str(home / ".cache/ms-playwright/chromium-*/chrome-linux64/chrome"),
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(sorted(glob.glob(pattern), reverse=True))
    return found


def find_browser() -> str | None:
    for env_name in (ARTIFACT_RENDER_BROWSER_ENV, LEGACY_RENDER_BROWSER_ENV):
        override = os.environ.get(env_name)
        if override:
            return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    for candidate in (*ARTIFACT_RENDER_BROWSERS, *_playwright_browser_candidates()):
        if candidate.startswith("/"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        elif found := shutil.which(candidate):
            return found
    return None


def _sniff_content_type(path: str, data: bytes) -> str:
    known = content_type_for(path)
    if known:
        return known
    stripped = data.lstrip()
    if stripped.startswith((b"<svg", b"<?xml")):
        return "image/svg+xml"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"wOF2"):
        return "font/woff2"
    if data.startswith(b"wOFF"):
        return "font/woff"
    if data.startswith((b"\x00\x01\x00\x00", b"OTTO")):
        return "font/otf"
    return "application/octet-stream"


def _theme_script(theme: str) -> bytes:
    return f'<script>document.documentElement.dataset.theme="{theme}"</script>'.encode()


def _inject(html: bytes, theme: str) -> bytes:
    match = re.search(rb"<head[^>]*>", html, re.IGNORECASE)
    script = _theme_script(theme)
    return html[: match.end()] + script + html[match.end() :] if match else script + html


def _slide_document(source: _Source, deck: dict[str, Any], slide_id: str, width: int, height: int) -> bytes | None:
    slide_bytes = source.file(f"project/slides/{slide_id}.html")
    if slide_bytes is None:
        return None
    slide_html = slide_bytes.decode("utf-8", "replace")
    # Strip <x-embed> bodies per viewer.md security guidance.
    slide_html = re.sub(r"(<x-embed\b[^>]*>)[\s\S]*?(</x-embed>)", r"\1\2", slide_html, flags=re.IGNORECASE)

    head_parts: list[str] = ['<meta charset="utf-8">']
    faces = deck.get("faces")
    font_css: list[str] = []
    if isinstance(faces, dict):
        for face in faces.values():
            if not isinstance(face, dict):
                continue
            href = face.get("href")
            family = face.get("family")
            src = face.get("src")
            if isinstance(href, str) and href.startswith("https://fonts.googleapis.com/css2?"):
                head_parts.append(f'<link rel="stylesheet" href="{html_lib.escape(href, quote=True)}">')
            elif (
                isinstance(family, str)
                and isinstance(src, str)
                and (src.startswith("/_blob/") or src.startswith("project/"))
            ):
                url = src if src.startswith("/") else "/" + src
                safe_family = family.replace("\\", "").replace("'", "")
                font_css.append(f"@font-face {{ font-family: '{safe_family}'; src: url('{url}'); }}")

    base_css = _SLIDES_BASE_CSS.replace("__W__", str(width)).replace("__H__", str(height))
    head_parts.append(f"<style>{base_css}{''.join(font_css)}</style>")

    fmt = deck.get("format")
    if isinstance(fmt, dict):
        shared = fmt.get("shared")
        if isinstance(shared, list):
            for css_path in shared:
                if isinstance(css_path, str) and css_path.startswith("project/"):
                    head_parts.append(f'<link rel="stylesheet" href="/{quote(css_path, safe="/")}">')

    # Reveal fragments for the completed slide view, keep pinned backdrops behind flow content.
    settle_script = "<script>document.querySelectorAll('.fragment').forEach(el=>el.classList.add('visible'));</script>"
    return (
        f"<!doctype html><html><head>{''.join(head_parts)}</head><body>{slide_html}{settle_script}</body></html>"
    ).encode()


class _Source:
    """Serves the render's files from memory: overrides first, then published bytes, runtime, and assets."""

    def __init__(self, client: ArtifactClient, snapshot: ArtifactSnapshot, overrides: dict[str, bytes]) -> None:
        self.client = client
        self.snapshot = snapshot
        self.overrides = overrides
        self.cache: dict[str, bytes] = {}
        self.missing: list[str] = []
        self.lock = threading.Lock()

    def file(self, path: str) -> bytes | None:
        with self.lock:
            if path in self.overrides:
                return self.overrides[path]
            if path in self.cache:
                return self.cache[path]
            data: bytes | None = None
            try:
                if path.endswith("support.js") and path not in self.snapshot.files:
                    data = self.client._content(
                        self.snapshot.id,
                        self.snapshot.version,
                        ARTIFACT_RENDER_RUNTIME_PATH,
                        self.snapshot.asset_token,
                        ARTIFACT_MAX_FILE_BYTES,
                    )
                elif path.startswith("_blob/") and ASSET_ID.fullmatch(path[6:]):
                    data = self.client.read_blob(self.snapshot, path[6:], ARTIFACT_MAX_ASSET_BYTES)
                elif path in self.snapshot.files:
                    data = self.client.read_file(self.snapshot, path)
            except (ArtifactProtocolError, ValueError):
                data = None
            if data is None:
                self.missing.append(path)
            else:
                self.cache[path] = data
            return data


def _handler(
    source: _Source, *, deck: dict[str, Any] | None = None, slide_size: tuple[int, int] = (1920, 1080)
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            parts = urlsplit(self.path)
            path = parts.path.lstrip("/")
            query = parse_qs(parts.query)
            theme = query.get("__oca_theme", [""])[0]
            if path == VIEWPORT:
                target, width, height = query.get("src", [""])[0], query.get("w", ["0"])[0], query.get("h", ["0"])[0]
                if not width.isdigit() or not height.isdigit() or theme not in ARTIFACT_RENDER_THEMES:
                    self.send_error(400)
                    return
                file_path(target)
                frame = (
                    f'<!doctype html><html><body style="margin:0;overflow:hidden">'
                    f'<iframe src="/{quote(target)}?__oca_theme={theme}" '
                    f'style="display:block;border:0;width:{width}px;height:{height}px"></iframe></body></html>'
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(frame)
                return
            if path == SLIDE_VIEW and deck is not None:
                slide_id = query.get("id", [""])[0]
                if not SLIDE_ID_RE.fullmatch(slide_id):
                    self.send_error(400)
                    return
                doc = _slide_document(source, deck, slide_id, slide_size[0], slide_size[1])
                if doc is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(doc)
                return
            try:
                file_path(path)
            except ValueError:
                self.send_error(404)
                return
            data = source.file(path)
            if data is None:
                self.send_error(404)
                return
            mime = _sniff_content_type(path, data)
            if mime == "text/html" and theme in ARTIFACT_RENDER_THEMES:
                data = _inject(data, theme)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

    return Handler


def _slide_targets(
    source: _Source, paths: list[str], slides: list[str]
) -> tuple[dict[str, Any], tuple[int, int], list[dict[str, Any]]]:
    raw = source.file("project/deck.json")
    if raw is None:
        raise ArtifactSafetyError("The deck has no project/deck.json yet; write its index and cover slide first.")
    deck = json.loads(raw)
    order = deck.get("order")
    if not isinstance(order, list) or not order:
        raise ArtifactSafetyError("project/deck.json has no slides in order.")
    width, height = (1440, 1080) if deck.get("size") == "4:3" else (1920, 1080)

    selected_ids: list[str] = []
    for item in slides:
        if item.isdigit():
            index = int(item)
            if not 1 <= index <= len(order):
                raise ValueError(f"Slide number {index} is out of range (1–{len(order)}).")
            selected_ids.append(str(order[index - 1]))
        else:
            cleaned = item.removeprefix("project/slides/").removesuffix(".html")
            if cleaned not in order:
                raise ValueError(f"Slide {item!r} is not listed in project/deck.json order.")
            selected_ids.append(cleaned)
    for path in paths:
        match = re.fullmatch(r"project/slides/([A-Za-z0-9_-]{1,64})\.html", path)
        if match is None:
            raise ValueError(f"Slide path must be project/slides/<id>.html, got: {path}")
        if match.group(1) not in order:
            raise ValueError(f"Slide {match.group(1)!r} is not listed in project/deck.json order.")
        selected_ids.append(match.group(1))
    if not selected_ids:
        selected_ids = [str(slide_id) for slide_id in order]

    # Deduplicate while preserving selection order.
    seen: set[str] = set()
    targets: list[dict[str, Any]] = []
    for slide_id in selected_ids:
        if slide_id in seen:
            continue
        seen.add(slide_id)
        number = order.index(slide_id) + 1
        targets.append(
            {
                "kind": "slide",
                "slide_id": slide_id,
                "slide_number": number,
                "path": f"project/slides/{slide_id}.html",
                "width": width,
                "height": height,
            }
        )
    return deck, (width, height), targets


def _targets(kind: str | None, source: _Source, paths: list[str]) -> list[dict[str, Any]]:
    if kind == "design":
        raw = source.file("project/canvas.json")
        if raw is None:
            raise ArtifactSafetyError("The canvas has no project/canvas.json yet; write its first artboard.")
        index = json.loads(raw)
        boards = index.get("boards", {})
        chosen = paths or ["project/" + name for name in index.get("order", [])]
        targets = []
        for path in chosen:
            board = boards.get(path.removeprefix("project/"), {})
            height = int(min(max(board.get("h", ARTIFACT_RENDER_DEFAULT_HEIGHT), 40), ARTIFACT_RENDER_MAX_HEIGHT))
            fixed = None if board.get("expand") == "fill" else int(board.get("w", 0)) or None
            targets.append({"kind": "page", "path": path, "height": height, "fixed_width": fixed})
        return targets
    if kind in ARTIFACT_FILE_KINDS:
        raise ArtifactSafetyError(
            "Local rendering covers Design artboards, Slides decks, and plain artifact pages; "
            "open Design System artifacts in Claude to inspect them."
        )
    if kind is not None:
        raise ArtifactSafetyError("This artifact type keeps its content in a store and has no local render.")
    return [
        {"kind": "page", "path": path, "height": ARTIFACT_RENDER_DEFAULT_HEIGHT, "fixed_width": None}
        for path in paths or ["index.html"]
    ]


def render(
    client: ArtifactClient,
    snapshot: ArtifactSnapshot,
    *,
    output_dir: Path,
    paths: list[str] | None = None,
    slides: list[str] | None = None,
    overrides: dict[str, bytes] | None = None,
    widths: list[int] | None = None,
    themes: list[str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    browser: str | None = None,
) -> dict[str, Any]:
    browser = browser or find_browser()
    if browser is None:
        raise ArtifactSafetyError(
            f"No Chrome, Chromium, or Edge was found; set {ARTIFACT_RENDER_BROWSER_ENV} to a browser binary."
        )
    widths = widths or [1280, 390]
    themes = themes or list(ARTIFACT_RENDER_THEMES)
    if len(widths) > ARTIFACT_RENDER_MAX_WIDTHS or any(not 240 <= width <= 3840 for width in widths):
        raise ValueError("Render at 1–4 widths between 240 and 3840 CSS pixels.")
    if any(theme not in ARTIFACT_RENDER_THEMES for theme in themes):
        raise ValueError("Themes are light and dark.")
    source = _Source(client, snapshot, overrides or {})
    kind = client.type_kind(snapshot.type_id, type_title=snapshot.type_title)
    deck: dict[str, Any] | None = None
    slide_size = (1920, 1080)
    if kind == "slides":
        deck, slide_size, targets = _slide_targets(source, [file_path(p) for p in paths or []], slides or [])
    else:
        if slides:
            raise ValueError("--slide is only supported for Slides decks.")
        targets = _targets(kind, source, [file_path(path) for path in paths or []])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(source, deck=deck, slide_size=slide_size))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    rules = "MAP * ~NOTFOUND, " + ", ".join(f"EXCLUDE {host}" for host in ("127.0.0.1", *ARTIFACT_RENDER_ALLOWED_HOSTS))
    output_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    try:
        for target in targets:
            if target["kind"] == "slide":
                slide_id = target["slide_id"]
                number = target["slide_number"]
                width, height = target["width"], target["height"]
                image = output_dir / f"slide-{number:02d}-{slide_id}.png"
                with tempfile.TemporaryDirectory(prefix="oca-render-") as profile:
                    completed = runner(
                        [
                            browser,
                            "--headless=new",
                            f"--user-data-dir={profile}",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-extensions",
                            "--hide-scrollbars",
                            "--enable-logging=stderr",
                            "--v=0",
                            f"--host-resolver-rules={rules}",
                            f"--window-size={width},{height}",
                            f"--virtual-time-budget={ARTIFACT_RENDER_SETTLE_MS}",
                            f"--screenshot={image}",
                            f"http://127.0.0.1:{port}/{SLIDE_VIEW}?" + urlencode({"id": slide_id}),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=ARTIFACT_RENDER_TIMEOUT_SECONDS,
                        check=False,
                    )
                console = [
                    {"level": level.lower(), "message": message[:500], "line": int(line)}
                    for level, message, _source, line in CONSOLE.findall(completed.stderr or "")
                    if level != "INFO"
                ]
                shots.append(
                    {
                        "slide": number,
                        "slide_id": slide_id,
                        "path": target["path"],
                        "width": width,
                        "height": height,
                        "image": str(image),
                        "rendered": completed.returncode == 0 and image.is_file(),
                        "console": console,
                    }
                )
                continue

            stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", target["path"].removeprefix("project/"))
            for width in [target["fixed_width"]] if target["fixed_width"] else widths:
                for theme in themes:
                    image = output_dir / f"{stem}-{width}-{theme}.png"
                    with tempfile.TemporaryDirectory(prefix="oca-render-") as profile:
                        completed = runner(
                            [
                                browser,
                                "--headless=new",
                                f"--user-data-dir={profile}",
                                "--no-first-run",
                                "--no-default-browser-check",
                                "--disable-extensions",
                                "--hide-scrollbars",
                                "--enable-logging=stderr",
                                "--v=0",
                                f"--host-resolver-rules={rules}",
                                f"--blink-settings=preferredColorScheme={0 if theme == 'dark' else 1}",
                                f"--window-size={width},{target['height']}",
                                f"--virtual-time-budget={ARTIFACT_RENDER_SETTLE_MS}",
                                f"--screenshot={image}",
                                f"http://127.0.0.1:{port}/{VIEWPORT}?"
                                + urlencode(
                                    {"src": target["path"], "w": width, "h": target["height"], "__oca_theme": theme}
                                ),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=ARTIFACT_RENDER_TIMEOUT_SECONDS,
                            check=False,
                        )
                    console = [
                        {"level": level.lower(), "message": message[:500], "line": int(line)}
                        for level, message, _source, line in CONSOLE.findall(completed.stderr or "")
                        if level != "INFO"
                    ]
                    shots.append(
                        {
                            "path": target["path"],
                            "width": width,
                            "height": target["height"],
                            "theme": theme,
                            "image": str(image),
                            "rendered": completed.returncode == 0 and image.is_file(),
                            "console": console,
                        }
                    )
    finally:
        server.shutdown()
        server.server_close()
    missing = sorted(set(source.missing) - {"favicon.ico"})
    return {
        "id": snapshot.id,
        "version": snapshot.version,
        "kind": kind,
        "local_overrides": sorted(overrides or {}),
        "render_executed": True,
        "shots": shots,
        "missing_requests": missing,
        "ok": all(shot["rendered"] and not any(c["level"] == "error" for c in shot["console"]) for shot in shots)
        and not missing,
        "note": "Network was limited to loopback and the artifact CDN allowlist; inspect every image before reporting.",
    }


def render_directory(root: Path, artifact: str) -> Path:
    return root.joinpath(*ARTIFACT_RENDER_PARTS, artifact)
