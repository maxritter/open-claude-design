# Standalone to Claude Artifacts

Anthropic [announced](https://support.claude.com/en/articles/17440474-migrate-from-standalone-claude-design-to-claude) that standalone Claude Design closes on December 14, 2026. New designs and design systems live in Claude as artifacts. The CLI retains standalone access and adds experimental native Design artifact workflows through a separate subscription login. Read [artifact workflows](artifacts.md) for the new canvas.

## Choose the correct destination

```bash
open-claude-design migration status --json
open-claude-design migration resolve 'https://claude.ai/code/artifact/<id>' --json
open-claude-design status --backend artifact --json
```

`migration status` and `resolve` are offline and never start authentication. Resolution classifies a URL, strips its query and fragment, and does not verify that the resource exists or that the user can access it. A bare id always means a standalone project. An artifact id must never be copied from its URL and passed as a bare project id.

`status --backend artifact` verifies the live artifact contract with its own credential; `capabilities --backend artifact` separates implemented CLI workflows from server capabilities. Normal `status` verifies standalone access only. Standalone project helpers accept a project id or a `https://claude.ai/design/p/<id>` URL; a URL's `?file=` does not replace a command's explicit file operand. They reject artifact URLs before remote project operations. Within the explicit `artifacts` command group, a bare id means an artifact.

For an artifact request, use `login --backend artifact` and the dedicated artifact commands. Never substitute a standalone project, scrape another application's credentials, probe guessed endpoints, or use browser automation to imitate an API. Browser inspection verifies the actual canvas after a CLI write; it is not the transport. Do not invoke Claude Code as a subprocess to make a transport available to other agents. See [Anthropic's artifact documentation](https://code.claude.com/docs/en/artifacts) for native account and organization requirements.

## Inspect standalone readiness

```bash
open-claude-design migration check <project-id-or-url> --json
```

This reads one project's metadata and file inventory. It reports known bytes, missing size metadata, `uploads` files worth reviewing, and files outside the CLI's transfer/export limits. These limits are **not artifact migration limits**. It reads no file bodies and makes no changes. A successful exit means the diagnostic ran, not that migration is possible. `migration_verified` remains false and `host_check_required` remains true.

Use Anthropic's migration checker to decide accepted names, file types, encoding, size, theme origin, and organization permissions. Empty design systems and systems originating from built-in starter themes are excluded, even if edited. The CLI can identify an empty inventory but cannot currently verify starter-theme origin or artifact permissions. Existing project-migration instructions remain pending from Anthropic.

Migration from the Artifacts page affects every design system in the organization. Published systems that are not private become visible organization-wide on team plans. Require explicit authorization for that migration and its visibility consequences. Original systems stay in standalone; re-migration skips copies edited in Claude. Record which copy the user wants to maintain. Do not promise that a standalone update changes its migrated copy or that an old default-setting command changes Claude's artifact default.

## Preserve files and history

Chats and comments do not migrate. Standalone public links stop working when the site closes. Offer preservation before the deadline, and save a local archive only when requested:

```bash
open-claude-design export <project-id-or-url> \
  --include-history --output .open-claude-design/archives/project.zip --json
```

The existing file-only ZIP export remains available by omitting `--include-history`. History export requires a whole project, so it cannot be combined with `--path`. It adds project metadata, conversations, and the full comment listing under `__open_claude_design_export__/`, with a checksum manifest. Known credential fields and render capabilities are redacted. The archive is private user data: keep it out of source control and do not display its bodies in an agent response.

Files and history are read again before the archive is saved. This detects observed concurrent changes but is not an atomic server snapshot. The helper refuses malformed or truncated history, including transcripts reaching the 256 KiB read cap, and preserves an existing local archive on failure. It does not acknowledge comments or alter chats. Permission errors remain explicit; do not produce a file-only export and call it a complete history archive. For oversized transcripts, use a supported host export or preserve individual chats only when their complete retrieval can be verified; the CLI currently has no paginated transcript interface.

After an authorized migration, confirm files, design-system binding, permissions, and the new durable link in Claude. An export or migration result does not prove that Open Claude Design can read or update the new artifact. Verify that specific link with `artifacts inspect`, then read back its intended files and verify the native canvas. Artifact design-system administration and binding migration remain unimplemented.
