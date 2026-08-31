# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who already work in a coding agent and want to use Claude Design without moving their implementation workflow into a different agent. They work across existing codebases where components, tokens, product behavior, assets, and interaction states already matter.

## Product Purpose

Open Claude Design connects a developer's preferred coding agent with Claude Design. The agent can create design elements from the real codebase, synchronize changes in either direction, and verify the rendered result, while the developer continues to use Claude Design's visual interface for inspection, comparison, and hands-on tweaking.

Success means the codebase and Claude Design remain aligned without blind overwrites, design work preserves real product context, and the user does not need to learn or invoke design skills manually.

## Positioning

Open Claude Design combines three things in one workflow that neighboring design-prompt packages do not necessarily provide together:

- the complete Claude Design surface Anthropic exposes to coding agents;
- automatic, codebase-grounded design expertise across many coding agents; and
- conflict-aware synchronization between local code and the visual Claude Design workspace.

The coding agent remains the implementation environment. Claude Design remains the visual workspace.

## Operating Context

- Runtime: a shell-capable coding agent on macOS, Linux, or WSL2.
- Visual workspace: Claude Design's web interface for reviewing and tweaking designs.
- Authentication: a Claude Pro, Max, Team, or Enterprise account connected directly through `open-claude-design login`; no Claude Code installation or API key is required. Enterprise organizations must enable Claude Design.
- Installation: one GitHub-hosted bootstrap installs the persistent CLI and the same portable skills for detected agents.
- Distribution: GitHub repository and GitHub Releases; no npm or PyPI publication for Open Claude Design.
- Companion tools: Impeccable is optional in the standalone package. Pilot Shell installs both as part of its wider engineering system.

## Capabilities and Constraints

- Expose every current and future Claude Design tool published through its MCP catalog by discovering tools dynamically.
- Keep large design files and synchronization ledgers out of model context through disk-backed CLI operations.
- Detect remote-only, local-only, and both-changed states through remote etags and local hashes; never choose a winner silently when both sides changed.
- Bind synchronization approval to the exact reviewed remote etags and local content hashes, then require a new review if either side changes before application.
- Connect the first real Claude Design task automatically on desktop hosts while keeping installs non-interactive and routing headless/dev-container users through a terminal-only manual flow.
- Create new Claude Design elements from real components, tokens, assets, copy, templates, and interaction states.
- Load Anthropic's latest live Claude Design prompt and exactly one relevant live authoring skill only at the remote-authoring boundary.
- Verify remote writes through render, visual inspection, and readback before advancing the synchronization baseline.
- Use a CLI as the universal agent transport. Open Claude Design is an MCP client internally, not another MCP server for users to configure in every agent.
- Cover everything Anthropic exposes to agents over MCP; do not claim that web-canvas gestures unavailable over MCP are remotely automated.
- Install the same five implicit Agent Skills for every supported coding agent through one compatibility mechanism.
- Remain free and source-available while restricting redistribution, rebranding, competing publication, and hosted resale.

## Brand Commitments

- Product name: Open Claude Design. Use the full name in every public surface.
- Public surface: the GitHub README and Releases; no separate website.
- Voice: concise, concrete, confident, and outcome-led. Avoid installer internals, safety plumbing, manual skill invocation, and unexplained framework language in the main README.
- Public examples stay generic. Do not reference private or personal projects.
- Brand assets:
  - `docs/media/open-claude-design-hero.png`
  - `docs/media/open-claude-design-logo.png`
  - `docs/media/open-claude-design-icon.png`
- The project is independent and must not imply Anthropic endorsement.

## Evidence on Hand

- A live authenticated audit on 2026-08-30 returned 23 Claude Design MCP tools covering projects, files, prompts, design skills, previews, conversations, comments, members, sharing, and remote writes.
- The CLI, credential providers, synchronization helpers, installer adapter, skills, and cross-platform tests are implemented locally.
- The existing Pilot Shell implementation provides the proven CLI-client and disk-backed synchronization architecture being generalized here.
- Generated hero, logo, and icon assets exist at the paths above.
- No public user count, adoption benchmark, testimonial, or performance claim exists yet; future public copy must not fabricate one.

## Product Principles

1. Keep the user's coding agent and Claude Design in one continuous workflow.
2. Treat the real product system and codebase as design authority.
3. Load current context only when it is needed; do not duplicate mutable upstream prompts.
4. Synchronize explicitly and conflict-aware; never hide an unknown or both-changed state.
5. Give every supported agent the same capability and automatic behavior.

## Accessibility & Inclusion

Generated and implemented UI work must verify accessibility and actual interaction through the target repository's available browser, simulator, device, or named UI driver. Accessibility facts, platform recommendations, and subjective design taste remain distinct.
