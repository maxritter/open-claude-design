---
name: open-claude-ui-design
description: Create or redesign product UI in an existing codebase, including a wireframe, substantive visual variations, and an interactive prototype. Use for requests about UI layout, visual direction, screens, flows, components, a landing page, dashboard, or making an interface feel polished. Do not use for backend work, system architecture, decks, or logic-only UI fixes.
license: Source-available; see LICENSE.md
---

# UI Design

Create intentional product interfaces inside the user's real codebase. The current product is the source of truth; design expertise improves it without replacing its language by reflex.

## Important boundaries

- Inspect the existing design system, components, tokens, theme, screenshots, assets, and neighboring screens before proposing visual changes.
- A non-visual logic change in a UI file is not a design task. Preserve the rendered result and handle it directly without expanding scope.
- Work in the project's native framework and file structure. Do not replace an application with a standalone HTML mockup unless the user explicitly requests an isolated prototype.
- Reuse real content and assets. Mark a missing asset with a labeled placeholder; do not invent product claims, statistics, testimonials, features, or destinations.
- When Impeccable is also available, this skill owns the overall product-design workflow. Use Impeccable only for a requested named refinement, supporting agent, hook evidence, or detector result; do not run a second competing design process.

## Direction count

Create one strong, complete direction by default. A direct request to design, redesign, or implement a surface does not imply comparative exploration. Use multiple variants only when the user explicitly asks for options, alternatives, or comparison, or when a materially unresolved product direction makes side-by-side evidence cheaper than a clarifying question. An established product system plus a clear objective normally has one product-consistent answer.

## Scope

The user's explicit surface is the boundary: do not narrow a requested full-screen redesign or expand a requested region. If the request names a whole surface but gives only a localized change objective and the intended breadth is materially ambiguous, ask one scope question. When no answer is available, design the named change and leave the surrounding UI unchanged and omitted.

Before sketching or specifying, separate **provided product facts**, **verified existing UI**, and **unknowns**. Missing evidence removes authority; it never permits “generic” or “illustrative” fields, settings, sections, actions, policies, or product consequences, and an unknown never becomes plausible-looking interface copy.

For a partial-surface request, start the deliverable with `Scope: <named region> only; surrounding UI unchanged and omitted.` Show only that region: a full-page wireframe, a named surrounding section, or an invented neighboring action is out of scope. Render an unknown high-stakes consequence as a bracketed placeholder such as `[verified deletion consequence]`, never as factual copy. A missing repository never expands scope; in a self-contained brief, the brief is authoritative.

## Select the relevant procedure

Read only the references needed for the request, resolved relative to this skill:

| Request | Required reference |
|---|---|
| New UI, redesign, or ambiguous visual direction | `references/discovery-and-direction.md` |
| Explicit wireframes, alternatives, or materially unresolved visual direction | `references/exploration.md` |
| Clickable prototype, interaction demo, or new flow | `references/prototype.md` |

Combine references only when the task spans their modes. A redesign that asks for three interactive alternatives uses all three; a focused styling change may need none beyond this router.

## Execution contract

1. Ground every decision in inspected product evidence or an explicit greenfield direction.
2. Ask only when the answer materially changes audience, scope, brand, flow, fidelity, or the axes of comparison. Make reversible local decisions autonomously and state the consequential ones.
3. Build the smallest complete surface that proves the direction, then extend it consistently through components and tokens.
4. Verify the actual interface with the repository's named browser, simulator, or UI driver: interact with the primary path, re-snapshot the result, inspect representative widths and supported themes, and report unverified states.
5. For a final visual audit or polish request, use the `open-claude-ui-review` skill so review findings, accessibility, and fixes have one owner.

When the user requests an outline or plan and explicitly forbids implementation, include a **Verification plan** in the delivered artifact. It names the primary interaction, one representative failure, keyboard operation, the viewport/theme matrix, and the state transitions that must be re-snapshotted after implementation.

Every asynchronous action in a designed flow includes a retryable failure state: keep relevant input/context, show an actionable error, re-enable the action when safe, and define where focus moves.

## Completion

The result is complete when the requested surface works in the real application, follows either the existing system or a documented new direction, contains no invented scope, and has interaction plus visual evidence at the affected states and viewports.

## When not to use

- Backend, API, database, infrastructure, or software-architecture design
- Slide decks, presentations, print documents, or generic image creation
- Logic-only fixes in TSX/JSX or other UI files whose rendered behavior must remain unchanged
- Design-system extraction without a requested screen or flow; use `open-claude-design-system`
- Report-only UI audits or pre-ship polish; use `open-claude-ui-review`
- Accessing, importing, or changing a Claude Design project; use `open-claude-design`, then return here for local adaptation
