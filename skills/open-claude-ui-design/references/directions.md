# Aesthetic Directions

Starting points for greenfield work with no brand, design system, references, or existing UI. Use one direction when the user picked it or when an unattended run must proceed; state the choice and why in the deliverable so it can be redirected cheaply. Every direction is expressed as decisions, not values: the concrete tokens are chosen for the product and recorded through `open-claude-design-system`.

Pick by audience and job first, taste second. The directions differ in type, palette logic, surface treatment, density, and motion; a design that mixes two of them usually reads as neither.

## Quiet editorial

- **Fits**: reading-heavy products, publications, documentation, considered consumer brands.
- **Type**: a serif display face over a humanist sans body; generous measure; display headings tight, body relaxed.
- **Palette**: paper-toned neutrals, ink-dark text, one muted accent used almost only for links and the primary action.
- **Surfaces**: hairline borders and whitespace instead of shadows; small radii or none.
- **Density**: low; sections breathe, lists have room.
- **Motion**: near none; a single fade on page load at most.
- **Signature**: the type does the work. If a screen needs an icon grid to feel finished, the direction is wrong for it.

## Precise technical

- **Fits**: developer tools, infrastructure dashboards, data products, expert audiences.
- **Type**: one high-x-height sans for everything, a monospace for code, labels, and identifiers; compact scale with a small base size.
- **Palette**: cool neutrals, high-contrast text, one saturated accent reserved for the primary action and active states; semantic colors for status only.
- **Surfaces**: square or barely rounded corners, bordered panels, no resting shadows; overlays alone lift with a shadow.
- **Density**: high; tables, keyboard shortcuts, and inline metadata are first-class.
- **Motion**: instant state changes, short transitions only where they explain a change.
- **Signature**: alignment and rhythm. Grids visibly line up; nothing floats.

## Warm consumer

- **Fits**: services and apps for a broad audience, onboarding-heavy products, hospitality, wellness.
- **Type**: a friendly rounded or geometric sans display over a neutral sans body; medium scale.
- **Palette**: cream or warm-gray neutrals, one vivid warm accent, soft tinted surfaces for grouping.
- **Surfaces**: pill controls, rounded cards, restrained soft shadows for layering.
- **Density**: medium-low; one idea per screen.
- **Motion**: gentle, purposeful micro-interactions; a soft entrance on key moments.
- **Signature**: approachability without decoration. Warmth comes from color and shape, not illustrations of people.

## Dark instrument

- **Fits**: monitoring, trading, media, and creative tools used for long sessions.
- **Type**: a neutral sans with tabular numerals; monospace for values that update.
- **Palette**: near-black neutrals with layered gray panels, light text, one luminous accent for the live element; status colors desaturated so they do not glow.
- **Surfaces**: flat panels separated by tone, not borders; radii small; no glassy transparency without blur.
- **Density**: high; every pixel of a widget carries information.
- **Motion**: only where data changes; transitions under 200ms.
- **Signature**: contrast discipline. Measure every text and border pair; dark themes fail quietly.

## Bold campaign

- **Fits**: launches, event pages, brands that want to be remembered on first contact.
- **Type**: an oversized characterful display face, tight leading, a plain sans for body; few words.
- **Palette**: one dominant field color with a hard-contrast counterpart, black or white text, almost no gray.
- **Surfaces**: hard edges, thick rules, no shadows; imagery full-bleed or absent.
- **Density**: very low on the hero, normal below.
- **Motion**: one orchestrated entrance; nothing loops.
- **Signature**: commitment. Half-bold reads as a template; either the page owns its field color or it should use another direction.

## Soft product

- **Fits**: general SaaS, productivity tools, admin interfaces that must feel modern without a strong brand voice.
- **Type**: a clean sans throughout; standard scale; medium weights for headings.
- **Palette**: light neutral surfaces, mid-blue or violet accent family, generous use of tints for selection and hover.
- **Surfaces**: 8 to 12px radii, subtle layered shadows with a hairline border, cards on a slightly tinted page.
- **Density**: medium; comfortable forms and tables.
- **Motion**: standard 150ms transitions, reduced-motion aware.
- **Signature**: consistency. This direction only works when every control shares the same radius, shadow, and focus ring; deviations read as bugs.

## Committing

After choosing, write the direction's decisions as a small token set (type roles, palette roles, radius scale, shadow scale, spacing base, motion durations) before the first screen, and keep the signature trait visible on every surface. The generic-template review in `open-claude-ui-review` then has something concrete to judge against.
