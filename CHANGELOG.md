# Changelog

All notable changes to Open Claude Design are documented here. Releases follow semantic versioning and are generated from conventional commits.

## [1.1.1](https://github.com/maxritter/open-claude-design/compare/v1.1.0...v1.1.1) (2026-08-31)

### Fixed

- Login no longer fails with HTTP 403: Cloudflare on `platform.claude.com` began rejecting Python's default urllib User-Agent, so OAuth token and refresh requests now identify themselves as `open-claude-design/<version>`.
- macOS credential storage is no longer silently truncated: the Keychain write previously fed the credential through `security`'s interactive password prompt, which caps input at 128 bytes and corrupted the stored JSON while still exiting 0. The credential now travels on a `security -i` stdin command line, keeping it out of process argv and intact at any length.

## [1.1.0](https://github.com/maxritter/open-claude-design/compare/v1.0.2...v1.1.0) (2026-08-31)

### Added

- Revision-bound two-way synchronization with automatic review receipts, local content hashes, remote etags, verified baselines, and stale-approval rejection before mutation.
- First-use desktop authentication without install-time coupling, plus a fail-closed manual flow for CI, SSH, and headless dev containers that keeps authorization codes out of agent chat.
- Local-only Git exclusion for generated sync receipts and snapshots, preventing status noise without editing a repository's tracked `.gitignore`.
- A real Claude Design editor screenshot in the README so new users can see the visual workspace before installing.

### Security

- Approved sync batches are all-or-nothing, detect file creation, deletion, and concurrent revision changes, keep snapshots worktree-local, and cannot be replayed after completion or an ambiguous outcome.

## [1.0.2](https://github.com/maxritter/open-claude-design/compare/v1.0.1...v1.0.2) (2026-08-31)

### Added

- `uninstall.sh --scope project|global` so project-scoped skill installs can be removed; the Agent Skills fallback now honors the selected scope.
- Shell-profile PATH guidance after installation when the login shell would not resolve `open-claude-design`.
- Members, sharing, and conversation-sync workflow guidance in the `open-claude-design` skill, grounded in the live tool contracts.

### Fixed

- The uninstaller reports honestly when skill removal could not be confirmed instead of always printing success, skips the network fallback when the CLI already removed the skills, and cleans the credential-lock directory on macOS as well as Linux.
- `install.sh --dry-run` no longer claims workflows were installed.
- The installer and uninstaller strip forced ANSI color (`FORCE_COLOR`/`CLICOLOR_FORCE`, exported by `uv run` and some CI systems) from captured `uv tool dir --bin` output, which previously aborted installation with "uv returned an invalid tool executable directory".
- The release-manifest wheel filter rejects path separators, so a tampered `SHA256SUMS` cannot direct downloads outside the staging directory.

### Security

- CI now runs the full pre-commit hook set (including private-key detection) and tests Python 3.12 and 3.13; the shell quality gate covers every repository script.


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
