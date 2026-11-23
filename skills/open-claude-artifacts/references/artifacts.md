# Claude Artifacts workflows

Use `open-claude-artifacts` for every Claude artifact: Design canvases, Slides decks, Design System artifacts, Data dashboards, Whiteboards, Docs, Sheets, and plain artifact pages. Assets, comments, the shared database, sharing, and lifecycle commands are in [artifact collaboration](artifact-collaboration.md).

## Connect

```bash
open-claude-artifacts status --json
open-claude-artifacts login
```

The CLI stores its own OAuth credential in macOS Keychain (or `~/.config/open-claude-artifacts/credentials.json` on Linux/WSL2 with `0600` permissions) and seamlessly reads existing `open-claude-artifacts` artifact credentials if present. In headless environments ask the user to run `open-claude-artifacts login --manual` in their own terminal and paste the code there, never into chat.

## Pick the artifact type

| Content | Type | Content model |
|---|---|---|
| Screens, flows, landing pages, posters | `Design` | files: `project/canvas.json` (v3) + `.dc.html` artboards |
| Presentations (16:9 or 4:3) | `Slides` | files: `project/deck.json` (v4/v5) + `project/deck.css` + `project/slides/<id>.html` |
| Brand tokens, components, assets | `Design System` | files: `project/design-system.json` (v3) + `tokens.json` + component previews |
| Dashboards, metrics, KPI reports | `Data` | shared artifact database (`db`) |
| Shared visual thinking boards | `Whiteboard` | shared artifact database (`db`) |
| Editable living documents | `Docs` | Claude Docs connector; this CLI creates and reads them |
| Spreadsheets | `Sheets` | Claude Docs connector; this CLI creates and reads them |
| Anything else that is one page | plain page (no type) | `index.html` + files, optional runtime capabilities |

```bash
open-claude-artifacts list --scope mine|shared|all --json
open-claude-artifacts types --json
open-claude-artifacts type 'Slides' --json
open-claude-artifacts instances 'Design System' --json
open-claude-artifacts inspect '<artifact>' --json
open-claude-artifacts files '<artifact>' [--all] --json
```

An artifact operand is a UUID/slug, a `claude.ai/code/artifact/<id>` URL, or a short share link (`claude.ai/artifact/<22 chars>`). Migrated Design artifacts and plain untyped pages are both readable through `inspect`, `files`, and `pull`.

## Create and load the live guide

```bash
open-claude-artifacts create 'Settings flow' --type Design \
  --idempotency-key '<retained-uuid>' --allow-write --json
open-claude-artifacts authoring-context '<artifact>' [--design-system <system>|none] --json
```

Generate one UUID per creation and reuse it only to reconcile that same creation after an unknown outcome. `authoring-context` downloads the type's current `SKILL.md` and reference docs under `.open-claude-artifacts/context/<id>/` plus `open-claude-artifacts.md` (and for Design/Slides, available design systems and the chosen system's `README.md` + `tokens.json`). Read the live guide before the first write and follow it as written. For plain pages, use `open-claude-artifacts contract [--capability db] --json`.

## Author and publish

- **Typed artifacts write only under `project/`**; the type owns `index.html`, `SKILL.md`, and `artifact-type/`.
- **New indexes carry `"createdOnFiles": {"v": 1, "at": "<now>"}`** (canvas v3, deck v5 with `lists` and `format` + `project/deck.css`, design-system v3 with `"layout": "files"`). Keep every key you do not change on existing indexes.
- **Order:** send the index with the entry artboard or cover slide first; a design system sends its index last.
- **Assets:** Design and Slides upload images/fonts via `assets upload` and reference the returned `/_blob/<id>` verbatim.

```bash
open-claude-artifacts push '<artifact>' \
  --file 'project/canvas.json=<local>' --if-match 'project/canvas.json=0' \
  --file 'project/Main.dc.html=<local>' --if-match 'project/Main.dc.html=0' \
  [--remove 'project/Old.dc.html=<sha256>' --allow-destructive] --allow-write [--open] --json

open-claude-artifacts publish 'Release notes' --page index.html [--file style.css=style.css] \
  [--capabilities '{"db":{},"user":{}}' --contract latest] [--favicon '📈'] --allow-write --json

open-claude-artifacts design-system install '<canvas-or-deck>' '<system>' [--folder acme] --allow-write --json
```

`--if-match` takes the file's current SHA-256 from `files`, or `0` for a new file. Every push pins the artifact version and verifies readback byte-for-byte.

## Render and verify locally (headless Chromium)

```bash
# Design artboards or plain pages (light & dark, custom widths, local drafts before push)
open-claude-artifacts render '<artifact>' [--path project/Main.dc.html] \
  [--local 'project/Main.dc.html=<draft>'] [--width 1280 --width 390] [--theme light] --json

# Slides decks (1920x1080 or 1440x1080, by slide id or 1-based number, local drafts supported)
open-claude-artifacts render '<deck>' [--slide 1 --slide plan-mode] \
  [--local 'project/deck.css=deck.css'] [--local 'project/slides/plan-mode.html=plan-mode.html'] --json

open-claude-artifacts preview '<artifact>' [--open] --json
```

`render` launches local headless Chrome, Chromium, Edge, or Playwright Chromium (`OPEN_CLAUDE_ARTIFACTS_BROWSER` overrides the binary) against a loopback server with `/_blob/` asset MIME sniffing and CDN allowlist isolation — no browser window is opened or hijacked. Inspect every rendered PNG and check `console` and `missing_requests`.

## Review and synchronize with code

```bash
open-claude-artifacts sync review '<artifact>' --direction to-design|to-code --pair 'project/Main.dc.html=<local>' --json
open-claude-artifacts sync apply '<review-id>' --allow-write [--reconciled] --json
open-claude-artifacts sync finish '<review-id>' --json
open-claude-artifacts sync status --json
```

Exit `3` (`state: stale`) means nothing was written because remote or local state changed since review. Exit `2` (`state: unknown`) means a write lacks verified evidence and must be reconciled rather than retried.
