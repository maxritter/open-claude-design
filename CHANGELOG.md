# Changelog

All notable changes to Open Claude Design are documented here. Releases follow semantic versioning and are generated from conventional commits.

## [1.0.2](https://github.com/maxritter/open-claude-design/compare/v1.0.1...v1.0.2) (2026-08-30)


### Documentation

* sharpen product workflow positioning ([e385007](https://github.com/maxritter/open-claude-design/commit/e385007e8ca09eaff1c99c5a3064c7c4c8bb3b91))

## [1.0.1](https://github.com/maxritter/open-claude-design/compare/v1.0.0...v1.0.1) (2026-08-30)


### Bug Fixes

* preserve streamed installer input ([68102b3](https://github.com/maxritter/open-claude-design/commit/68102b3c6c95c381d910f7604b06e15101c38b3e))

## 1.0.0 - 2026-08-30

### Added

- Five portable, implicitly invoked design skills for product UI creation, design-system extraction, review, and Claude Design access.
- One Agent Skills compatibility layer for Claude Code, Codex, OpenCode, and every supported host.
- A read-only-by-default Claude Design bridge for macOS, Linux, and WSL2 with standalone browser OAuth—no Claude Code installation or Anthropic API key required.
- Conflict-aware pull and push, guarded deletion with recovery backups, durable previews, project conversations, comments, members, sharing, and dynamic live-tool discovery.
- A cached authoring-context command that retrieves the current project prompt and one selected Claude Design authoring skill through one MCP session without dumping either into terminal output.
- Branded POSIX install and uninstall scripts with checksummed private runtime setup and a one-line GitHub Release installer.

### Security

- Exact-path etag plans, bounded MCP responses, redirect refusal, credential-safe storage, symlink-resistant local I/O, write-expiry preflights, and post-mutation verification.
- Byte-level installed-skill verification and no-op reinstalls that avoid interrupting active coding agents.
- Pinned GitHub Actions, Trivy, CodeQL, dependency review, pre-commit secret/private-key checks, checksummed artifacts, and build provenance attestations.
