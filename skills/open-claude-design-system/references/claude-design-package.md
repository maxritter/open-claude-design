# Claude Design System artifact package

Read this reference when publishing an extracted design system into a native Claude **Design System** artifact (`--type "Design System"`). Always run `open-claude-artifacts authoring-context <artifact> --json` first and follow the live `SKILL.md` and `format.md` whenever Anthropic updates the schema.

All reads, writes, and asset uploads go through `open-claude-artifacts`.

## Create or locate the Design System artifact

1. Check existing systems with `open-claude-artifacts instances "Design System" --json`.
2. To create a new one (when authorized):
   ```bash
   open-claude-artifacts create "Acme Design System" --type "Design System" \
     --idempotency-key "<uuid>" --allow-write --json
   ```
3. Load the live format guide with `open-claude-artifacts authoring-context <artifact> --json`.

## File layout under `project/`

Keep the source codebase's exact token names and numeric values. Write only under `project/`.

| Path under `project/` | Purpose |
| --- | --- |
| `design-system.json` | Schema v3 index (`"v": 3`, `"layout": "files"`, `"createdOnFiles"`, `"title"`, `"namespace"`, `"libraries"`, `"groups"`, `"assetGroups"`). Write this file **last**. |
| `tokens.json` | Complete color (light/dark themes), typography, spacing, and radius token definitions. |
| `README.md` (and optional `*.md`) | Brand principles, token usage guidance, and component rules. |
| `components/bundle.js`, `bundle.css`, `index.d.ts` | Optional classic script assigning `window.<namespace>`, stylesheet, and type docs. |
| `components/<Name>/README.md` | Guidelines for one component (first sentence acts as summary). |
| `components/<Name>/preview.html` | Live preview card starting with `<!-- @dsCard group="Actions" height=88 -->`. |
| `fonts/<file>` | Self-hosted font files listed in `tokens.json`. |

Never write generated paths (`project/tokens.css`, `project/manifest.json`, or `project/api/*`). Upload icons, logos, and images via `open-claude-artifacts assets upload` and reference their blob IDs in `assetGroups` inside `design-system.json`.

## Publish and install into canvases or decks

1. Push `tokens.json`, `README.md`, fonts, and component files first with `--if-match` SHA-256 preconditions (`0` for new files).
2. Push `project/design-system.json` last so the artifact reads the complete file set cleanly.
3. Install the system into a Design canvas or Slides deck with one command:
   ```bash
   open-claude-artifacts design-system install <canvas-or-deck> <design-system> --allow-write --json
   ```
   This copies `tokens.json` into `project/ds/<folder>/tokens.json` and records the system in `canvas.json` or `deck.json`.
