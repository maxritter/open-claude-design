"""Real macOS Keychain roundtrip for the Claude Artifacts credential."""

from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

import open_claude_artifacts.auth as auth
from open_claude_artifacts.config import OAUTH_CLIENT_ID, OAUTH_SCOPES

pytestmark = pytest.mark.integration


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the macOS Keychain")
def test_darwin_keychain_roundtrip_preserves_the_full_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    scratch = f"open-claude-artifacts-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(auth, "KEYCHAIN_SERVICE", scratch)
    monkeypatch.setattr(auth, "KEYCHAIN_ACCOUNT", scratch)
    payload: dict[str, object] = {
        "artifactOauth": {
            "accessToken": "a" * 300,
            "refreshToken": "r" * 250,
            "expiresAt": 9_999_999_999_999,
            "scopes": list(OAUTH_SCOPES),
            "clientId": OAUTH_CLIENT_ID,
            "identity": "0" * 32,
        }
    }

    try:
        auth.save_artifact_credential(payload, platform="darwin")
        assert auth._read_keychain(service=scratch, account=scratch) == payload
    finally:
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", scratch, "-s", scratch],
            capture_output=True,
            timeout=10,
            check=False,
        )
