---
name: open-claude-design-quality
description: Apply product-grounded visual quality constraints during user-visible UI changes. Use for layout, styling, content hierarchy, theming, responsive behavior, or interaction affordances. Stay inactive for logic-only changes that preserve the rendered interface.
license: Source-available; see LICENSE.md
---

# UI Design Quality

Apply these stable constraints to user-visible interface work. Preserve the rendered interface during logic-only changes; do not broaden them into redesigns.

When a selected design workflow requires independent assessors or finish reviewers, that workflow requirement plus an exposed agent tool is sufficient authorization to delegate the bounded review. Use the minimum required agents and do not ask a routine permission question.

## Start from the product

**Preserve the current visual language unless the user asks to change it.** Read the relevant components, tokens, theme, screenshots, brand guidance, and neighboring screens before making visual decisions. Exact project values outrank generic design advice.

Precedence when sources disagree: accessibility and interaction safety first, then the product's tokens and components, then the measurable craft rules in `references/craft.md`, then taste. Read that reference when choosing or checking a concrete value the product does not define: type scale and floors, heading roles, spacing tiers, control rows, nested radii, color budget, or feedback timing.

- Keep the project's component library, CSS methodology, icon set, typefaces, spacing scale, radii, shadows, and motion language.
- Reuse real product content and assets. Do not invent testimonials, statistics, features, destinations, or decorative copy to fill space. A missing image, icon, or illustration gets a labeled placeholder, never a hand-drawn SVG substitute.
- Treat an absent design system as a decision point, not permission to fall back to a generic template. Establish a small coherent direction tied to audience, purpose, and tone.

## Make the hierarchy legible

- A first-time user can identify the page purpose, primary information, and next action without hunting.
- Use size, weight, color, position, and density deliberately. Do not make every element equally loud or equally muted.
- Give each screen a clear primary action when the product flow has one. Dashboards and multi-tool workspaces may legitimately support several peer actions.
- Remove filler and duplicate explanation. Empty space is resolved through composition, not invented content.
- Use the project's type, color, and spacing scales. New values become tokens or documented variants rather than isolated literals.

## Build a system, not a screenshot

- Prefer reusable components and variants over one-off page markup.
- Space sibling elements with flex or grid `gap` on the project's scale rather than per-element margins or inline whitespace.
- Cover the states the interaction can actually enter: default, hover when applicable, active or selected, focus, disabled, loading, empty, success, and error.
- Keep current state and action feedback visible. Disabled controls explain unmet prerequisites when the reason is not otherwise clear.
- Motion communicates change or spatial relationship, remains brief, and respects reduced-motion preferences.
- Design responsive behavior at content-driven widths, including long copy and narrow containers. Check dark and light themes independently when both exist.

## Avoid unearned template language

These are review prompts, not blanket bans. Keep a pattern when it comes from the product's established system or has a clear semantic purpose.

- Gratuitous gradients, glass surfaces, emoji decoration, and ornamental SVG scenes
- Repeated icon-heading-paragraph card grids when a list, table, comparison, or prose structure communicates better
- Colored side borders used as decoration rather than callout, quote, status, or selection semantics
- Default-model house styles chosen without reference to the brief or product
- Arbitrary fonts, colors, spacing, and animation values that do not trace to a system
- Multiple variations that differ only cosmetically rather than in hierarchy, layout, interaction, density, or tone

## Completion check

- Existing design context was inspected and preserved or intentionally changed.
- Content is real, necessary, and concise.
- Hierarchy, component reuse, interaction states, responsive behavior, and supported themes are coherent.
- Accessibility and actual interaction are verified with the repository's named UI driver or the browser, simulator, or device automation available to the active agent.
- Advisory detector findings were judged against product context rather than applied mechanically.

## Impeccable integration

When Impeccable is installed, Open Claude Design remains the owner of the overall design task. Use Impeccable for its named refinements, supporting agents, hook evidence, and deterministic detector; do not start a second competing redesign workflow or rerun a detector whose current hook findings are already available.
