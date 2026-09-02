# Exploration

Use this procedure when the user asks for wireframes, alternatives, different takes, or comparative design exploration.

## Lock the comparison

State:

- The surface or flow being varied
- The user goal and non-negotiable content
- The design system or greenfield direction
- The requested number of options
- Two to four meaningful axes such as layout, hierarchy, density, interaction model, navigation, or tone

If the number is absent and alternatives are central to the request, default to at least three. Assign stable option identifiers before building and preserve them across later rounds, even when options are reordered, revised, or combined. Do not create alternatives for a focused change that has one clear product-consistent answer.

## Low-fidelity wireframes

Keep wireframes intentionally low fidelity: grayscale, neutral type, labeled media placeholders, and concise structural copy. Explore information architecture, flow, density, and action placement before visual styling.

Each variation must represent a distinct product hypothesis. Write its distinguishing structure before building it, then annotate the tradeoff beside the variation. Disposable wireframes do not receive high-fidelity polish.

## High-fidelity variations

Root every option in the product's system unless the user explicitly wants boundary-pushing concepts. Vary substantive dimensions:

- What is primary and what is removed
- Layout skeleton and information density
- Interaction or navigation model
- Type hierarchy and component treatment
- Tone and color role, when the system allows it

Changing only an accent, shadow, or radius is not a separate variation. Order options from product-conservative to more exploratory, keep all options comparable in one review surface when the repository supports that, and give a clear recommendation.

Before high-fidelity work, acquire all relevant design context rather than rebuilding it approximately: inspect the complete component variants involved, neighboring examples, real assets, bound design systems or UI kits, and every applicable template for this surface. If a necessary asset or component is unavailable, ask for it or use an honest labeled placeholder; a placeholder is better than a low-quality invented substitute.

## Handoff

When the options represent a product decision, stop after presenting and recommending them. Ask the user which option or hybrid to continue with; do not treat the recommendation as approval unless the user explicitly delegated the choice. If the options live in Claude Design, name the exact project, project-relative file, screen/frame or stable option ids, and durable project URL so the user can inspect the same artifacts before deciding.

The user's selection starts the refinement phase; it is not approval to implement a draft. Record the selected option or hybrid, what they valued, what they rejected, and every constraint revealed by comparison. Keep the exploration artifact and its stable option ids intact as that record. Develop the selected direction in its own deliverable across the complete requested scope: real content, responsive views, primary interactions, and the relevant loading, empty, failure, success, focus, and theme states.

Render, inspect, and read back that complete selected design before touching production code. If implementation was part of the original request, begin it after the selected design passes this gate; if the request was exploration-only, hand off the completed design and stop. Carry the selected design decisions into implementation instead of retaining discarded branches in production.

## Completion

Exploration is complete when each option differs in one sentence, its tradeoff is visible, the recommendation is explicit, its review location is unambiguous, and the user has chosen a direction or explicitly delegated that choice. The design phase is complete only after the selected direction exists as its own finished deliverable and passes render and readback verification. Implementation remains blocked before both gates.
