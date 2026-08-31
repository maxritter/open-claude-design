# Security

Please report vulnerabilities privately to `mail@maxritter.net`. Do not open a public issue for credential exposure, path traversal, authorization bypass, or remote-write findings.

## Security properties

- Standalone OAuth credentials are stored in a dedicated macOS Keychain item or a current-user-owned Linux/WSL2 file with mode 0600. Claude Code's existing credential remains a read-only compatibility fallback.
- Authenticated HTTP requests never follow redirects.
- MCP responses are size-bounded and bound to the exact JSON-RPC request id; paginated discovery has page, item, and repeated-cursor limits.
- Remote mutation requires local tool classification, explicit write authorization, current etags, and structured success evidence bound to the requested project and paths. Unknown live tools are treated as possible mutations regardless of their remote annotation.
- Approval-bound synchronization records a worktree-local revision receipt, revalidates every mapped etag and content hash before mutation, rejects stale batches without partial writes, and consumes the receipt only after verification.
- Generated sync receipts and snapshots are excluded through Git's local `info/exclude`; Open Claude Design never edits the repository's tracked `.gitignore` for runtime state.
- Local file operations reject symlink escapes and default to the current Git worktree.
- Capability-bearing operations use guarded one-process helpers; plan tokens and short-lived preview URLs are redacted from output.
- Generic remote deletion is disabled. Guarded deletion requires exact path confirmation, current etags, recovery backups, canonical paths, and post-delete absence verification.
- Install and uninstall select only collision-resistant `open-claude-*` skill names and the Open Claude Design-managed runtime. Final agent-specific lifecycle semantics remain owned by the maintained Agent Skills installer.
- The one-line bootstrap is delivered over GitHub HTTPS; the installer then verifies pinned uv and Node archives plus the release wheel before installation.
- CI runs Trivy vulnerability, secret, and workflow-misconfiguration scanning, CodeQL, pull-request dependency review, pinned-action validation, and release artifact provenance. Release Please creates draft releases; publication occurs only after the full build, test, shell, and security gates pass.

Reports should include the affected version, platform, reproduction steps, and whether a real credential or remote project was involved. Redact all tokens and private project content.
