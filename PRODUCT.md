# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers using a coding agent to create, check locally, and sync Claude Artifacts from their real codebase.

## Product purpose

Open Claude Artifacts is a free, source-available CLI and portable Agent Skills package, part of QualityLayer's design ecosystem. It connects coding agents to Anthropic's native Claude Artifacts platform, renders Design artboards, Slides decks, and plain pages in headless Chromium, and keeps designs and code aligned with revision-checked sync.

## Positioning

- One CLI and five portable skills across 79 coding-agent integrations (`skills@1.7.0`).
- Local headless Chromium verification for Design canvases, Slides decks, and plain pages without opening the user's browser.
- Revision-checked two-way synchronization between local code and Claude Artifacts.
- Complementary to QualityLayer, which provides a local-first artifact and planning workspace without requiring a Claude subscription.

## Operating context

- Runtime: macOS, Linux, or WSL2.
- Authentication: `open-claude-artifacts login` (or `--manual` in SSH, CI, or containers), storing credentials in macOS Keychain or `0600` files under `~/.config/open-claude-artifacts/`. Existing `open-claude-design` artifact credentials work automatically as a read fallback.
- Distribution: GitHub repository (`maxritter/open-claude-artifacts`) and GitHub Releases; no separate website.
