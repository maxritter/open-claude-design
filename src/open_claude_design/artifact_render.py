"""Local headless rendering of artifact pages and Design artboards, published or pending."""

from __future__ import annotations

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

from open_claude_design.artifact_api import ArtifactClient, ArtifactSnapshot, content_type_for, file_path
from open_claude_design.artifact_store import ASSET_ID
from open_claude_design.config import (
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
)
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError

VIEWPORT = "__ocd_viewport"
CONSOLE = re.compile(r":(INFO|WARNING|ERROR):CONSOLE(?:\(\d+\))?\] \"(.*)\", source: (\S*) \((\d+)\)")


def find_browser() -> str | None:
    override = os.environ.get(ARTIFACT_RENDER_BROWSER_ENV)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    for candidate in ARTIFACT_RENDER_BROWSERS:
        if candidate.startswith("/"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        elif found := shutil.which(candidate):
            return found
    return None


def _theme_script(theme: str) -> bytes:
    return f'<script>document.documentElement.dataset.theme="{theme}"</script>'.encode()


def _inject(html: bytes, theme: str) -> bytes:
    match = re.search(rb"<head[^>]*>", html, re.IGNORECASE)
    script = _theme_script(theme)
    return html[: match.end()] + script + html[match.end() :] if match else script + html


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
            except (ClaudeDesignProtocolError, ValueError):
                data = None
            if data is None:
                self.missing.append(path)
            else:
                self.cache[path] = data
            return data


def _handler(source: _Source) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            parts = urlsplit(self.path)
            path = parts.path.lstrip("/")
            query = parse_qs(parts.query)
            theme = query.get("__ocd_theme", [""])[0]
            if path == VIEWPORT:
                # Headless windows have a minimum width, so pages render in an exact-width frame instead.
                target, width, height = query.get("src", [""])[0], query.get("w", ["0"])[0], query.get("h", ["0"])[0]
                if not width.isdigit() or not height.isdigit() or theme not in ARTIFACT_RENDER_THEMES:
                    self.send_error(400)
                    return
                file_path(target)
                frame = (
                    f'<!doctype html><html><body style="margin:0;overflow:hidden">'
                    f'<iframe src="/{quote(target)}?__ocd_theme={theme}" '
                    f'style="display:block;border:0;width:{width}px;height:{height}px"></iframe></body></html>'
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(frame)
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
            mime = content_type_for(path) or "application/octet-stream"
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


def _targets(kind: str | None, source: _Source, paths: list[str]) -> list[dict[str, Any]]:
    if kind == "design":
        raw = source.file("project/canvas.json")
        if raw is None:
            raise ClaudeDesignSafetyError("The canvas has no project/canvas.json yet; write its first artboard.")
        index = json.loads(raw)
        boards = index.get("boards", {})
        chosen = paths or ["project/" + name for name in index.get("order", [])]
        targets = []
        for path in chosen:
            board = boards.get(path.removeprefix("project/"), {})
            height = int(min(max(board.get("h", ARTIFACT_RENDER_DEFAULT_HEIGHT), 40), ARTIFACT_RENDER_MAX_HEIGHT))
            fixed = None if board.get("expand") == "fill" else int(board.get("w", 0)) or None
            targets.append({"path": path, "height": height, "fixed_width": fixed})
        return targets
    if kind in ARTIFACT_FILE_KINDS:
        raise ClaudeDesignSafetyError(
            "Local rendering covers Design artboards and plain artifact pages; open Slides and Design System "
            "artifacts in Claude to check them."
        )
    if kind is not None:
        raise ClaudeDesignSafetyError("This artifact type keeps its content in a store and has no local render.")
    return [
        {"path": path, "height": ARTIFACT_RENDER_DEFAULT_HEIGHT, "fixed_width": None}
        for path in paths or ["index.html"]
    ]


def render(
    client: ArtifactClient,
    snapshot: ArtifactSnapshot,
    *,
    output_dir: Path,
    paths: list[str] | None = None,
    overrides: dict[str, bytes] | None = None,
    widths: list[int] | None = None,
    themes: list[str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    browser: str | None = None,
) -> dict[str, Any]:
    browser = browser or find_browser()
    if browser is None:
        raise ClaudeDesignSafetyError(
            f"No Chrome, Chromium, or Edge was found; set {ARTIFACT_RENDER_BROWSER_ENV} to a browser binary."
        )
    widths = widths or [1280, 390]
    themes = themes or list(ARTIFACT_RENDER_THEMES)
    if len(widths) > ARTIFACT_RENDER_MAX_WIDTHS or any(not 240 <= width <= 3840 for width in widths):
        raise ValueError("Render at 1–4 widths between 240 and 3840 CSS pixels.")
    if any(theme not in ARTIFACT_RENDER_THEMES for theme in themes):
        raise ValueError("Themes are light and dark.")
    source = _Source(client, snapshot, overrides or {})
    kind = client.type_kind(snapshot.type_id)
    targets = _targets(kind, source, [file_path(path) for path in paths or []])
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(source))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    rules = "MAP * ~NOTFOUND, " + ", ".join(f"EXCLUDE {host}" for host in ("127.0.0.1", *ARTIFACT_RENDER_ALLOWED_HOSTS))
    output_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    try:
        for target in targets:
            stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", target["path"].removeprefix("project/"))
            for width in [target["fixed_width"]] if target["fixed_width"] else widths:
                for theme in themes:
                    image = output_dir / f"{stem}-{width}-{theme}.png"
                    with tempfile.TemporaryDirectory(prefix="ocd-render-") as profile:
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
                                    {"src": target["path"], "w": width, "h": target["height"], "__ocd_theme": theme}
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
        "backend": "artifact",
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
    return root.joinpath(*ARTIFACT_RENDER_PARTS, re.sub(r"[^A-Za-z0-9_-]", "_", artifact))
