"""Read-only transition diagnostics and bounded history preservation."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from open_claude_design.config import (
    CLAUDE_DESIGN_ARTIFACT_GUIDE_URL,
    CLAUDE_DESIGN_ARTIFACT_PATH_PREFIXES,
    CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES,
    CLAUDE_DESIGN_MAX_RESPONSE_BYTES,
    CLAUDE_DESIGN_MIGRATION_GUIDE_URL,
    CLAUDE_DESIGN_RESOURCE_HOSTS,
    CLAUDE_DESIGN_STANDALONE_CLOSE_DATE,
    CLAUDE_DESIGN_STANDALONE_PATH_PREFIX,
)
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError


def transition_status(*, today: date | None = None) -> dict[str, Any]:
    current = today or datetime.now(UTC).date()
    closing = date.fromisoformat(CLAUDE_DESIGN_STANDALONE_CLOSE_DATE)
    return {
        "standalone_closes_on": closing.isoformat(),
        "days_until_closure": max(0, (closing - current).days),
        "closure_date_reached": current >= closing,
        "guide_url": CLAUDE_DESIGN_MIGRATION_GUIDE_URL,
        "artifact_guide_url": CLAUDE_DESIGN_ARTIFACT_GUIDE_URL,
        "backends": {
            "standalone": {"implemented": True, "authentication": "Design-scoped OAuth"},
            "artifact": {"implemented": True, "experimental": True, "authentication": "Separate subscription OAuth"},
        },
        "preserve_before_closure": ["project files", "chats", "comments", "sharing metadata"],
        "project_migration": "Anthropic has not yet documented the project migration procedure.",
        "design_system_migration": "Use Claude's Artifacts page; migration affects the whole organization.",
    }


def resolve_target(value: str) -> dict[str, str]:
    """Classify a resource without fetching it or retaining URL query capabilities."""
    if not value or any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in value) or "\\" in value:
        raise ValueError("Use a project id or a supported HTTPS Claude resource URL.")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        return {"backend": "standalone", "resource_id": value, "identity_source": "bare-project-id"}
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in CLAUDE_DESIGN_RESOURCE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValueError
    except ValueError as error:
        raise ValueError("Use a project id or a supported HTTPS Claude resource URL.") from error
    prefixes = (
        (CLAUDE_DESIGN_STANDALONE_PATH_PREFIX, "standalone"),
        *((prefix, "artifact") for prefix in CLAUDE_DESIGN_ARTIFACT_PATH_PREFIXES),
    )
    for prefix, backend in prefixes:
        if parsed.path.startswith(prefix):
            resource_id = parsed.path[len(prefix) :].removesuffix("/")
            if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", resource_id):
                return {
                    "backend": backend,
                    "resource_id": resource_id,
                    "url": f"https://claude.ai{prefix}{resource_id}",
                    "identity_source": "url",
                }
    raise ValueError("This URL does not identify a supported Claude project or artifact route.")


def standalone_target(value: str) -> str:
    target = resolve_target(value)
    if target["backend"] != "standalone":
        raise ClaudeDesignSafetyError(
            "This is a Claude artifact, not a standalone Design project. Use artifacts commands and "
            "login --backend artifact; do not reuse its id with standalone commands."
        )
    return target["resource_id"]


def strict_history_result(result: dict[str, Any], *, tool: str) -> Any:
    """Reject capped, malformed, or ambiguous history instead of archiving a partial document."""
    failure = f"Cannot preserve complete {tool} history; no archive saved."
    limit = CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES if tool == "get_conversation" else CLAUDE_DESIGN_MAX_RESPONSE_BYTES
    if result.get("isError") is True or result.get("truncated") is True:
        raise ClaudeDesignProtocolError(failure)
    value = result.get("structuredContent")
    if not isinstance(value, dict | list):
        content = result.get("content")
        texts = (
            [
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            ]
            if isinstance(content, list)
            else []
        )
        if len(texts) != 1:
            raise ClaudeDesignProtocolError(failure)
        text = texts[0].strip()
        if text.startswith("<untrusted-project-content"):
            wrapper = re.match(
                r"<untrusted-project-content\b([^>]*)>\n?([\s\S]*?)\n?</untrusted-project-content>", text
            )
            if wrapper is None or text.count("<untrusted-project-content") != 1:
                raise ClaudeDesignProtocolError(failure + " The response is truncated or lacks a complete wrapper.")
            attributes = wrapper.group(1)
            footer = text[wrapper.end() :]
            if re.search(r"\b(?:truncated|truncation|partial)\b", footer, re.IGNORECASE):
                raise ClaudeDesignProtocolError(failure + " The host reports incomplete history.")
            lines = re.search(r'\blines="(\d+)-(\d+)"', attributes)
            total = re.search(r'\btotal_lines="(\d+)"', attributes)
            if "truncated" in attributes or (lines and (not total or lines[1] != "1" or lines[2] != total[1])):
                raise ClaudeDesignProtocolError(failure + " The response contains only part of the history.")
            text = wrapper.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if len(text.encode("utf-8")) >= limit:
            raise ClaudeDesignProtocolError(failure + " The response reached the history read cap.")
        try:
            value = json.loads(text)
        except ValueError as error:
            raise ClaudeDesignProtocolError(failure + " The response is not complete JSON.") from error
    if not isinstance(value, dict | list) or (isinstance(value, dict) and value.get("truncated") is True):
        raise ClaudeDesignProtocolError(failure)
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except ValueError as error:
        raise ClaudeDesignProtocolError(failure + " The response contains invalid JSON values.") from error
    if len(serialized.encode("utf-8")) >= limit:
        raise ClaudeDesignProtocolError(failure + " The response reached the history read cap.")
    return value


def redact_history(value: Any) -> Any:
    """Strip credential fields and render capabilities from saved collaboration metadata."""
    if isinstance(value, dict):
        return {
            str(key): "<redacted>"
            if re.sub(r"[^a-z0-9]", "", str(key).lower())
            in {
                "accesstoken",
                "refreshtoken",
                "authorization",
                "authorizationcode",
                "bearertoken",
                "plantoken",
                "serveurl",
                "cookie",
                "setcookie",
                "designoauth",
            }
            else redact_history(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_history(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"https://[^\s\"'<>]*claudeusercontent\.com[^\s\"'<>]*", "<redacted-preview>", value)
        value = re.sub(r"\bBearer\s+[^\s\"'<>]+", "Bearer <redacted>", value, flags=re.IGNORECASE)
        value = re.sub(r"\bsk-ant-[A-Za-z0-9_-]+", "<redacted>", value)
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(redact_history(json.loads(value)), ensure_ascii=True)
            except ValueError:
                pass
    return value


def history_snapshot(client: Any, project_id: str) -> dict[str, Any]:
    snapshot = {
        key: strict_history_result(client.call_tool(tool, {"project_id": project_id}), tool=tool)
        for key, tool in (
            ("project", "get_project"),
            ("conversations", "get_conversation"),
            ("comments", "list_comments"),
        )
    }
    if isinstance(snapshot["comments"], dict):
        # Each read mints a new polling watermark even when no thread changed.
        snapshot["comments"] = {key: value for key, value in snapshot["comments"].items() if key != "server_time"}
    return snapshot
