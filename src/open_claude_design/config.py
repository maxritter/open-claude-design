"""Central configuration for the Open Claude Design package."""

from __future__ import annotations

from typing import Final

PACKAGE_NAME: Final = "open-claude-design"
VERSION: Final = "1.2.1"

CLAUDE_DESIGN_ENDPOINT: Final = "https://api.anthropic.com/v1/design/mcp"
CLAUDE_DESIGN_OAUTH_AUTHORIZE_URL: Final = "https://claude.com/cai/oauth/authorize"
CLAUDE_DESIGN_OAUTH_TOKEN_URL: Final = "https://platform.claude.com/v1/oauth/token"
CLAUDE_DESIGN_OAUTH_CLIENT_ID: Final = "59637612-477b-4836-a601-b0589eda7704"
CLAUDE_DESIGN_OAUTH_USER_AGENT: Final = f"{PACKAGE_NAME}/{VERSION}"
CLAUDE_DESIGN_OAUTH_MANUAL_REDIRECT_URL: Final = "https://platform.claude.com/oauth/code/callback"
CLAUDE_DESIGN_OAUTH_SUCCESS_URL: Final = "https://platform.claude.com/oauth/code/success?app=claude-code"
CLAUDE_DESIGN_BROWSER_LOGIN_ENV: Final = "OPEN_CLAUDE_DESIGN_BROWSER_LOGIN"
CLAUDE_DESIGN_OAUTH_SCOPES: Final = ("user:design:read", "user:design:write")
CLAUDE_DESIGN_OAUTH_TIMEOUT_SECONDS: Final = 5 * 60
CLAUDE_DESIGN_OAUTH_REFRESH_MARGIN_SECONDS: Final = 2 * 60
CLAUDE_DESIGN_OAUTH_RESPONSE_MAX_BYTES: Final = 1024 * 1024
CLAUDE_DESIGN_STANDALONE_KEYCHAIN_SERVICE: Final = "Open Claude Design-credentials"
CLAUDE_DESIGN_STANDALONE_KEYCHAIN_ACCOUNT: Final = "open-claude-design"
CLAUDE_DESIGN_STANDALONE_CREDENTIAL_PARTS: Final = (".config", "open-claude-design", "credentials.json")
CLAUDE_DESIGN_DURABLE_PREVIEW_HOSTS: Final = frozenset({"claude.ai", "www.claude.ai"})
CLAUDE_DESIGN_SERVE_PREVIEW_HOST_SUFFIX: Final = "claudeusercontent.com"
CLAUDE_DESIGN_PROTOCOL_VERSION: Final = "2025-11-25"
CLAUDE_DESIGN_HTTP_TIMEOUT_SECONDS: Final = 30
CLAUDE_DESIGN_MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
CLAUDE_DESIGN_MAX_SSE_EVENTS: Final = 64
CLAUDE_DESIGN_MAX_TOOL_PAGES: Final = 64
CLAUDE_DESIGN_MAX_TOOLS: Final = 4096
CLAUDE_DESIGN_KEYCHAIN_SERVICE: Final = "Claude Code-credentials"
CLAUDE_DESIGN_CREDENTIAL_MAX_BYTES: Final = 1024 * 1024
CLAUDE_DESIGN_MAX_INLINE_FILE_BYTES: Final = 256 * 1024
CLAUDE_DESIGN_MAX_BATCH_FILES: Final = 64
CLAUDE_DESIGN_MAX_BATCH_BYTES: Final = 4 * 1024 * 1024
CLAUDE_DESIGN_MAX_STDIN_BYTES: Final = 1024 * 1024
CLAUDE_DESIGN_MAX_PLAN_TOKEN_BYTES: Final = 16 * 1024
CLAUDE_DESIGN_MIN_WRITE_CREDENTIAL_SECONDS: Final = 5 * 60
CLAUDE_DESIGN_AUTHORING_CACHE_TTL_SECONDS: Final = 60 * 60
CLAUDE_DESIGN_AUTHORING_CACHE_PARTS: Final = (".open-claude-design", "authoring-context")
CLAUDE_DESIGN_SYNC_PARTS: Final = (".open-claude-design", "sync")
CLAUDE_DESIGN_SYNC_SCHEMA_VERSION: Final = 1
CLAUDE_DESIGN_MAX_SYNC_DIFF_BYTES: Final = 4 * 1024 * 1024
CLAUDE_DESIGN_SYNC_UNKNOWN_EXIT_CODE: Final = 2
CLAUDE_DESIGN_SYNC_STALE_EXIT_CODE: Final = 3
CLAUDE_DESIGN_NON_MUTATING_GUARDED_TOOLS: Final = frozenset()
CLAUDE_DESIGN_KNOWN_READ_ONLY_TOOLS: Final = frozenset(
    {
        "get_claude_design_prompt",
        "get_conversation",
        "get_project",
        "list_comments",
        "list_design_systems",
        "list_files",
        "list_members",
        "list_projects",
        "read_design_skill",
        "read_file",
    }
)
CLAUDE_DESIGN_KNOWN_MUTATING_TOOLS: Final = frozenset(
    {
        "ack_comments",
        "add_member",
        "copy_files",
        "create_project",
        "create_support_js",
        "delete_files",
        "finalize_plan",
        "put_conversation",
        "remove_member",
        "update_member_role",
        "update_sharing",
        "write_files",
    }
)
CLAUDE_DESIGN_KNOWN_DESTRUCTIVE_TOOLS: Final = frozenset({"copy_files", "delete_files", "remove_member"})
CLAUDE_DESIGN_SPECIALIZED_ONLY_TOOLS: Final = frozenset(
    {"copy_files", "create_support_js", "delete_files", "finalize_plan", "render_preview", "write_files"}
)
CLAUDE_DESIGN_MUTATION_SUCCESS_KEYS: Final = {
    "ack_comments": frozenset({"acked", "acknowledged", "not_queued"}),
    "add_member": frozenset({"account", "member", "member_id", "role"}),
    "create_project": frozenset({"project_id", "url"}),
    "delete_files": frozenset({"deleted"}),
    "put_conversation": frozenset({"chat_id", "next_idx"}),
    "remove_member": frozenset({"removed"}),
    "update_member_role": frozenset({"member", "member_id", "role"}),
    "update_sharing": frozenset({"link_role", "link_scope", "sharing"}),
}

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
SKILL_NAMES: Final = (
    "open-claude-design-quality",
    "open-claude-ui-design",
    "open-claude-design-system",
    "open-claude-ui-review",
    "open-claude-design",
)
SKILLS_CLI_PACKAGE: Final = "skills"
SKILLS_CLI_VERSION: Final = "1.5.23"
SKILLS_CLI_NODE_MINIMUM: Final = (22, 20, 0)
SKILLS_CLI_NODE_VERSION: Final = "22.20.0"
SKILLS_CLI_NODE_RUNTIME_PARTS: Final = (".local", "share", PACKAGE_NAME, "node")
BRIDGE_COMMAND_NAMES: Final = (
    "status",
    "authoring-context",
    "tools",
    "describe",
    "call",
    "planned-call",
    "preview",
    "files",
    "pull",
    "push",
    "delete",
    "sync",
)
INSTALL_SCOPES: Final = ("project", "global")
DEFAULT_INSTALL_SCOPE: Final = "global"
DEFAULT_FILE_LIST_DEPTH: Final = 1
CLAUDE_CONFIG_ENV: Final = "CLAUDE_CONFIG_DIR"
CLAUDE_CONFIG_DIRNAME: Final = ".claude"
