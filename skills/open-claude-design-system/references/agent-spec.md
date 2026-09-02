# Agent-Facing Design System Package

Use this procedure when the user wants the extracted system to govern future agent work in the repository, not only to exist as tokens in code. The output is a project-local skill that every coding agent loads automatically before touching UI, so the product's own language wins over generic taste without anyone re-explaining it.

Produce it after `tokens.md` and `components.md` have established the evidence. The package restates that evidence in agent-readable form; it never invents values the extraction did not find.

## Placement

- One directory per product system: `.claude/skills/<product>-design-system/` with a mirror at `.agents/skills/<product>-design-system/` (a relative symlink where the host allows it, a copy otherwise), so Claude Code, Codex, and other Agent Skills hosts read the same file.
- `SKILL.md` carries everything. Do not scatter modules across files that a host may not load; the module index below is an index into sections of the same file.
- The frontmatter description names the product and says when to read it: "the visual specification for <product> UI; read before creating or changing any user-visible interface in this repository".

## Structure

1. **Provenance**: source paths, the commit hash the extraction was taken from, the extraction date, and the maintainer decisions that resolved conflicts. This is what lets a later review notice drift between the package and the code.
2. **Style**: one or two sentences of the product's visual character in concrete terms (surfaces, brand moments, corner treatment, type feel, depth), followed by the three to five signature traits that make a screen recognizably this product. Each trait names the token or rule that carries it.
3. **Before writing any code**: which sections to read for which task, as a short table (landing page, form, dashboard, settings, overlay).
4. **Critical rules**: the product-specific non-negotiables, each one testable. Examples of the right granularity: which surfaces may carry the brand color, the single content width, the section rhythm, which controls are square and which are round, what an outline button's border weight is.
5. **Module index**: foundation first (colors, typography, spacing, radius, borders, shadows, layout), then components, then complex components, each linking to its section.
6. **One section per module** in a fixed shape:
   - Dependencies: the foundation sections this module relies on.
   - Core specs: the values every instance shares (radius, border, shadow, weight, font, transition).
   - Sizes: a table of the sizes that actually exist with font size and padding.
   - Variants: for each variant, background, border, text, hover, focus ring, and any effect, all as token names.
   - States: default, hover, active, focus-visible, disabled, loading, error, selected as applicable.
   - Rules and prohibited: what this component never does in this product.
   - Sources: the files and consumers the section was derived from.

## Content rules

- Tokens keep the product's real names (`--color-brand-600`, `spacing.4`, `radius.md`), with the resolved value beside the name once, in the foundation section. Component sections reference names only, so a token change propagates without editing every module.
- Derived values are written as relationships, not second numbers: an inner radius is "outer radius minus panel padding", a hover surface is "the neutral hover tint shared by every link surface".
- Every state a component can enter is listed, even when the product currently leaves it unstyled; mark such gaps as `[not defined in source]` so the next agent asks instead of inventing.
- Prohibited lists carry only rules with product evidence or an explicit maintainer decision. Generic taste belongs to `open-claude-design-quality`, not here.
- Keep the package under roughly 40 KB. Past that, move rarely used complex components into a second skill with its own description rather than diluting the primary one.

## Precedence statement

The package opens with the same precedence the quality skill uses: accessibility and interaction safety first, then this package, then the measurable craft rules, then taste. A later agent must not weaken an accessibility requirement to satisfy a style rule, and must not invent a style value the package does not define; it adds the value to the foundation section with its source instead.

## Verification

- Build one representative surface from the package alone in a scratch route and compare it against the real product screen it describes; mismatches are extraction errors to fix in the package, not in the product.
- Confirm the skill loads in the repository's agents (Claude Code and Codex at minimum) by asking each to describe the product's button variants without opening the source.
- Re-run the extraction diff when tokens or shared components change; the provenance commit hash is the trigger.
