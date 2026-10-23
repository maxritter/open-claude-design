# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who already work in a coding agent and want to design from their real codebase. QualityLayer offers its own design workspace without requiring a Claude subscription. Developers who want Anthropic's Claude Design can use the standalone Open Claude Design connection with an eligible Claude account.

## Product Purpose

Open Claude Design is part of QualityLayer's design offering and remains available as a free, source-available standalone CLI. It connects a developer's preferred coding agent with Claude Design. The agent creates designs from the real codebase, synchronizes changes in either direction, and verifies the rendered result. The developer uses Claude Design's visual interface for inspection, comparison, and hands-on tweaking.

Success means the codebase and Claude Design remain aligned without blind overwrites. Designs preserve real product context, and the user does not need to learn or invoke design skills manually.

## Positioning

The public README points readers to QualityLayer first. Its own artifacts support mockups, diagrams, clickable pages, comments, and agent-driven revisions without a Claude subscription. QualityLayer also offers planning, implementation, verification, independent review, and team collaboration. The user's chosen coding agent still needs its own account or API access.

Keep that workspace distinct from the Claude Design connection: this CLI still requires a Claude account with access to the relevant workspace. Do not imply that QualityLayer grants free access to Anthropic's service or that the CLI is bundled by its installer.

Open Claude Design combines three things in one workflow that neighboring design-prompt packages do not necessarily provide together:

- full native Claude artifact coverage (Design, Slides, Design System, plain pages, assets, comments, the shared database, sharing, and lifecycle) plus the existing standalone operations;
- automatic, codebase-grounded design expertise across many coding agents; and
- conflict-aware synchronization between local code and the visual Claude Design workspace.

The coding agent remains the implementation environment. Claude Design remains the visual workspace.

## Operating Context

- Runtime: a shell-capable coding agent on macOS, Linux, or WSL2.
- Visual workspace: standalone Claude Design's web interface for reviewing and tweaking designs. Anthropic announced closure on December 14, 2026; new designs live in Claude Artifacts.
- Authentication: `login` connects standalone Design; `login --backend artifact` connects the subscription frame backend in a separate secure store. No Claude Code installation or API key is required. Native artifact login uses Anthropic's subscription client and requests profile, inference, and session scopes; file operations make no model calls. Max access is verified; other account and organization combinations need their own verification.
- Installation: one GitHub-hosted bootstrap installs the persistent CLI and the same portable skills for detected agents.
- Distribution: GitHub repository and GitHub Releases; no npm or PyPI publication for Open Claude Design.
- QualityLayer integration: QualityLayer's own artifact workspace works independently of Claude Design. When Open Claude Design is installed, users can ask QualityLayer to publish an artifact to Claude Design and retain its link. This connection is optional and keeps its Claude account requirements. Impeccable is an optional companion for design refinement and checks.

## Capabilities and Constraints

- Expose every current and future Claude Design tool published through its MCP catalog by discovering tools dynamically.
- Keep large design files and synchronization ledgers out of model context through disk-backed CLI operations.
- Detect remote-only, local-only, and both-changed states through remote etags and local hashes; never choose a winner silently when both sides changed.
- Bind synchronization approval to the exact reviewed remote etags and local content hashes, then require a new review if either side changes before application.
- Connect the first real Claude Design task automatically on desktop hosts while keeping installs non-interactive and routing headless/dev-container users through a terminal-only manual flow.
- Create new Claude Design elements from real components, tokens, assets, copy, templates, and interaction states.
- Load Anthropic's latest live Claude Design prompt and exactly one relevant live authoring skill only at the remote-authoring boundary.
- Verify remote writes through readback and visual inspection before advancing the synchronization baseline. Standalone previews render through the service. Artifact `render` draws Design artboards and plain pages locally in headless Chrome, in both themes and at phone and desktop widths, before and after a push; Slides and Design System artifacts are checked in Claude.
- Use a CLI as the universal agent transport. Open Claude Design is an MCP client internally, not another MCP server for users to configure in every agent.
- Cover everything Anthropic exposes to agents over standalone MCP; do not claim that web-canvas gestures unavailable over MCP are remotely automated.
- Install the same five implicit Agent Skills for every supported coding agent through one compatibility mechanism.
- Diagnose standalone-to-artifact migration and preserve files, chats, comments, and project metadata through an opt-in local archive. Migration eligibility remains Anthropic's decision; artifact workflows are experimental and verified through the native frame service, independent of remote migration.
- Cover Claude Code's full Artifact tool action set for every agent, including Claude Code itself. Add local rendering and code synchronization.
- Remain free and source-available while restricting redistribution, rebranding, competing publication, and hosted resale.

## Brand Commitments

- Product name: Open Claude Design, part of QualityLayer. Keep the standalone name and CLI command; use QualityLayer as the main invitation on the README.
- Public surface: the GitHub README and Releases; no separate website.
- Voice: concise, concrete, confident, and outcome-led. Avoid installer internals, safety plumbing, manual skill invocation, and unexplained framework language in the main README.
- Public examples stay generic. Do not reference private or personal projects.
- Identity: a warm spark with an open centre, selected inside a design-tool frame with hollow corner handles — an idea made editable by any coding agent. The spark is original, never Anthropic's logo. Palette: paper `#F3EFE6`, ink `#16140F`, ink 2 `#57534A`, clay `#D2603A` (dark clay `#E2714B`); clay marks the spark and one highlight per surface, never body text. Type: Instrument Sans for display, IBM Plex Mono for prompts, paths, and labels.
- Brand assets (source board in the Claude Design project "Open Claude Design — Brand"):
  - `docs/media/hero-light.webp`, `docs/media/hero-dark.webp` — README hero, served through `<picture>`
  - `docs/media/social-preview.png` — 1280×640 GitHub social preview
  - `docs/media/brand/mark.svg`, `mark-dark.svg` — full mark; `mark-small.svg`, `mark-small-dark.svg` — 8-ray mark for 64px and below
  - `docs/media/brand/icon.svg`, `icon.png` — app icon; `favicon.svg` — spark-only icon for 32px and below
  - `docs/media/examples/*.webp` — fictional use-case examples (slides, desktop and mobile app, CV, design system)
- The project is independent and must not imply Anthropic endorsement; public surfaces that travel without the README (social preview) carry the independence line.

## Evidence on Hand

- A live authenticated audit on 2026-08-30 returned 23 Claude Design MCP tools covering projects, files, prompts, design skills, previews, conversations, comments, members, sharing, and remote writes.
- On 2026-10-09 the standalone connection still authenticated and advertised 23 project-based tools. Read-only live checks verified migration inventory diagnostics and complete history decoding; they did not verify artifact authoring or remote migration.
- On 2026-10-09 a separate subscription login verified native Design creation, first publication with a canvas index, SHA-256 guarded updates, private browser rendering, exact file readback, and both artifact sync directions. Artifact receipt identity and revision checks are isolated from standalone.
- On 2026-10-20, against Claude Code 2.1.304's protocol and runtime contract 0.2.87, live checks verified creation from the Design, Slides, and Design System types; plain-page publishing with capabilities; first publication with the type's follow-up version; additions, removals, and capability-preserving updates; asset upload, listing, byte-exact download, and deletion; version-pinned database writes, per-user paths, queries, and batches; public and private sharing; versions, retitle, pin, delete, diagnostics, and profiles; design-system install; and local rendering. Comment reply and resolve were verified only against the protocol, because no thread had been sent to Claude.
- The CLI, credential providers, synchronization helpers, installer adapter, skills, and cross-platform tests are implemented locally.
- The existing Pilot Shell implementation provides the proven CLI-client and disk-backed synchronization architecture being generalized here.
- The brand assets listed above were redrawn on 2026-10-05 from a Claude Design brand board, with Imagegen used for concept exploration and example photography.
- No public user count, adoption benchmark, testimonial, or performance claim exists yet; future public copy must not fabricate one.

## Product Principles

1. Keep the user's coding agent and Claude Design in one continuous workflow.
2. Treat the real product system and codebase as design authority.
3. Load current context only when it is needed; do not duplicate mutable upstream prompts.
4. Synchronize explicitly and conflict-aware; never hide an unknown or both-changed state.
5. Give every supported agent the same capability and automatic behavior.

## Accessibility & Inclusion

Generated and implemented UI work must verify accessibility and actual interaction through the target repository's available browser, simulator, device, or named UI driver. Accessibility facts, platform recommendations, and subjective design taste remain distinct.
