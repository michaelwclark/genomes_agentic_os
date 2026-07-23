# ADR-0002: Admin Dashboard In-App, Not AdminJS

## Status

Accepted.

## Context

The command center will need administrative/inspection surfaces beyond the
conversational view — browsing work items, registries, automations, config —
the kind of CRUD-ish surface AdminJS is built for. Two sibling reference
projects, `~/projects/losmon` and `~/projects/ledgerline`, both already run
AdminJS in production, so it was evaluated first rather than assumed away.

The state plane this app reads (per ADR-0001) is SQLite (`state.db`) plus
JSONL files — not a conventional ORM-backed relational schema — accessed only
through the `agentic-os` CLI, never directly.

## Decision

Admin/inspection surfaces ship as **pages inside the command center itself**
— page registry + feature modules — not AdminJS, and not a separate web app,
for v1. Any mutation from an admin page goes through a governed CLI command
(e.g. `agentic-os work upsert`), the same rule ADR-0001 already applies to
reads: no raw DB writes, ever, from any process this app controls.

Two concrete precedents are reused instead of inventing new plumbing:

- **Realtime**: losmon's WebSocket fan-out blueprint —
  `~/projects/losmon/src/adapters/websocket.adapter.ts` subscribes once via
  `eventBus.onAll(...)` and forwards every event to every connected client;
  `~/projects/losmon/src/ui/hooks/useWebSocket.ts` mirrors that client-side
  (one shared connection, a listener `Set`, subscribe returns unsubscribe).
  Adapted to Electron IPC push instead of a real WebSocket connection — see
  ADR-0003.
- **Registration**: ledgerline's admin registry pattern —
  `~/projects/ledgerline/src/registries/admin.registry.ts` exports
  `registerAllAdminResources(ctx, admin)`, an explicit flat list of ~20
  `registerXAdminResources(ctx, admin)` calls, one per feature module, no
  runtime scanning. This becomes the shape for admin **page** registration in
  this app (Phase 4 — see `../ROADMAP.md`).

### Alternatives considered

| | Option | Verdict | Why |
|---|---|---|---|
| (a) | AdminJS + `@adminjs/sql` | **Rejected** | `npm view @adminjs/sql` (re-verified independently for this ADR): `2.2.6`, dependencies `knex ^2.4.2`, `mysql2 ^3.3.3`, `pg ^8.10.0` only. Package description/keywords advertise Postgres/MySQL. No SQLite dialect is exposed. The state plane's primary store is SQLite — this package doesn't reach it. |
| (b) | AdminJS + a custom `ResourceAdapter` over `better-sqlite3` | **Rejected** (not merely harder — deferred indefinitely) | A custom `ResourceAdapter` is a real commitment (Resource/Property/filter/sort/pagination/actions), and it still inherits AdminJS's other fight-scars visible in both reference repos (below). JSONL-backed state has no AdminJS "resource" concept at all, so it would need a second bespoke resource type on top. And it duplicates a UI shell this app already has. |
| (c) | Pages inside the command center (page registry + feature modules) | **Chosen** | See Decision above. |
| (d) | A separate Express + React admin web app | **Deferred**, not rejected | Revisit if browser-based/remote access, or non-Michael users, become a real requirement. If so, reuse the same main-process service layer over HTTP — do not build a second implementation of the admin logic. See Revisit-when. |

**AdminJS fight-scars, cited from the two reference repos, informing the
rejection of (b):**

- `~/projects/losmon/src/init/admin.init.ts`: AdminJS's static asset router
  defaults to `dotfiles: 'ignore'` and 404s any path containing a dot
  segment. losmon works around this by intercepting asset routes first and
  re-serving them with `{ dotfiles: 'allow' }` (two call sites: the bundle
  passthrough, and `res.sendFile(path.resolve('.adminjs/bundle.js'), {
  dotfiles: 'allow' })`), on top of its own env-var admin auth (`ADMIN_EMAIL`
  / `ADMIN_PASSWORD` / `ADMIN_SESSION_SECRET`, each with an insecure
  hardcoded fallback if the env var is unset — acceptable there because it's
  gated behind other network controls, not a pattern to inherit uncritically).
- `~/projects/ledgerline/patches/adminjs.patch`: patches AdminJS's own
  `router.js` asset-bundle resolution (`resolveDesignSystemBundle`) because
  the package-relative path AdminJS computes at import time doesn't survive
  pnpm's `.pnpm` store layout. The patch comment cites the upstream issue
  directly: `// Use process.cwd() so assets resolve on Render/pnpm
  (adminjs#1788)`.

A custom adapter under option (b) would still sit behind this same
patched/workaround router; it doesn't avoid the scar tissue, it just adds an
adapter on top of it.

## Consequences

- Admin pages share the renderer's existing design system, IPC bridge, and
  state tiers (ADR-0004) instead of standing up a second UI stack.
- No AdminJS dependency, no pnpm-patch to maintain, no asset-router
  workaround to carry forward. Confirmed today: `package.json` has no
  `adminjs`/`@adminjs/*` dependency of any kind — there is nothing to migrate
  away from, only something not to add.
- Single client, single machine, Electron-only for v1: no admin URL, no
  browser access, no remote/anonymous path. Deliberate scope cut (see
  alternative (d)), not an oversight.
- Every admin page's write path is gated on a CLI command existing first —
  pages cannot get ahead of the CLI's write surface, by construction.

## Revisit-when

- Someone other than Michael needs to view or operate this surface, **or**
- Remote/browser access to admin pages becomes a real requirement (e.g.
  checking automation status from a phone).

Either trigger: build alternative (d), the separate Express + React admin web
app, reusing the main-process service layer over HTTP. Do not build it
speculatively before one of these triggers is real.
