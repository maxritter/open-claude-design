# Changelog

All notable changes to Open Claude Design are documented here. Releases follow semantic versioning and are generated from conventional commits.

## [1.6.0](https://github.com/maxritter/open-claude-design/compare/v1.5.0...v1.6.0) (2026-10-09)

### Added

- Offline `migration status` and `migration resolve` commands distinguish standalone projects from Claude artifact URLs. `migration check` reads one standalone inventory and reports preservation limits while leaving migration eligibility to Anthropic's checker.
- `export --include-history` preserves project metadata, chats, and comments alongside files in a private ZIP. It redacts known credentials and render capabilities, verifies files and history again before saving, and refuses incomplete transcripts or observed concurrent changes.

### Changed

- Status and capabilities identify the standalone backend and its announced December 14, 2026 closure. Selecting `--backend artifact` returns an explicit unsupported result without authentication. Project helpers accept standalone URLs and reject artifact URLs instead of passing them to the standalone service.
- Agent guidance describes the organization-wide migration, separate original and migrated copies, and preservation before closure. Artifact authoring remains unimplemented pending a verified portable interface.

## [1.5.0](https://github.com/maxritter/open-claude-design/compare/v1.4.1...v1.5.0) (2026-10-05)

### Added

- `project live <project-id> [--open]` returns the project's `?embed=1` window, built from the URL `get_project` returns. Claude Design refreshes it on every write, so the user can watch a design land while the agent works. Read-only.
- Validation now enforces the editor contract that Claude Design's live authoring prompt states. A template hole must be a dotted lookup or a literal (`{{ count + 1 }}` fails silently at render), a component mounts through `dc-import` rather than a capitalized tag, and every non-void element inside the template closes explicitly. `push` refuses a Design Component that breaks any of these.
- Non-blocking `warnings` for a control-flow or import element placed directly under `deck-stage`, `scrollIntoView`, and a design without `a`/`a:hover` colors. Validation also reports `editor_overrides` and `comment_anchors`, so an agent implementing a design in code applies the rules the user made by direct editing.

### Changed

- `--open` on `preview`, `push`, `planned-call`, and `sync apply` now opens the durable `claude.ai/design` editor link. It used to open the short-lived render URL, which carries a project-scoped token, stays in browser history, and stops working minutes later.

### Fixed

- `push` no longer refuses files Claude Design writes itself. A static Design Component without a logic script, a logic script marked `type="text/plain"`, and self-closing SVG children such as `<path/>` are all accepted. A check of 87 Design Components across live projects now reports no false refusals.
- Pushed SVG, JPEG, and WebP files verify again. Claude Design adds C2PA provenance on read and re-serializes SVG on write, so readback reported `verified: false` for files that had landed intact. Raster files are now compared after removing exactly one provenance block against the stored byte count (`readback: exact`). SVG is compared as canonical XML without the embedded manifest (`readback: svg-equivalent`). Anything ambiguous still fails closed.
- The tool-workflows reference now says that `create_project` without `design_system_id` binds the organization default design system, and that `project bind --clear` removes it.

## [1.4.1](https://github.com/maxritter/open-claude-design/compare/v1.4.0...v1.4.1) (2026-10-01)

### Fixed

- Pages written below the project root were reported as verified although Claude Design's editor never lists them. The Pages menu shows only root-level `.html` and `.dc.html` files, so a page pushed to a folder rendered by direct link, passed readback and the durable-preview check, and left the user with an empty Pages menu and a blank canvas. `push`, `planned-call` (`copy_files`, including every leaf of a folder copy, and `create_support_js`), `sync review` and `sync apply` to design, and generic calls of newly advertised file-writing tools now refuse a nested page before any remote call and name the root path to use. `--allow-nested-page` is the explicit opt-out for a page the user wants kept out of the menu.
- Every verification preview now reports `page_listed`. A written nested page makes `verification.verified` false (exit `2`) with `nested_pages` and the root path to use, unless the opt-out was given, in which case verification passes with a `warning`. `preview` on a nested page stays read-only but returns `page_listed: false` and a warning.
- The tool-workflows reference told agents that root-level and nested `.dc.html` paths were equally complete and not to flatten a design to make it visible. It now states the rule: pages at the project root, assets in subfolders.

### Added

- `project pages <project-id>` is a read-only audit that lists listed and nested pages, a suggested root path for each nested page (folder-prefixed when the plain name is taken), and whether root `support.js` exists. It exits `2` when any page is nested.

## [1.4.0](https://github.com/maxritter/open-claude-design/compare/v1.3.1...v1.4.0) (2026-09-30)

### Added

- First-party API access through the existing scoped login: native design-system creation, complete typed inventory, publication/unpublication, preview-card registration/removal, organization-default management, project renaming, binding inspection and replacement (including multiple systems), and guarded whole-project deletion.
- Original text and binary transfers up to 16 MiB, 32 MiB write/sync batches, and revision-checked project ZIP exports up to 128 MiB with a checksum manifest. Read-added PNG provenance is reconciled against original size/revision metadata; ambiguous reconstruction fails closed.
- Portable HTML structure, JavaScript syntax, declared-resource, and API preview-delivery checks without browser control. Validation reports that JavaScript/layout execution remains outside these checks.
- Read-only batches sharing one MCP session/catalog, bounded transient-read retries, automatic single-binding authoring context, and local serialization of temporary project grants.
- The pinned skills adapter is updated to 1.7.0. All-agent checks cover all 79 supported identifiers (77 global integrations; Eve and PromptScript require project scope), using bounded parallel verification.

### Fixed

- Partial/windowed file responses can no longer be saved as full files, sync snapshots, or deletion backups.
- Folder copies require a complete source-leaf etag map before planning; nested conflicts and missing copied leaves cannot report verified success.
- Binary writes and synchronization require complete original-byte readback. Large and binary to-code sync reuses revision-checked immutable snapshots.
- Complete project discovery supplies the required type filter for each native API inventory instead of issuing an invalid unfiltered request.
- Non-editable Design Component structure and invalid logic-script syntax are rejected before a write. Preview verification checks the actual API-issued response and reports its precise scope.
- Collaboration guidance follows current destructive annotations, and standalone versus in-conversation Design availability and settings are distinguished.

### Safety and boundaries

- New metadata grants require explicit acknowledgement, are revoked and checked after success or failure, and preserve pre-existing grants. Organization defaults update only the reviewed default field; sharing restrictions remain untouched.
- File mutations retain atomic server etag protection. Metadata preflight/readback checks and local locks do not claim cross-device atomicity.
- Browser-only artifact migration/sharing and native PDF/PPTX/Google Slides export are not advertised as supported APIs. Design-system compilation remains distinct from publication.

## [1.3.1](https://github.com/maxritter/open-claude-design/compare/v1.3.0...v1.3.1) (2026-09-18)

### Fixed

- The design-system guidance no longer treats `list_design_systems` as a complete inventory. It can omit design-system projects the user owns, and `list_projects` carries no type, so agents confirm a named system with `get_project` before reporting that it does not exist.
- `install.sh --help` installed the CLI and then forwarded `--help` to the skill installer, which printed its help, exited 0, and installed nothing while the installer reported "installed and verified". Help is now answered before any step runs, and the installer reports success only when the skill step returns an install result.

## [1.3.0](https://github.com/maxritter/open-claude-design/compare/v1.2.3...v1.3.0) (2026-09-18)

### Added

- The design-system skill can package an extracted system for Claude Design (`references/claude-design-package.md`): the `PROJECT_TYPE_DESIGN_SYSTEM` destination and how to confirm it, the authored layout (`styles.css`, `tokens/`, `components/`, preview cards, `readme.md`, `SKILL.md`), the first-line `@dsCard` marker that indexes a preview card, the files Claude Design compiles and an agent must never write, and the compiled manifest as the acceptance check.
- The Claude Design skill documents design-system projects: the project type is fixed at creation, `create_project` makes regular projects only, the compiled manifest is the cheapest inventory, and a change to a published system reaches every bound project.

### Changed

- Comment handling follows the current Claude Design contract: `queued_for_claude: true` fetches only the "Send to Claude" queue, its interaction with `changed_since` is spelled out, and `author_is_you` is judged per comment body and per reply rather than per thread.
- `create_project` guidance resolves the design system before the call, using `is_default` from `list_design_systems` for the user's standard system.
- The skill states that the project-wide `finalize_plan` scope and the token-less standing write grant are deliberately unused; every helper keeps minting exact-path, etag-checked plans.
- `pages_written` from `write_files` and `copy_files` is documented as the page to link when a batch mixes pages with support files, and a test pins `push` against the live write result shape.

## [1.2.3](https://github.com/maxritter/open-claude-design/compare/v1.2.2...v1.2.3) (2026-09-16)

### Fixed

- Public installs now record the durable `releases/latest/download/open-claude-design.tar.gz` source in uv instead of the installer's deleted staging wheel, so `uv tool upgrade open-claude-design` can resolve future releases. Explicit local package installs are copied into persistent package-owned storage rather than leaving a dead temporary-path receipt.

## [1.2.2](https://github.com/maxritter/open-claude-design/compare/v1.2.1...v1.2.2) (2026-09-16)

### Fixed

- A native Claude Design connector registered by the host agent (for example an `mcpServers` entry pointing at the Claude Design endpoint) authenticates with the host account's own token, which carries no Claude Design scope. It fails with HTTP 403 and makes the agent report Claude Design as unavailable while the bridge is healthy. `doctor` now reports those entries under `native_connectors` with the file, entry, and removal step, `install`, `update`, and the one-line installer surface the same report when one is registered, and the Claude Design skill treats a failing connector as a host-configuration fault rather than evidence that Claude Design is down.
- HTTP 403 from Claude Design no longer advises a login that cannot succeed. 401 still means the credential is invalid or expired and a fresh `login` fixes it; 403 now says the account was accepted but has no Claude Design access, so it must be enabled for that account or a different account used.
- `doctor --json` reported `"authentication": "not checked"` even when it had just verified the credential. The field is now `verified`, `failed`, or `not checked`.

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
