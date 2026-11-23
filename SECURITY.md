# Security

Report vulnerabilities privately to `mail@maxritter.net`. Do not open a public issue for credential exposure, path traversal, authorization bypass, or remote-write bugs.

## Security properties

- **Isolated OAuth credentials:** Stored in a dedicated macOS Keychain item (`Open Claude Artifacts-credentials`) or a current-user-owned Linux/WSL2 file under `~/.config/open-claude-artifacts/credentials.json` with mode `0600`. Existing `open-claude-design` artifact credentials are read as a migration fallback.
- **No redirects on authenticated requests:** Token exchange and artifact API calls reject HTTP redirects so credentials never cross origins.
- **Bounded network responses:** All JSON, file, asset, and diagnostic responses enforce explicit byte and page limits.
- **Explicit mutation gates:** Every remote write requires `--allow-write`. File pushes pin current SHA-256 preconditions (`--if-match`) and verify byte-for-byte readback; database updates to existing documents pin `--if-version`. Deletions also require `--allow-destructive` (plus `--confirm` for whole artifacts); public sharing requires `--allow-public`.
- **Conflict-aware code sync:** `sync review` writes a local SHA-256-sealed receipt and immutable snapshots. `sync apply` revalidates local and remote revisions before writing and aborts with exit code `3` if either side drifted.
- **Clean repositories:** Context caches, render images, and sync receipts live under `.open-claude-artifacts/` and are ignored via `.git/info/exclude`, never by modifying tracked `.gitignore` files.
- **Symlink-safe local I/O:** Local reads and writes default to the current Git worktree, traverse directories using `O_NOFOLLOW` pinned file descriptors, and reject external paths without explicit `--allow-external-local-path`.
- **Redacted capability tokens:** Short-lived frame content URLs and `assetToken` values are stripped from all CLI output. Only durable `https://claude.ai/code/artifact/<id>` URLs are returned or opened.
- **Isolated local rendering:** Headless Chromium runs with a throwaway profile and `--host-resolver-rules` blocking all network hosts outside `127.0.0.1` and the artifact CDN allowlist.
- **Verified release supply chain:** CI runs Trivy (vulnerabilities, secrets, misconfigurations), CodeQL, dependency review, pinned GitHub Actions checks, and SLSA build provenance attestations. Publication requires manual approval on the `release` environment.

Include the affected version, platform, and reproduction steps in your report, and redact all tokens and private artifact content.
