# Craft Rules

Measurable defaults for user-visible UI work. The product's own tokens, components, and established patterns override every number here, and accessibility requirements override both. Use these rules when the product does not define the value, and to recognize a value that drifted away from its system.

## Precedence

1. Accessibility and interaction safety (the `open-claude-ui-review` skill owns the criteria).
2. The product's tokens, components, and repeated production patterns.
3. These craft rules.
4. Generic taste.

Derive dependent values from the system with custom properties or `calc()` instead of hardcoding a second number that has to be kept in step by hand.

## Type

- One scale from one base and one ratio: roughly 1.125–1.2 for dense product UI, 1.25–1.333 for marketing, larger only when a headline must dominate the page.
- Floors: 16px for body copy, button labels, and readable headings; 14px for supporting text; below 14px only for badges, chips, and timestamps.
- Leading: 1.4–1.6 for body copy; about 1.1–1.25 for small headings that wrap; about 1.0 for display headings so wrapped lines do not open gaps.
- Measure: 45–75 characters per line on desktop (`max-width: 65ch` is a safe default), 30–45 on narrow screens.
- Families: at most three (display, interface, monospace). Pair across classification rather than two similar sans faces. Body sits at weight 400–500 and 600 or heavier marks headings and key labels; avoid thin weights under 18px and black weights under 24px.
- Heading level is document semantics; heading size is surface role. Page and section openers are large; card, tile, accordion, footer, and sidebar titles stay near body size, roughly 14–20px. Dashboards and application screens cap page titles around 28px and widget titles around 24px; only marketing heroes use display sizes. A metric is a display number in a paragraph, not a heading.
- Tracking: tighten large display text slightly, open uppercase labels, and leave body copy alone. Use tabular numerals in data columns.

## Space

- One base unit, 4px or 8px, and at least three visibly distinct tiers per layout: tight inside a group, default between siblings, loose between groups, with section rhythm larger still.
- Padding around a group is larger than the gap inside it; otherwise the group does not read as one thing.
- A heading owns the space below it: heading-to-content stays tighter than content-to-next-section.
- Start generous and tighten until the grouping still reads. Growing a cramped layout by increments produces cramped layouts.

## Controls and surfaces

- One primary action per surface, distinguishable from every secondary action within a second. Secondary actions use an outline or quiet fill, tertiary actions read as links, and a destructive action is not automatically loud.
- Button labels never wrap and buttons never shrink inside a row. Adjacent buttons share height and padding, and an input beside a button matches the button's height. Sizes come from the system's base control size, not per-screen adjustments.
- Nested rounded shapes: inner radius equals outer radius minus the padding between them.
- Badges are inline and content-sized. A full-width strip is a banner or alert, not a badge.
- An input on a same-hue surface needs a visible fill or border difference at rest, not only on focus. Restyle native selects so the indicator, padding, and states match sibling inputs.
- Every control exposes default, hover, active, focus-visible, and disabled states. Asynchronous actions add a loading state and block resubmission. Disabled looks unavailable rather than invisible and explains itself when the reason is not obvious.
- Feedback within about 100ms, a transient indicator under a second, determinate progress beyond it. Transitions last 100–200ms and respect reduced-motion preferences.

## Color

- Neutral surfaces carry the page. One element wears the full-strength accent and everything else steps down in saturation or lightness, so the eye lands on the primary action without effort.
- Text on a colored surface uses a tint or shade of that hue, never grey. Avoid pure black for text or backgrounds.
- Every semantic state pairs color with a second cue. Compute contrast; never judge it by eye.

## Imagery and icons

- Real assets or labeled placeholders. A broken image, clip art, or a hand-drawn SVG standing in for a product shot is worse than an honest placeholder.
- Icons come from the product's icon set with consistent size and stroke. Emoji and text characters are not icons.
