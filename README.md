<div align="center">

<img src="docs/media/open-claude-design-hero.png" alt="Open Claude Design — design intelligence for coding agents" width="100%">

<h1>Claude Design for any coding agent</h1>

**Use Claude Design from your existing coding agent—no Claude Code installation or Anthropic API key required.**

```bash
curl -fsSL https://github.com/maxritter/open-claude-design/releases/latest/download/install.sh | sh
```

**macOS · Linux · WSL2**

[![GitHub stars](https://img.shields.io/github/stars/maxritter/open-claude-design?style=flat&color=22B8C7)](https://github.com/maxritter/open-claude-design/stargazers)
[![Release](https://img.shields.io/github/v/release/maxritter/open-claude-design?style=flat&color=8B5CF6)](https://github.com/maxritter/open-claude-design/releases)
[![Downloads](https://img.shields.io/github/downloads/maxritter/open-claude-design/total?style=flat&color=FF8066)](https://github.com/maxritter/open-claude-design/releases)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-22C55E.svg?style=flat)](https://github.com/maxritter/open-claude-design/pulls)
[![Source available](https://img.shields.io/badge/license-source--available-64748B.svg?style=flat)](LICENSE.md)

<a href="#quick-start">Install</a> ·
<a href="#what-you-can-do">Capabilities</a> ·
<a href="#agent-compatibility">Agents</a> ·
<a href="#open-for-pull-requests">Contribute</a>

⭐ **If this makes your coding agent better at design, [give it a star](https://github.com/maxritter/open-claude-design).**

</div>

Open Claude Design connects your coding agent and real codebase to Claude Design's visual workspace. Ask normally—the right workflow loads automatically.

## Quick start

**Prerequisites:** macOS, Linux, or WSL2 and a [Claude Pro, Max, Team, or Enterprise account](https://support.claude.com/en/articles/14604416-getting-started-with-claude-design). You can install before your coding agent; Claude Code is not required.

> [!IMPORTANT]
> Free accounts are not currently eligible. Claude Design uses the paid plan's shared usage limits. [Enterprise administrators](https://support.claude.com/en/articles/14604406-claude-design-admin-guide-for-team-and-enterprise-plans) must enable it under Organization settings → Capabilities.

1. **Run the one-line installer above.** It installs the CLI and shared workflows, connects detected agents, and opens the standalone Claude login.

2. **Ask your agent normally.**

> Create a Claude Design version of this settings flow, using the real components and states from the codebase.

## One workflow, both sides

1. **Create from code.** Turn real components, tokens, assets, copy, and states into a Claude Design element.
2. **Inspect visually.** Open the result in Claude Design, compare options, and tweak it directly in the visual UI.
3. **Sync both ways.** Move approved designs into code or newer code into Claude Design. Conflicts stop for review.

## Why Claude Design is the design tool to beat

Most AI design tools end at a mockup. Claude Design stays interactive: generate, inspect, compare, comment, edit, and tune visually.

Open Claude Design connects that visual workspace to the real product:

- **Codebase grounded.** Real components, tokens, assets, copy, and states shape the design.
- **Visually controllable.** Inspect and adjust the rendered result without prompting every tweak.
- **Two-way iteration.** Approved designs return to code; newer code returns to Claude Design.

## What you can do

- **Full Claude Design access.** Projects, files, previews, design systems, conversations, comments, members, and sharing.
- **Current guidance, lean context.** Live authoring context is cached on disk and loaded only when needed.
- **Verified remote changes.** Writes are rendered, inspected, and read back before synchronization completes.

## Works with Impeccable

[Impeccable](https://github.com/pbakaus/impeccable) adds refinement workflows, deterministic checks, supporting agents, and edit-time hooks. It remains optional.

> [!TIP]
> **Want the complete engineering system?** [Pilot Shell](https://github.com/maxritter/pilot-shell) is a context and harness engineering system for Claude Code and Codex, built around spec-driven development, TDD, enforced quality, persistent memory, and end-to-end verification. It installs Open Claude Design and the complete Impeccable package as part of that larger system.

## Agent compatibility

Every supported agent receives the same automatic workflows and CLI access.

| Coding agents | Status |
|---|:---:|
| Claude Code · Codex · OpenCode | ✅ Full |
| Cursor · GitHub Copilot · Cline · Trae · Qoder · Rovo Dev | ✅ Full |
| Gemini CLI · Antigravity · Kimi · Kiro · Pi | ✅ Full |
| Mistral Vibe · Hermes · Reasonix · Grok Build · OpenClaw | ✅ Full |
| Warp · Zed · Amp · Replit · other Agent Skills hosts | ✅ Full |

The installer auto-detects installed agents. Use `--all-agents` only when every available integration is wanted.

## Maintenance

| What do you want to do? | Command |
|---|---|
| **Reconnect your Claude account** | `open-claude-design login` |
| **Check the connection** | `open-claude-design status --json` |
| **Update Open Claude Design** | `open-claude-design update --scope global --yes` |
| **Uninstall Open Claude Design** | `curl -fsSL https://github.com/maxritter/open-claude-design/releases/latest/download/uninstall.sh \| sh` |

## Open for pull requests

Use the structured forms to [report a bug](https://github.com/maxritter/open-claude-design/issues/new?template=bug_report.yml) or [request a feature](https://github.com/maxritter/open-claude-design/issues/new?template=feature_request.yml). See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Open Claude Design is free and source-available. Personal and internal commercial use are allowed; redistribution, rebranding, competing publication, and hosted resale are restricted. See [LICENSE.md](LICENSE.md).

This independent project is not affiliated with, sponsored by, or endorsed by Anthropic.

<div align="center">

Made with 🩵 by [Max Ritter](https://maxritter.net)

</div>
