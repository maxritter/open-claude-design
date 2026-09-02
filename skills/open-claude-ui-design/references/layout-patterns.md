# Layout Patterns

Structural starting points for surfaces that recur in most products. Each pattern describes structure, hierarchy, and responsive behavior only; the product's tokens and components supply every visual value, and `open-claude-design-quality/references/craft.md` supplies the measurable defaults where the product is silent.

Write the structure before styling: containers, stacks, order, and widths in plain words. A pattern is a default, not a rule; when the product already solves the surface, its pattern wins.

## Shared rules

- Content sits in one centered container with a single maximum width for the product (marketing commonly 1200 to 1280px, dense tools wider). Full-bleed backgrounds may span the viewport; content never does.
- A section's intro block (eyebrow, heading, lead, actions) reads as one unit with a narrower measure than the section, roughly 60 to 70 characters, and clears the body content by a full section-scale gap.
- One primary action per surface. Everything else is secondary or a link.
- Vertical rhythm comes from equal, symmetric section spacing; adjacent bordered elements draw a shared edge once.
- Below the narrow breakpoint every multi-column layout stacks in source order and stretches to the container width with comfortable side padding; nothing hides content without an explicit disclosure control.

## Marketing surfaces

**Navigation bar.** A single row: logo at the start, primary links in the middle or trailing, one primary action at the end, a secondary action beside it. Links are text with a hover color change, not buttons. On narrow screens the links and secondary action collapse behind a menu button into a panel below the bar; the primary action may remain visible. Sticky bars are translucent only with a backdrop blur.

**Hero, centered stack.** Eyebrow, headline, lead, action pair, then supporting media below (product shot, dashboard mockup, or video frame). The copy stack is narrower than the media. Use when the product image sells the story.

**Hero, split.** Copy stack on one side, media on the other, aligned to a shared vertical center or to the top edge. The copy side carries the action pair and optional proof line (rating, logos, install command). Stacks copy above media on narrow screens. Use for developer tools and products where the words matter more than the picture.

**Hero, full-bleed media.** The media fills the section; copy sits on a contrast-safe panel or a darkened region with measured contrast. Reserve for brands whose imagery is the message, and provide a text-first fallback for reduced-data or accessibility contexts.

**Feature grid.** Intro block, then a grid of three or four columns of icon, title, two-line description. Card titles stay near body size. Cap at nine items; beyond that, group into tabs or alternate rows.

**Alternating feature rows.** For fewer, deeper features: rows of copy and media that swap sides each time, each row a self-contained argument with its own small heading. Rows stack media-first on narrow screens.

**Bento or mosaic.** Mixed-size tiles where one featured tile spans two columns or rows. Use when features differ in importance; every tile still carries a title and one line of copy, and the featured tile carries the media.

**Proof row.** A single wrapping row of customer logos or a stat strip (three to five numbers with labels) under a short kicker. Logos are monochrome unless the brand allows color; stats are display numbers in paragraphs, not headings.

**Testimonials.** One featured quote with attribution and avatar, or a two- or three-column set of shorter quotes. Quote text stays body-sized or one step above; the decorative quotation mark is optional and never larger than the headline scale.

**Pricing.** Intro block with an optional billing toggle, then two to four tier cards of equal width and height: plan name, one-line description, dominant price with a period suffix on the same baseline, one full-width action, then a feature list of check icon plus label. Highlight one recommended tier through a border or a badge, never a different card size. A comparison table below the cards handles long feature matrices. Cards stack on narrow screens in the same order.

**FAQ.** Intro block, then either an accordion in one column with a measured width, or a static two-column grid of question and answer pairs when answers are short. Questions are near body size and read like list items.

**Call-to-action band.** Headline, one line of supporting copy, action pair, centered, on a contrasting band. It is the only section that may reuse the hero's brand surface.

**Footer.** Logo and a one-line description, three to five link columns with small uppercase or medium-weight labels, then a bottom row with legal links and a copyright. Columns collapse into stacked groups on narrow screens. A minimal footer reduces to one row of links plus the legal line.

## Application surfaces

**Application shell.** A fixed-width sidebar for primary navigation, a top bar for context (breadcrumb or page title, search, account menu), and a scrollable content region. Sidebar items share one hover fill and one stronger active fill; groups are separated by labels, not lines. Below the medium breakpoint the sidebar collapses to icons or into an off-canvas drawer opened from the top bar.

**Page header.** Title, optional description, and the page's actions on the same row; secondary tools (filters, view switches) on a row beneath. The title follows the application heading cap, not the marketing scale.

**Data table.** A toolbar (search, filters, bulk actions once rows are selected), a header row with sortable columns, rows with consistent alignment (text left, numbers right in tabular numerals, actions trailing), a footer with pagination and a row-count summary. Selected rows take the neutral hover fill and show their state through the checkbox. Provide loading rows, an empty state with the next action, and an error row with retry. On narrow screens, drop secondary columns or switch to stacked cards; never force horizontal scrolling of the whole page.

**Form.** One column, labels above fields, helper text below, errors below in text plus an icon. Group related fields under small headings; place the primary action at the end with a secondary cancel beside it. Multi-step forms show progress and keep entered values across steps. Inputs beside buttons share the button's height.

**Settings.** Sections as cards or bordered groups, each with a heading, description, and the fields it owns; destructive actions live in their own final section with a confirmation step where the action becomes primary.

**Dashboard.** A grid of widgets with equal gutters: metric tiles (label, display number, delta with a non-color cue), chart cards (title, time-range control, chart drawn by a real charting library with series colors from the palette), and lists. Widget titles stay at the widget scale; the page title is the only larger text.

**Overlays.** Modal for a focused decision or a short form: header, body, footer actions with the primary trailing; sizes derived from content width, never full-bleed on wide screens. Drawer for long secondary content or navigation, sliding from the edge nearest its trigger. Both trap focus, close on Escape, and restore focus to the trigger.

**States.** Every list, table, and detail view defines loading (skeletons matching the layout), empty (a sentence and the next action), and error (what failed and a retry). Success feedback is transient and near the action.

**Authentication.** Login, register, and password flows use one centered card on a quiet surface: logo, heading, short line, fields, primary action, then alternatives (social sign-in, links to the other flows) below a divider. Verification and two-factor screens use the same card with a code input and a resend link with a visible cooldown.

**Error and maintenance pages.** Centered stack: short status line, one-sentence explanation, one primary action back to safety, optional secondary link to support. No decorative illustration unless the product already has one.

## Commerce surfaces

**Product card.** Image with fixed aspect ratio, title, price with any discount shown as strike-through plus the current price, rating with count, one action. The whole card is the link; the action is the only button.

**Product grid with filters.** Filters in a start-side column that becomes a drawer on narrow screens; a results header with count and sort; a responsive grid of product cards; pagination or a load-more control at the end.

**Product detail.** Gallery on one side (main image plus thumbnails), purchase panel on the other: title, price, variant selectors, quantity, primary add-to-cart, secondary save, delivery and return facts. Long-form details (description, specifications, reviews) follow below in tabs or sections.

**Cart and checkout.** The cart lists line items with image, title, variant, quantity control, line price, and remove; a summary card holds subtotal, shipping, tax, total, and the primary checkout action, sticky on wide screens. Checkout runs in ordered steps (contact, shipping, payment, review) with the summary visible throughout and one primary action per step. Order confirmation repeats the order number, the items, the delivery estimate, and the next action.

## Using a pattern

1. Name the pattern and its variant in the working notes, then adapt it to the product's components and content before styling.
2. Replace every placeholder with real content or a labeled placeholder; do not pad a pattern to make it look full.
3. Check the responsive collapse rule for the pattern at the narrow and wide widths before calling the surface done.
