# API workflows

Read this reference for native design-system lifecycle operations, preview cards, large or binary transfers, archives, or batching. All commands use the same scoped login and work in every agent through the CLI. They require no browser control. The first-party API supplements the live MCP catalog; it does not bypass the CLI's authorization, path, readback, and concurrency gates.

## Native design systems

```bash
open-claude-design design-systems list --json
open-claude-design design-systems settings --json
open-claude-design design-systems create 'Product design system' --allow-write --json
open-claude-design design-systems inspect <project-id> --json
```

`list` includes owned systems omitted by the MCP binding picker, with type, publication, and default metadata. `create` makes a real `PROJECT_TYPE_DESIGN_SYSTEM` project and verifies its type. Run it only after the user requested a new system. Regular `create_project` remains available through MCP for consumer projects and their initial binding.

Author files through `push`, using a current etag for every path. The design-system skill owns the package contents. `inspect` reports whether the host's compiled manifest exists; publishing does not prove compilation. Never invent or upload compiled `_ds_*`, adherence, or thumbnail files.

```bash
open-claude-design design-systems publish <project-id> --allow-write --allow-project-grant --json
open-claude-design design-systems unpublish <project-id> --allow-write --allow-project-grant --json
```

Publishing changes organization visibility and availability for binding. Obtain explicit authorization for that exact system and describe its reach first. These metadata operations need a server project grant. `--allow-project-grant` authorizes a temporary grant for this operation only: the CLI revokes a new grant and verifies revocation on success or failure. It preserves a grant that already existed. It never grants general file-writing authority as an authoring shortcut. An authentication or cleanup error leaves the outcome incomplete; reconnect and reconcile the named project's grant before continuing.

## Organization defaults and project metadata

```bash
open-claude-design design-systems settings --json
open-claude-design design-systems default <system-id> --if-current <reviewed-default-id> --allow-write --json
open-claude-design project inspect <project-id> --json
open-claude-design project rename <project-id> 'New name' --allow-write --allow-project-grant --json
```

Use `none` as the target or reviewed id when clearing an existing default or reviewing an empty default. Default changes affect newly created projects across the connected organization: require that explicit scope. The CLI checks the reviewed default, changes only `defaultDesignSystemProjectUuid`, and reads it back. It never changes interactive-only sharing restrictions. The API exposes no atomic revision condition for metadata updates; local locking and stale preflight checks do not claim cross-device atomicity.

Project inspection returns current design-system bindings. Authoring context resolves one binding automatically; for multiple bindings choose the relevant system explicitly. Renaming requires exact-project authorization and verified readback. Temporary grants are serialized across local agents and revoked after use; existing grants are preserved.

## Preview cards

Prefer authored `@dsCard` markers when the host indexes them. The API also supports explicit card registration for existing preview files:

```bash
open-claude-design design-systems cards <project-id> --json
open-claude-design design-systems register <project-id> --args '{"name":"Buttons","path":"components/buttons.card.html","section":"Components","viewport":{"width":700,"height":300}}' --allow-write --allow-project-grant --json
open-claude-design design-systems unregister <project-id> components/buttons.card.html --confirm-unregister components/buttons.card.html --allow-write --allow-project-grant --json
```

Registration verifies the file exists and reads the card back. Unregistration requires authorization for that exact card, verifies its absence, and retains the underlying file. Card status such as `ASSET_STATUS_NEEDS_REVIEW` remains explicit; registration is not approval or publication.

## Existing-project bindings and deletion

```bash
open-claude-design project inspect <project-id> --json
open-claude-design project bind <project-id> --design-system <system-id> --if-current none --allow-write --allow-project-grant --json
open-claude-design project bind <project-id> --clear --if-current <reviewed-system-id> --allow-write --allow-project-grant --json
open-claude-design project delete <project-id> --if-version <reviewed-version> --confirm-project <project-id> --allow-write --allow-destructive --allow-project-grant --json
```

Binding can select multiple systems by repeating `--design-system`. Review current bindings first; pass their comma-separated ids as `--if-current`, or `none` for no binding. The CLI checks types and current bindings, changes bindings through the dedicated API, and verifies their ids. Layout metadata is returned by the service and is not forced by the CLI. A changed binding needs a new authoring context; the CLI resolves a single binding automatically and requires an explicit choice for multiple bindings.

Project deletion requires the user's explicit authorization for that entire exact project, including its files and conversations. Never infer it from "cleanup," an obsolete-looking name, or approval of one file deletion. Inspect metadata/version and inventory first, offer a ZIP export when preservation is wanted, and pass all confirmation flags only after approval. The CLI checks delete permission and metadata freshness, rejects deleting the current organization default, and verifies absence through both project-type inventories. This is whole-project deletion, with metadata preflight rather than atomic file-etag protection. Deletion also revokes that deleted project's own grant, including a pre-existing grant; other projects' grants remain unchanged.

## Transfers and archives

```bash
open-claude-design pull <project-id> assets/font.woff2 --output ./scratch/font.woff2 --json
open-claude-design export <project-id> --output ./scratch/project.zip --json
open-claude-design export <project-id> --path components --output ./scratch/components.zip --json
```

Raw API reads preserve original text and binary data with their revisions, including files above the MCP read window. Each file is bounded at 16 MiB; writes and sync batches at 32 MiB; project exports at 128 MiB. Never treat a windowed MCP read as a complete file. Write and binary readback must match the exact source bytes. PNG read transports can add provenance: the CLI restores stored bytes only against revision-matched size metadata and rejects ambiguous reconstruction, retaining provenance already present in the stored file.

ZIP exports include project files plus a checksum/revision manifest. The complete inventory is checked again before atomic local publication; a concurrent edit saves no archive. Downloads remain opt-in artifacts: do not save project files or bundles unless the user requested them or local implementation requires them. Existing local outputs require `--force`; external local operands require exact-path authorization.

## Verification and batching

```bash
open-claude-design validate --local ./scratch/Page.dc.html --json
open-claude-design validate <project-id> Page.dc.html --json
open-claude-design preview <project-id> Page.dc.html --json
open-claude-design project pages <project-id> --json
open-claude-design batch --args '{"calls":[{"tool":"get_project","args":{"project_id":"<id>"}},{"tool":"list_members","args":{"project_id":"<id>"}}]}' --json
open-claude-design capabilities --json
```

Creation rejects non-editable `.dc.html` structure. Preview verification checks the API-issued HTML response and project resources without opening a browser. The installed Node runtime also parses logic scripts without executing them; syntax-check availability is reported. `render_executed: false` means JavaScript, layout, accessibility, and interactions still need visual/behavioral review. Never equate these checks with a screenshot or successful browser execution.

A durable preview proves a page renders by direct link, not that Claude Design's editor lists it: the Pages menu shows only root-level `.html` and `.dc.html` files. Every preview therefore reports `page_listed`, and `project pages` is the read-only inventory check: it lists root pages, nested pages with the root path each should use, and whether root `support.js` exists, and exits `2` when any page is nested. Keep pages at the root and assets in subfolders; `--allow-nested-page` on the write helpers is an explicit opt-out.

`batch` validates the entire group first and accepts only locally reviewed read-only tools. It uses one connection/catalog and stops at the first tool error. It cannot write, acknowledge comments, mint preview capabilities, or call unknown tools. Reads retry only bounded transient HTTP failures; mutations never automatically retry after an ambiguous outcome.

`capabilities` reports the current MCP catalog and the additional API workflows. In-conversation artifact migration, public/group artifact sharing, and native PDF/PPTX/Google Slides exports have no verified interface under this scoped connection. Do not promise them, substitute speculative endpoints, or start browser automation to imitate them.
