"""Artifact OAuth credentials owned by this CLI, isolated from every other login."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from open_claude_design import auth
from open_claude_design.config import (
    ARTIFACT_CREDENTIAL_PARTS,
    ARTIFACT_KEYCHAIN_ACCOUNT,
    ARTIFACT_KEYCHAIN_SERVICE,
    ARTIFACT_OAUTH_CLIENT_ID,
    ARTIFACT_OAUTH_SCOPES,
    CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS,
)


def credential_file(home: Path | None = None) -> Path:
    return (home or Path.home()).joinpath(*ARTIFACT_CREDENTIAL_PARTS)


def save_artifact_credential(
    payload: dict[str, object],
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if platform == "darwin":
        auth._write_keychain(payload, runner, service=ARTIFACT_KEYCHAIN_SERVICE, account=ARTIFACT_KEYCHAIN_ACCOUNT)
    elif platform.startswith("linux"):
        auth._write_secure_json_file(credential_file(home), payload)
    else:
        raise auth.DesignAuthError("Artifact login supports macOS, Linux, and WSL2.")


def _read(
    platform: str, home: Path | None, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> dict[str, object] | None:
    if platform == "darwin":
        return auth._read_keychain(runner, service=ARTIFACT_KEYCHAIN_SERVICE, account=ARTIFACT_KEYCHAIN_ACCOUNT)
    if platform.startswith("linux"):
        return auth._read_secure_json_file(credential_file(home))
    return None


def load_artifact_credential(
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now_ms: int | None = None,
    token_opener: Callable[..., Any] = auth._TOKEN_OPENER.open,
) -> dict[str, Any]:
    current = int(time.time() * 1000) if now_ms is None else now_ms

    def record(payload: dict[str, object] | None) -> dict[str, Any]:
        value = payload.get("artifactOauth") if payload else None
        if not isinstance(value, dict) or not isinstance(value.get("accessToken"), str) or not value["accessToken"]:
            raise auth.DesignAuthError("Connect artifacts with open-claude-design login --backend artifact.")
        if value.get("clientId") != ARTIFACT_OAUTH_CLIENT_ID:
            raise auth.DesignAuthError("Artifact credential belongs to another OAuth client; reconnect.")
        scopes = value.get("scopes")
        if not isinstance(scopes, list) or any(scope not in scopes for scope in ARTIFACT_OAUTH_SCOPES):
            raise auth.DesignAuthError(
                "Artifact credentials lack the required scopes; reconnect with --backend artifact."
            )
        expiry = value.get("expiresAt")
        if not isinstance(expiry, int) or isinstance(expiry, bool):
            raise auth.DesignAuthError("Artifact credentials have no valid expiry; reconnect with --backend artifact.")
        return value

    value = record(_read(platform, home, runner))
    if value["expiresAt"] > current + CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS * 1000:
        return value
    with auth._refresh_lock(path=credential_file(home)):
        value = record(_read(platform, home, runner))
        if value["expiresAt"] > current + CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS * 1000:
            return value
        refresh = value.get("refreshToken")
        if not isinstance(refresh, str) or not refresh:
            raise auth.DesignAuthError("Artifact login expired; reconnect with --backend artifact.")
        token = auth._request_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": ARTIFACT_OAUTH_CLIENT_ID,
                "scope": " ".join(ARTIFACT_OAUTH_SCOPES),
            },
            opener=token_opener,
        )
        payload = auth._credential_payload(
            token,
            client_id=ARTIFACT_OAUTH_CLIENT_ID,
            fallback_refresh_token=refresh,
            now_ms=current,
            required_scopes=ARTIFACT_OAUTH_SCOPES,
            record_key="artifactOauth",
            identity=value.get("identity"),
        )
        save_artifact_credential(payload, platform=platform, home=home, runner=runner)
        return record(payload)


def delete_artifact_credential(
    *,
    platform: str = sys.platform,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    if platform == "darwin":
        result = runner(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                ARTIFACT_KEYCHAIN_ACCOUNT,
                "-s",
                ARTIFACT_KEYCHAIN_SERVICE,
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    if platform.startswith("linux"):
        path = Path(os.path.abspath(credential_file(home)))
        parent = auth._open_secure_parent(path, create=False)
        if parent is None:
            return False
        try:
            os.unlink(path.name, dir_fd=parent)
            return True
        except FileNotFoundError:
            return False
        finally:
            os.close(parent)
    raise auth.DesignAuthError("Artifact logout supports macOS, Linux, and WSL2.")
