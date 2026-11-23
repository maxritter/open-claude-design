"""Central configuration for the Open Claude Artifacts package."""

from __future__ import annotations

from typing import Final

PACKAGE_NAME: Final = "open-claude-artifacts"
VERSION: Final = "2.0.0"

ARTIFACT_GUIDE_URL: Final = "https://code.claude.com/docs/en/artifacts"
ARTIFACT_RESOURCE_HOSTS: Final = frozenset({"claude.ai", "www.claude.ai"})
ARTIFACT_PATH_PREFIXES: Final = ("/code/artifact/", "/artifact/", "/artifacts/", "/public/artifacts/")
ARTIFACT_API_ORIGIN: Final = "https://api.anthropic.com"
ARTIFACT_API_PREFIX: Final = "/api/frame/"
ARTIFACT_CONTENT_HOST_SUFFIX: Final = ".frame.claudeusercontent.com"
ARTIFACT_PROTOCOL_CLIENT_VERSION: Final = "2.1.304"

# OAuth configuration for Claude Artifacts (native subscription client).
OAUTH_AUTHORIZE_URL: Final = "https://claude.com/cai/oauth/authorize"
OAUTH_TOKEN_URL: Final = "https://platform.claude.com/v1/oauth/token"
OAUTH_MANUAL_REDIRECT_URL: Final = "https://platform.claude.com/oauth/code/callback"
OAUTH_SUCCESS_URL: Final = "https://platform.claude.com/oauth/code/success?app=claude-code"
OAUTH_CLIENT_ID: Final = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_SCOPES: Final = ("user:profile", "user:inference", "user:sessions:claude_code")
OAUTH_BETA: Final = "oauth-2025-04-20"
OAUTH_USER_AGENT: Final = f"{PACKAGE_NAME}/{VERSION}"
OAUTH_TIMEOUT_SECONDS: Final = 5 * 60
OAUTH_REFRESH_MARGIN_SECONDS: Final = 2 * 60
OAUTH_RESPONSE_MAX_BYTES: Final = 1024 * 1024
BROWSER_LOGIN_ENV: Final = "OPEN_CLAUDE_ARTIFACTS_BROWSER_LOGIN"
LEGACY_BROWSER_LOGIN_ENV: Final = "OPEN_CLAUDE_DESIGN_BROWSER_LOGIN"

KEYCHAIN_SERVICE: Final = "Open Claude Artifacts-credentials"
KEYCHAIN_ACCOUNT: Final = "open-claude-artifacts"
CREDENTIAL_PARTS: Final = (".config", "open-claude-artifacts", "credentials.json")
LEGACY_KEYCHAIN_SERVICE: Final = "Open Claude Design-artifact-credentials"
LEGACY_KEYCHAIN_ACCOUNT: Final = "open-claude-design-artifact"
LEGACY_CREDENTIAL_PARTS: Final = (".config", "open-claude-design", "artifact-credentials.json")
CREDENTIAL_MAX_BYTES: Final = 1024 * 1024
MIN_WRITE_CREDENTIAL_SECONDS: Final = 5 * 60

OPERATION_LOCK_PARTS: Final = (".config", "open-claude-artifacts", "operation-locks")
OPERATION_LOCK_SECONDS: Final = 10.0

WORKSPACE_STATE_DIR: Final = ".open-claude-artifacts"
ARTIFACT_CONTEXT_PARTS: Final = (WORKSPACE_STATE_DIR, "context")
ARTIFACT_SYNC_PARTS: Final = (WORKSPACE_STATE_DIR, "sync")
ARTIFACT_RENDER_PARTS: Final = (WORKSPACE_STATE_DIR, "renders")
ARTIFACT_SYNC_SCHEMA_VERSION: Final = 1
ARTIFACT_MAX_SYNC_PAIRS: Final = 64
ARTIFACT_MAX_SYNC_BYTES: Final = 32 * 1024 * 1024
ARTIFACT_MAX_SYNC_DIFF_BYTES: Final = 8 * 1024 * 1024

ARTIFACT_MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
ARTIFACT_MAX_FILE_BYTES: Final = 16 * 1024 * 1024
ARTIFACT_MAX_INLINE_FILE_BYTES: Final = 256 * 1024
ARTIFACT_MAX_STDIN_BYTES: Final = 1024 * 1024
ARTIFACT_MAX_WRITE_BYTES: Final = 15 * 1024 * 1024
ARTIFACT_MAX_WRITE_FILES: Final = 256
ARTIFACT_MAX_FILES: Final = 4096
ARTIFACT_MAX_LIST_PAGES: Final = 64

# Artifact type titles as the service lists them, mapped to the content model each one uses.
ARTIFACT_TYPE_KINDS: Final = {
    "Design": "design",
    "Slides": "slides",
    "Design System": "design-system",
    "Data": "dashboard",
    "Dashboard": "dashboard",
    "Docs": "docs",
    "Sheets": "sheets",
    "Whiteboard": "whiteboard",
    "Migrated Design": "migrated-design",
}
# File-backed kinds: the index each keeps under project/ and the accepted schema versions.
ARTIFACT_FILE_KINDS: Final[dict[str, tuple[str, tuple[int, ...]]]] = {
    "design": ("project/canvas.json", (3,)),
    "slides": ("project/deck.json", (4, 5)),
    "design-system": ("project/design-system.json", (3,)),
}
ARTIFACT_STORE_KINDS: Final = {
    "dashboard": "Data dashboards keep their content in the artifact database; use `db`.",
    "whiteboard": "Whiteboards keep their content in the artifact database; use `db`.",
    "docs": "Docs keep their content in the Claude Docs connector; this CLI creates and reads them.",
    "sheets": "Sheets keep their content in the Claude Docs connector; this CLI creates and reads them.",
}
ARTIFACT_KINDS_WITH_DESIGN_SYSTEMS: Final = frozenset({"design", "slides"})
ARTIFACT_TYPE_OWNED_PATHS: Final = ("index.html", "SKILL.md", "artifact-type/")

ARTIFACT_TEXT_CONTENT_TYPES: Final = {
    "html": "text/html",
    "htm": "text/html",
    "json": "application/json",
    "css": "text/css",
    "js": "text/javascript",
    "mjs": "text/javascript",
    "md": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "svg": "image/svg+xml",
    "xml": "application/xml",
}
ARTIFACT_ASSET_CONTENT_TYPES: Final = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "pdf": "application/pdf",
    "woff2": "font/woff2",
    "woff": "font/woff",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "csv": "text/csv",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "json": "application/json",
    "txt": "text/plain",
    "ts": "text/plain",
    "css": "text/css",
    "js": "text/javascript",
    "mjs": "text/javascript",
    "cjs": "text/javascript",
}
ARTIFACT_MAX_ASSET_BYTES: Final = 20 * 1024 * 1024
ARTIFACT_MAX_SVG_ASSET_BYTES: Final = 2 * 1024 * 1024
ARTIFACT_ASSET_LIST_LIMIT: Final = 50
ARTIFACT_MAX_ASSET_COPY: Final = 10
ARTIFACT_ASSET_UPLOAD_TIMEOUT_SECONDS: Final = 120
ARTIFACT_MAX_COMMENT_BYTES: Final = 4096
ARTIFACT_DB_LEVELS: Final = ("view", "interact", "admin")
ARTIFACT_DB_QUERY_OPERATORS: Final = {
    "eq": "eq",
    "ne": "ne",
    "in": "in",
    "not-in": "not-in",
    "lt": "lt",
    "lte": "lte",
    "gt": "gt",
    "gte": "gte",
    "array-contains": "array-contains",
    "==": "eq",
    "!=": "ne",
    "<": "lt",
    "<=": "lte",
    ">": "gt",
    ">=": "gte",
}
ARTIFACT_DB_MAX_PATH_BYTES: Final = 1000
ARTIFACT_DB_MAX_LIMIT: Final = 1000
ARTIFACT_DB_MAX_BATCH: Final = 50
ARTIFACT_DB_MAX_BATCH_BYTES: Final = 1024 * 1024
ARTIFACT_DB_MAX_WHERE: Final = 10
ARTIFACT_SHARE_MODES: Final = ("private", "org", "people", "public")
ARTIFACT_SHARE_ACCESS: Final = ("view", "comment")
ARTIFACT_MAX_PROFILE_IDS: Final = 64
ARTIFACT_MAX_DIAGNOSTIC_BYTES: Final = 128 * 1024

ARTIFACT_RENDER_WIDTHS: Final = (1280, 390)
ARTIFACT_RENDER_MAX_WIDTHS: Final = 4
ARTIFACT_RENDER_THEMES: Final = ("light", "dark")
ARTIFACT_RENDER_TIMEOUT_SECONDS: Final = 60
ARTIFACT_RENDER_DEFAULT_HEIGHT: Final = 900
ARTIFACT_RENDER_MAX_HEIGHT: Final = 8000
ARTIFACT_RENDER_SETTLE_MS: Final = 6000
ARTIFACT_RENDER_RUNTIME_PATH: Final = "artifact-type/dc-runtime.js"
ARTIFACT_RENDER_ALLOWED_HOSTS: Final = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "code.jquery.com",
)
ARTIFACT_RENDER_BROWSER_ENV: Final = "OPEN_CLAUDE_ARTIFACTS_BROWSER"
LEGACY_RENDER_BROWSER_ENV: Final = "OPEN_CLAUDE_DESIGN_BROWSER"
ARTIFACT_RENDER_BROWSERS: Final = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)

SUPPORTED_PLATFORM_LABELS: Final = ("macOS", "Linux", "WSL2")
FEATURED_AGENT_IDS: Final = (
    "claude-code",
    "codex",
    "opencode",
    "cursor",
    "github-copilot",
    "gemini-cli",
    "antigravity",
    "antigravity-cli",
    "cline",
    "kimi-code-cli",
    "kiro-cli",
    "pi",
    "mistral-vibe",
    "hermes-agent",
    "reasonix",
    "trae",
    "grok",
    "qoder",
    "rovodev",
    "openclaw",
    "warp",
    "zed",
    "amp",
)
SUPPORTED_AGENT_IDS: Final = (
    "adal",
    "aider-desk",
    "amp",
    "antigravity",
    "antigravity-cli",
    "astrbot",
    "augment",
    "autohand-code",
    "bob",
    "claude-code",
    "cline",
    "codearts-agent",
    "codebuddy",
    "codemaker",
    "codestudio",
    "codex",
    "command-code",
    "continue",
    "cortex",
    "crush",
    "cursor",
    "deepagents",
    "devin",
    "dexto",
    "droid",
    "eve",
    "firebender",
    "forgecode",
    "fx",
    "gemini-cli",
    "github-copilot",
    "goose",
    "grok",
    "hermes-agent",
    "iflow-cli",
    "inference-sh",
    "jazz",
    "junie",
    "kilo",
    "kimchi",
    "kimi-code-cli",
    "kiro-cli",
    "kode",
    "lingma",
    "loaf",
    "mcpjam",
    "minimax-code",
    "mistral-vibe",
    "moxby",
    "mux",
    "neovate",
    "ona",
    "openclaw",
    "opencode",
    "openhands",
    "pi",
    "pochi",
    "posit-assistant",
    "promptscript",
    "qoder",
    "qoder-cn",
    "qwen-code",
    "reasonix",
    "replit",
    "roo",
    "rovodev",
    "sarvam-code",
    "tabnine-cli",
    "terramind",
    "tinycloud",
    "trae",
    "trae-cn",
    "universal",
    "warp",
    "windsurf",
    "zcode",
    "zed",
    "zencoder",
    "zenflow",
)
PROJECT_ONLY_AGENT_IDS: Final = frozenset({"eve", "promptscript"})
MAX_AGENT_VERIFY_WORKERS: Final = 4
SKILL_NAMES: Final = (
    "open-claude-design-quality",
    "open-claude-ui-design",
    "open-claude-design-system",
    "open-claude-ui-review",
    "open-claude-artifacts",
)
SKILLS_CLI_PACKAGE: Final = "skills"
SKILLS_CLI_VERSION: Final = "1.7.0"
SKILLS_CLI_NODE_MINIMUM: Final = (22, 20, 0)
SKILLS_CLI_NODE_VERSION: Final = "22.20.0"
SKILLS_CLI_NODE_RUNTIME_PARTS: Final = (".local", "share", PACKAGE_NAME, "node")
INSTALL_SCOPES: Final = ("project", "global")
DEFAULT_INSTALL_SCOPE: Final = "global"
CLAUDE_CONFIG_ENV: Final = "CLAUDE_CONFIG_DIR"
CLAUDE_CONFIG_DIRNAME: Final = ".claude"
