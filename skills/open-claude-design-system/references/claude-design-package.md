# Claude Design design-system package

Read this reference only when an extracted system must live in Claude Design as a design system that projects can bind. It describes the shape Claude Design indexes, observed on live design-system projects in September 2026. The host owns that shape and may change it: before authoring, inspect an existing design-system project in the user's account and follow what is there when it differs from this file.

Access, authentication, and every remote write go through `open-claude-design`. This reference only decides what the files contain.

## The destination is a design-system project

A design system is a Claude Design project whose `get_project` result reports `type: PROJECT_TYPE_DESIGN_SYSTEM`. The type is fixed at creation. Writing a package into a regular project never turns it into a design system, and nothing will be able to bind it.

1. Resolve the destination with `list_design_systems`, then confirm the type with `get_project`. Stop when the type is anything else.
2. The Claude Design connection creates regular projects only. When no design-system project exists yet, the user creates one in Claude Design (its design-system setup, or Claude Code's `/design-sync`) and gives the agent the id. Do not substitute a regular project.
3. A published design system applies to every project that binds it, and `is_default: true` marks the one new projects receive. Changing it changes other people's future work; name that effect when asking for write approval.

## Authored files

These are the files the agent writes. Keep the repository's own token names and values; this is a packaging step, not a second extraction.

| Path | Purpose |
|---|---|
| `styles.css` | The single entry point. Only `@import` lines, in cascade order: fonts, color, typography, spacing, base, then components. Every card and every consuming design links this one file. |
| `tokens/*.css` | Custom properties grouped by concern (`colors.css`, `typography.css`, `spacing.css`, `fonts.css`, `base.css`). Themes are selectors that redefine the same properties, such as `[data-theme='dark']`. |
| `components/components.css` and `components/<group>/<Name>.jsx` | Component classes, and one source file per reusable component when the system ships real components. |
| `guidelines/*.card.html` and `components/<group>/*.card.html` | Preview cards: small standalone pages that render one facet of the system. |
| `ui_kits/<name>/index.html` | Optional full-screen compositions that show the system assembled. |
| `assets/` | Logos, marks, and self-hosted fonts referenced by `tokens/fonts.css`. |
| `readme.md` | The human-readable system: principles, usage rules, do and don't. |
| `SKILL.md` | The agent entry point Claude Design loads with the system: name, description, the non-negotiable rules in one paragraph, and a pointer to `readme.md`. |
| `thumbnail.html` | The small page Claude Design renders as the system's thumbnail. |

## Preview cards

The Design System pane builds its card index from a marker on the first line of each preview file. A file without the marker is not a card, whatever its name.

```html
<!-- @dsCard group="Spacing & Shape" viewport="700x210" name="Spacing scale" subtitle="4px base" -->
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><link rel="stylesheet" href="../styles.css">
```

- `group` is the pane section. Use the source system's own categories; the pane groups by the exact string.
- `viewport` is `WIDTHxHEIGHT` in CSS pixels, sized to the content so the card neither clips nor floats in empty space.
- `name` is a short human label, and `subtitle` names the variants shown.
- Link `styles.css` by relative path and style the card with the system's own tokens. A card that hard-codes a value the system defines as a token documents the wrong thing.
- One facet per card: a scale, a palette band, one component's variants and states. Show real states, not only the resting one.

## Files Claude Design compiles

Never write, edit, or delete these. Claude Design derives them from the authored files after each change, and a hand-written copy goes stale or is overwritten.

- `_ds_manifest.json`: the compiled index of components, starting points, cards, templates, global CSS paths, tokens with their kind and defining file, themes, and fonts.
- `_ds_bundle.js`: the compiled component bundle.
- `_adherence.oxlintrc.json`: the rules Claude Design uses to check designs against the system.
- `.thumbnail`: the rendered thumbnail.

Read `_ds_manifest.json` after publishing as the acceptance check: every token, card, component, theme, and font the package intended should appear there, each traced to the right file. A token missing from the manifest was not recognized, usually because it is defined outside the files `styles.css` imports. Compilation runs in the Claude Design app, so ask the user to open the design system once when the manifest has not caught up.

## Publishing

1. Build the package in a repository-local scratch directory and render each card locally against the local `styles.css` first.
2. List the destination and compare structure. Publish incrementally, one component or token group at a time. Never replace a whole design system to land one change, and never delete remote files the user did not name.
3. Write through `open-claude-design push` with an etag for every path, inside one exact-path plan per batch. Exclude the compiled files from every plan.
4. Verify each written card through the normal render gate, then confirm it in the manifest.
5. Report the durable project URL and which bound projects the change reaches.

Binary assets above the inline write limit cannot be pushed from disk. Keep fonts and images small, or have the user upload them in Claude Design.
