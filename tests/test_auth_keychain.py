"""Real macOS Keychain roundtrip for the standalone Design credential."""

from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

import open_claude_design.auth as auth
from open_claude_design.config import CLAUDE_DESIGN_OAUTH_CLIENT_ID, CLAUDE_DESIGN_OAUTH_SCOPES

pytestmark = pytest.mark.integration


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the macOS Keychain")
def test_darwin_keychain_roundtrip_preserves_the_full_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real tokens push the payload far past the 128-byte limit of security's
    # interactive password prompt, which silently truncates (exit code 0).
    scratch = f"open-claude-design-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(auth, "CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE", scratch)
    monkeypatch.setattr(auth, "CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT", scratch)
    payload: dict[str, object] = {
        "designOauth": {
            "accessToken": "a" * 300,
            "refreshToken": "r" * 250,
            "expiresAt": 9_999_999_999_999,
            "scopes": list(CLAUDE_DESIGN_OAUTH_SCOPES),
            "clientId": CLAUDE_DESIGN_OAUTH_CLIENT_ID,
        }
    }

    try:
        auth.save_standalone_credential(payload, platform="darwin")
        assert auth._read_keychain() == payload
    finally:
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", scratch, "-s", scratch],
            capture_output=True,
            timeout=10,
            check=False,
        )
