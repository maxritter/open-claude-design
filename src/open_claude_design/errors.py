"""Shared failures for the MCP and first-party API transports."""


class ClaudeDesignError(RuntimeError):
    """Base error for actionable Claude Design failures."""


class ClaudeDesignAuthError(ClaudeDesignError):
    """Claude Design authentication is unavailable or expired."""


class ClaudeDesignProtocolError(ClaudeDesignError):
    """Claude Design returned an invalid or failed response."""


class ClaudeDesignSafetyError(ClaudeDesignError):
    """An operation exceeded its authorized scope."""
