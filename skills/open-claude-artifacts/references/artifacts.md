# Claude Artifacts workflows

Use `open-claude-artifacts` for Design canvases, Slides decks, Design System artifacts, Data dashboards, Whiteboards, Docs, Sheets, and plain artifact pages. Collaboration commands (assets, comments, shared database, sharing, versions) are in [artifact-collaboration.md](artifact-collaboration.md).

## Connect

```bash
open-claude-artifacts status --json
open-claude-artifacts login
```

Credentials stay in macOS Keychain or `~/.config/open-claude-artifacts/credentials.json` (`0600`). Existing `open-claude-design` artifact logins continue to work automatically. In headless or SSH sessions, ask the user to run `open-claude-artifacts login --manual` in their own terminal and paste the code there.

## Artifact types

| Content | Type | Content model |
| --- | --- | --- |
| Screens, flows, landing pages, posters | `Design` | `project/canvas.json` (v3) + `.dc.html` artboards |
| Presentations (16:9 or 4:3) | `Slides` | `project/deck.json` (v4/v5) + `project/deck.css` + `project/slides/<id>.html` |
| Brand tokens, components, assets | `Design System` | `project/design-system.json` (v3) + `project/tokens.json` + component previews |
| Dashboards, metrics, KPI reports | `Data` | Shared artifact database (`db`) |
| Shared visual boards | `Whiteboard` | Shared artifact database (`db`) |
| Editable documents and spreadsheets | `Docs`, `Sheets` | Created and read here; body managed via Claude Docs |
| One-page tools or reports | Plain page (no type) | `index.html` + files + optional runtime capabilities |

```bash
open-claude-artifacts list --scope mine|shared|all --json
open-claude-artifacts types --json
open-claude-artifacts type 'Slides' --json
open-claude-artifacts instances 'Design System' --json
open-claude-artifacts inspect '<artifact>' [--version <ver>] --json
open-claude-artifacts files '<artifact>' [--version <ver>] [--all] --json
```

Accepts a UUID/slug, a `claude.ai/code/artifact/<id>` URL, or a short share link (`claude.ai/artifact/<22 chars>`). Plain untyped pages and Migrated Design artifacts are readable via `inspect`, `files`, and `pull`.

## Create and load live guidance

```bash
open-claude-artifacts create 'Settings flow' --type Design \
  --idempotency-key '<retained-uuid>' --allow-write --json
open-claude-artifacts authoring-context '<artifact>' [--design-system <system>|none] --json
```

Reuse one UUID per creation only when reconciling an unknown outcome. `authoring-context` downloads the type's live `SKILL.md` and references under `.open-claude-artifacts/context/<id>/`, plus available design systems and the chosen system's `README.md` and `tokens.json`. Read the live guide before your first write. For plain pages, run `open-claude-artifacts contract [--capability db] --json`.

## Author and publish

- Typed artifacts write only under `project/`; the type owns `index.html`, `SKILL.md`, and `artifact-type/`.
- New indexes require `"createdOnFiles": {"v": 1, "at": "<now>"}` (canvas v3, deck v5 with `lists` and `format` + `project/deck.css`, design-system v3 with `"layout": "files"`). Keep existing keys you do not change.
- Send a canvas or deck index together with its entry artboard or cover slide first. Send a design system's index last.
- Upload images and fonts with `assets upload` and reference the returned `/_blob/<id>` verbatim.

```bash
open-claude-artifacts push '<artifact>' \
  --file 'project/canvas.json=<local>' --if-match 'project/canvas.json=0' \
  --file 'project/Main.dc.html=<local>' --if-match 'project/Main.dc.html=0' \
  [--remove 'project/Old.dc.html=<sha256>' --allow-destructive] --allow-write [--open] --json

open-claude-artifacts publish 'Release notes' --page index.html [--file style.css=style.css] \
  [--capabilities '{"db":{},"user":{}}' --contract latest] [--favicon '📈'] --allow-write --json

open-claude-artifacts design-system install '<canvas-or-deck>' '<system>' [--folder acme] --allow-write --json
```

Pass each file's current SHA-256 from `files` in `--if-match` (or `0` for new files). Every push pins the artifact version and checks readback byte-for-byte.

## Render locally in headless Chromium

```bash
# Design artboards or plain pages (light and dark, custom widths, local drafts)
open-claude-artifacts render '<artifact>' [--path project/Main.dc.html] \
  [--local 'project/Main.dc.html=<draft>'] [--width 1280 --width 390] [--theme light] --json

# Slides decks (1920x1080 or 1440x1080, by slide id or 1-based number, local drafts)
open-claude-artifacts render '<deck>' [--slide 1 --slide plan-mode] \
  [--local 'project/deck.css=deck.css'] [--local 'project/slides/plan-mode.html=plan-mode.html'] --json

open-claude-artifacts preview '<artifact>' [--open] --json
```

`render` launches headless Chrome, Chromium, Edge, or Playwright Chromium (`OPEN_CLAUDE_ARTIFACTS_BROWSER` overrides the binary). It serves files and `/_blob/` assets over loopback with network access restricted to the artifact CDN allowlist, without opening a browser window. Open every rendered PNG and check `console` and `missing_requests`.

## Sync with code

```bash
open-claude-artifacts sync review '<artifact>' --direction to-design|to-code --pair 'project/Main.dc.html=<local>' --json
open-claude-artifacts sync apply '<review-id>' --allow-write [--reconciled] --json
open-claude-artifacts sync finish '<review-id>' --json
open-claude-artifacts sync status --json
```

Exit `3` (`state: stale`) means nothing was written because local or remote content changed after review. Exit `2` (`state: unknown`) means a write lacks verified readback and needs inspection before any retry.
