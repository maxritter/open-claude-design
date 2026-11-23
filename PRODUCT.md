# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who work in a coding agent and want to create, render, and synchronize Claude Artifacts (Design canvases, Slides decks, Design Systems, Data dashboards, Whiteboards, Docs, Sheets, and interactive pages) from their real codebase.

## Product Purpose

Open Claude Artifacts is part of QualityLayer's design ecosystem and is available as a free, source-available CLI and portable Agent Skills package. It connects a developer's preferred coding agent directly to Anthropic's native Claude Artifacts platform, verifies Design artboards, Slides decks, and plain pages locally in headless Chromium, and keeps designs and code aligned with revision-checked sync.

## Positioning

- Native Claude Artifacts transport for every coding agent (`claude-code`, `codex`, `cursor`, `opencode`, `gemini-cli`, and 70+ Agent Skills hosts).
- Headless local verification for Design canvases, Slides decks, and plain pages without hijacking the user's browser.
- Conflict-aware two-way synchronization between local code and Claude Artifacts.
- Complementary to [QualityLayer](https://github.com/maxritter/qualitylayer), which provides its own local-first artifact and planning/build workspace without requiring a Claude subscription.

## Operating Context

- Runtime: a shell-capable coding agent on macOS, Linux, or WSL2.
- Authentication: `open-claude-artifacts login` (or `--manual` in headless/SSH/CI runtimes) stores OAuth credentials in macOS Keychain or `0600` files under `~/.config/open-claude-artifacts/`, with automatic read fallback for legacy `open-claude-design` artifact credentials.
- Installation: one GitHub-hosted bootstrap (`install.sh`) installs the CLI and the five portable skills for detected agents via `skills@1.7.0`.
- Distribution: GitHub repository (`maxritter/open-claude-artifacts`) and GitHub Releases.
