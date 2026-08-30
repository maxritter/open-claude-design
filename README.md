<div align="center">

<img src="docs/media/open-claude-design-hero.png" alt="Open Claude Design — design intelligence for coding agents" width="100%">

<h1>Claude Design for any coding agent</h1>

**Use Claude Design from your existing coding agent—no Claude Code installation or Anthropic API key required.**

```bash
curl -fsSL https://github.com/maxritter/open-claude-design/releases/latest/download/install.sh | sh
```

**macOS · Linux · WSL2**

[![GitHub stars](https://img.shields.io/github/stars/maxritter/open-claude-design?style=flat&color=22B8C7)](https://github.com/maxritter/open-claude-design/stargazers)
[![Star history](https://img.shields.io/badge/Star_History-chart-8B5CF6.svg?style=flat)](https://star-history.com/#maxritter/open-claude-design&Date)
[![Downloads](https://img.shields.io/github/downloads/maxritter/open-claude-design/total?style=flat&color=FF8066)](https://github.com/maxritter/open-claude-design/releases)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-22C55E.svg?style=flat)](https://github.com/maxritter/open-claude-design/pulls)
[![Source available](https://img.shields.io/badge/license-source--available-64748B.svg?style=flat)](LICENSE.md)

<a href="#quick-start">Install</a> ·
<a href="#what-you-can-do">Capabilities</a> ·
<a href="#agent-compatibility">Agents</a> ·
<a href="#open-for-pull-requests">Contribute</a> ·
<a href="#star-history">Star history</a>

⭐ **If this makes your coding agent better at design, [give it a star](https://github.com/maxritter/open-claude-design).**

</div>

Keep coding in the agent you already use. Open Claude Design connects it to Claude Design, so the agent creates from your actual codebase while you inspect, compare, and tweak the result visually in the Claude Design UI.

Changes move safely in either direction. The right workflow loads automatically from a normal request—no design commands to memorize.

## Quick start

**Prerequisites:** macOS, Linux, or WSL2 and a [Claude Pro, Max, Team, or Enterprise account](https://support.claude.com/en/articles/14604416-getting-started-with-claude-design). You can install before your coding agent; Claude Code is not required.

> [!IMPORTANT]
> Free accounts are not currently eligible. Claude Design uses the paid plan's shared usage limits. [Enterprise administrators](https://support.claude.com/en/articles/14604406-claude-design-admin-guide-for-team-and-enterprise-plans) must enable it under Organization settings → Capabilities.

1. **Run the one-line installer above.** It installs the CLI and portable design workflows globally, connects detected agents, and opens the standalone Claude account connection. Compatible agents installed later can use the same shared workflows.

2. **Ask your agent normally.**

> Create a Claude Design version of this settings flow, using the real components and states from the codebase.

## One workflow, both sides

1. **Create from code.** Ask your coding agent to turn an existing component, flow, or branch into a Claude Design element using the real tokens, assets, copy, and interaction states.
2. **Inspect visually.** Open the result in Claude Design, compare options, and tweak it directly in the visual UI.
3. **Sync with confidence.** Ask the agent to bring the approved changes back to code—or send newer code changes to Claude Design. If both sides changed, Open Claude Design stops for reconciliation instead of choosing a winner.

## Why Claude Design is the design tool to beat

Most AI design tools end at the first generated mockup. Claude Design keeps the work alive: generate with an agent, inspect the interactive result, compare themes and breakpoints, comment, edit, and tune exposed properties directly.

Open Claude Design connects that visual workspace to the real product:

- **The codebase stays in the room.** Components, tokens, assets, copy, and interaction states shape the design instead of being recreated from memory.
- **You keep visual control.** Inspect the rendered experience and make precise adjustments in Claude Design without turning every tweak into another prompt.
- **Iteration goes both ways.** Approved visual changes return to code, and newer implementation work can flow back into Claude Design.

## What you can do

- **Use Claude Design from your preferred agent.** Projects, files, previews, design systems, conversations, comments, members, and sharing remain available.
- **Stay current without repeated setup.** One cached operation retrieves the live project prompt and selected authoring guidance only when remote creation begins; large context stays on disk instead of flooding the terminal.
- **Create from the real product.** Existing components, tokens, assets, copy, templates, and interaction states remain authoritative.
- **Keep code and design aligned.** One-sided changes synchronize cleanly; conflicting changes stop before either version is lost.
- **Verify what people will see.** Remote writes are rendered, inspected, and read back before the project is considered synchronized.

## Works with Impeccable

[Impeccable](https://github.com/pbakaus/impeccable) complements Open Claude Design with named refinement workflows, deterministic design checks, supporting agents, and edit-time hooks. It remains optional here.

> [!TIP]
> **Want the complete engineering system?** [Pilot Shell](https://github.com/maxritter/pilot-shell) is a context and harness engineering system for Claude Code and Codex, built around spec-driven development, TDD, enforced quality, persistent memory, and end-to-end verification. It installs Open Claude Design and the complete Impeccable package as part of that larger system.

## Agent compatibility

Every supported agent receives the same automatic design workflows and CLI access. **Full** means the agent can discover and use Claude Design's current agent-facing capabilities, create from code, synchronize both directions, and run the same verification workflow.

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

Contributions are welcome. Please use the structured forms to [report a bug](https://github.com/maxritter/open-claude-design/issues/new?template=bug_report.yml) or [request a feature](https://github.com/maxritter/open-claude-design/issues/new?template=feature_request.yml). For a larger change, open a feature request before investing in the implementation.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the local checks and pull-request expectations.

## Star history

If Open Claude Design makes your agent better at design, [star the repository](https://github.com/maxritter/open-claude-design). It is the simplest way to help more developers find it.

<a href="https://star-history.com/#maxritter/open-claude-design&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=maxritter/open-claude-design&type=Date&theme=dark">
    <img alt="Open Claude Design star history" src="https://api.star-history.com/svg?repos=maxritter/open-claude-design&type=Date" width="100%">
  </picture>
</a>

## License

Open Claude Design is free and source-available. Personal and internal commercial use are allowed; redistribution, rebranding, competing publication, and hosted resale are restricted. See [LICENSE.md](LICENSE.md).

This independent project is not affiliated with, sponsored by, or endorsed by Anthropic.
