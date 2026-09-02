# Changelog

All notable changes to Open Claude Design are documented here. Releases follow semantic versioning and are generated from conventional commits.

## [1.2.1](https://github.com/maxritter/open-claude-design/compare/v1.2.0...v1.2.1) (2026-09-02)

### Added

- Live authoring in the Claude Design skill: a request to create or change a design in Claude Design authorizes the task's writes, and the agent publishes at checkpoints (the first clean draft, each round that changes what the user would notice, and before pausing) so the design evolves in the editor instead of waiting for a push instruction. Each round's small corrections fold into one write.
- An agent-facing design-system package output in the design-system skill (`references/agent-spec.md`): a project-local skill with provenance, signature traits, critical rules, a module index, and per-component specs, so an extracted system governs later UI work automatically.
- Layout patterns for common marketing, application, and commerce surfaces (`references/layout-patterns.md`) and six greenfield aesthetic directions (`references/directions.md`) in the UI design skill, routed from the skill and its discovery reference.

### Changed

- The UI design skill builds multi-section pages one checked section at a time instead of reviewing once at the end.

## [1.2.0](https://github.com/maxritter/open-claude-design/compare/v1.1.2...v1.2.0) (2026-09-02)

### Added

- `sync apply --reconciled`: a `both-changed` review no longer overwrites the design with the local bytes on `--allow-write` alone. The flag acknowledges that the remote changes were merged into the local files the user approved.
- `sync review` records an observed match as the baseline when a mapped pair has no baseline yet but both sides already hold identical bytes (`baseline_recorded: true`), instead of requesting approval for a no-op remote write.
- The `open-claude-design-quality` skill ships `references/craft.md`: measurable defaults for type, spacing, controls, color, and imagery with an explicit precedence below accessibility and the product's own tokens.

### Fixed

- Every `push`, `sync apply`, `pull`, and `delete` readback failed by one byte: Claude Design appends a newline before its `</untrusted-project-content>` wrapper and the bridge only stripped the leading one, so 1.1.2 exited 2 without a preview after each otherwise successful write.
- `delete` exited 2 and reported the files as remaining although Claude Design had deleted them, because the live `delete_files` result is `{"deleted": N}`. The parent listing is now the ground truth whenever the tool did not error, and a failed backup read names the path.
- The Claude Design skill described the live `frontend-design` skill as implementation-oriented output; it is aesthetic direction for work outside any design system and is no longer loaded inside an established system. Selected design options now stay in the exploration file and are promoted into a separate deliverable, as the live `hifi-design` skill requires.

### Changed

- The Claude Design skill also triggers on `.dc.html` files, offers the durable `?embed=1` live window, rebases on etag conflicts, and documents that `planned-call create_support_js` needs `if_match`.
- The UI design skill merges its scope guidance into one section and adds craft defaults for a new visual direction.

## [1.1.2](https://github.com/maxritter/open-claude-design/compare/v1.1.1...v1.1.2) (2026-08-31)

### Fixed

- Design creation now fails closed when a `.dc.html` file has no same-directory server-provided `support.js`, when exact post-write readback differs, or when Claude Design cannot produce a durable preview. Successful `push`, `copy_files`, and code-to-design sync results include verified preview URLs; `--open` additionally opens the isolated render without exposing its short-lived URL.
- Agent skill installation and updates now perform a second byte-for-byte readback for every requested agent after the skills backend reports success, preventing one valid integration from masking a partial, stale, or missing one.
- Release wheels contain only runtime skill files; benchmark `tests/evals.json` payloads are excluded and the build now fails if they reappear.

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
