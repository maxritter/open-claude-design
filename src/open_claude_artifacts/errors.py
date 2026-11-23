"""Shared failures for Open Claude Artifacts."""


class ArtifactError(RuntimeError):
    """Base error for actionable Claude Artifacts failures."""


class ArtifactAuthError(ArtifactError):
    """Claude Artifacts authentication is unavailable or expired."""


class ArtifactProtocolError(ArtifactError):
    """The artifact service returned an invalid or failed response."""


class ArtifactSafetyError(ArtifactError):
    """An operation exceeded its authorized scope or safety bounds."""
