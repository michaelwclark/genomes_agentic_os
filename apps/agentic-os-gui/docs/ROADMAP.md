# Command Center Roadmap

Phase 1 is in progress — landing the same night this document was written.
Phases 2–4 are this pass's proposed sequencing, not a locked backlog: reorder,
cut, split, or merge them freely. The ADRs in `adr/` constrain **how** each
phase is built once it's picked up; this document only proposes **what** and
**when**, and marks what's checkable when a phase is declared done.

MoSCoW tags on each phase reflect this doc's own opinion of priority, not a
commitment — Michael reorders as needed.

---

## Phase 1 — Foundation (in progress)

**Must.** This is landing now; treat it as close to committed, not a proposal.

| Item | Scope | State at time of writing |
|---|---|---|
| Design tokens | Formalize the CSS custom properties already in `src/renderer/styles.css` (confirmed today: `--border`, `--muted`, `--panel`, `--panel-raised`, `--focus`, plus scattered per-component tokens like `--model-accent`) into the system `../DESIGN-SYSTEM.md` defines. | Landed this session: `src/renderer/theme/tokens.css` (67 tokens incl. legacy aliases) + `DESIGN-SYSTEM.md`; `styles.css` refactored onto the tokens in the same change. |
| Resizable shell | A `Sash`-driven resizable shell, state persisted through `src/renderer/layout/layoutState.ts` (Tier 2, ADR-0004). | Landed this session: `layout/Sash.tsx` + `layout/layoutState.ts`, sashes at nav\|list, list\|workspace, and content\|rail. |
| Editor groups, 2-way split | `workspaceModel.ts` backs a two-pane split, toggled with `⌘\`. | Landed this session: `layout/workspaceModel.ts` pure reducers + split sash; last-tab close collapses, empty primary promotes secondary. |
| Page registry, execution-fabric as first tab | A page registry wires `src/renderer/components/ExecutionFabricView.tsx` in as the first registered page/tab. | Landed this session: `src/renderer/pages/registry.tsx` with `execution-fabric` as the first registered page; the old fullscreen overlay in `ConversationList` is removed and the view now opens as a page tab in the focused editor group. |
| Doc suite | This ADR set (`adr/`) plus `ROADMAP.md` (this file), alongside `ARCHITECTURE.md`, `FEATURE-PLAYBOOK.md`, `DATA-AND-EVENTS.md`, `DESIGN-SYSTEM.md` — authored concurrently by other agents in the same `docs/` directory this session. | Landed this session — all six present under `docs/`. |
| Auto-dev config bundle for this project | Scoped by the orchestrator brief for this doc pass; lives outside `apps/agentic-os-gui/src`. | Not independently verified by this pass — out of this agent's read scope. |

**Exit criteria**

- [x] `docs/adr/` (this set) + `docs/ARCHITECTURE.md` + `docs/FEATURE-PLAYBOOK.md` + `docs/DATA-AND-EVENTS.md` + `docs/DESIGN-SYSTEM.md` + `docs/ROADMAP.md` all present.
- [x] `src/renderer/layout/layoutState.ts` exists, `schemaVersion: 1`, and a `Sash`-driven resizable shell reads/writes it.
- [x] `⌘\` opens a second editor group; `workspaceModel.ts` backs the split.
- [x] A page registry exists with execution-fabric registered as the first tab, rendering the existing `ExecutionFabricView`.
- [x] `pnpm typecheck && pnpm test` green — verified at Phase 1 close: 0 type errors, 9 suites / 69 tests passing (7 pre-existing suites unregressed + `layoutState` + `workspaceModel`), `pnpm build` clean.

---

## Phase 2 — Plumbing (proposal)

**Should.** No dashboard strictly needs this to exist before Phase 3 starts,
but every dashboard in Phase 3 gets more expensive to add without it.

| Item | Scope | State at time of writing |
|---|---|---|
| Per-feature IPC registry | `registerXxxIpc(ctx)` per feature, called from one central `ipc.registry.ts`. | Today, every channel (`uiConfig`, `snapshot`, `transcript`, `setPinned`, `sendTurn`, `cancelTurn`, `openExternal`, `openLocalTarget`) is registered by one function, `registerIpc(store)`, in `src/main/index.ts`. |
| `MainContext` DI object | A composition-root context object built once, threaded through instead of reached for. | Today, `src/main/index.ts` holds services as module-level mutable bindings — `let mainWindow`, `let bridge: AosBridge`, `const broker = new SessionBroker()`. |
| EventBus + `aos:feed-event` + `useFeed` | ADR-0003's implementation. | Not started — ADR-0003 is "Accepted, phased," this is that phase. |
| TTL query cache | ADR-0004 Tier 4's planned half, shaped after `ledgerline`'s `cache.port.ts`. | Not started — `AosBridge`'s single-flight cache (Tier 4, confirmed) stays; this adds the general-purpose layer beside it. |
| ESLint `no-restricted-imports` layer enforcement | Encode layer-import rules (ports/adapters/data-style boundaries this app adopts) as lint, not convention. | Confirmed greenfield: no `.eslintrc*` or `eslint.config.*` exists anywhere in this worktree today, and `package.json` has no `lint` script. This is a new introduction, not an extension of existing config. |
| `styles.css` → tokens refactor, completion | Finish migrating raw values onto the Phase 1 token system. | Phase 1 starts the token system; today's `styles.css` still has raw hex custom properties outside of it. |

**Exit criteria**

- [ ] Every IPC channel is registered via a `registerXxxIpc(ctx)` function called from one central `ipc.registry.ts`; `registerIpc` in `src/main/index.ts` is gone or reduced to invoking the registry.
- [ ] A single `MainContext` is constructed once at startup and threaded through; no new module-level mutable service bindings.
- [ ] `aos:feed-event` channel is live; `IPC.streamEvent`/`IPC.snapshotChanged` consumers are migrated to `useFeed(topic)` or explicitly deferred with a stated reason.
- [ ] `eslint .` runs clean in CI with layer-import rules enforced.
- [ ] No raw hex colors remain in `styles.css` outside the token definition file.

---

## Phase 3 — Operator surfaces (proposal)

**Could**, roughly in the order listed — reorder freely based on what's
actually painful to check by hand week to week. Each item below follows the
feature-module recipe `../FEATURE-PLAYBOOK.md` defines (referenced here by
name and purpose only — this pass did not author or read that file's
internal steps).

| Page | Scope (1–2 lines) | Suggested dir | Page id |
|---|---|---|---|
| Automation dashboard | Run health/history for the OS's existing automations (security, dependabot, PR-maintenance, etc.) as a command-center page instead of log-diving. | `src/renderer/features/automation-dashboard/` | `automation-dashboard` |
| Work-queue watcher page | Live view of the work-intake/dev queue inside the command center, alongside (not replacing) CLI/Notion access. | `src/renderer/features/work-queue/` | `work-queue` |
| System health dashboard | Multi-host, multi-service runtime health, superseding the single-tab view `ExecutionFabricView` provides today. | `src/renderer/features/system-health/` | `system-health` |
| Reporting engine | On-demand/scheduled report generation and viewing inside the command center. | `src/renderer/features/reporting/` | `reporting` |

Each page reads exclusively through `AosBridge`/the CLI (ADR-0001) or the
Phase 2 IPC registry — no direct disk/DB access, no exceptions.

**Exit criteria**

- [ ] Automation dashboard page live, reading via CLI-backed IPC only.
- [ ] Work-queue watcher page live, reading via CLI-backed IPC only.
- [ ] System health dashboard page live, superseding or absorbing `ExecutionFabricView`.
- [ ] Reporting engine page live; any mutation goes through a governed CLI command (ADR-0002 rule), not a direct write.

---

## Phase 4 — Admin & beyond (proposal)

**Won't, until triggered** — this phase is explicitly gated, not just
low-priority. Build the first two items whenever Phase 3 feels stable; leave
the third alone entirely unless its trigger fires.

| Item | Scope | Gate |
|---|---|---|
| Admin pages (work items, registries, automations control) | Pages inside the command center per ADR-0002; mutations via governed CLI commands only; registration via the ledgerline-style explicit `admin.registry.ts`-shaped list. | None — proceed when there's an admin surface worth building. |
| Notifications / toasts | Surface EventBus topics (ADR-0003) that need operator attention (automation failure, PR check failure) as in-app toasts. | Depends on Phase 2's EventBus existing. |
| Optional remote read-only web export | A separate Express + React admin web app, reusing the main-process service layer over HTTP. | **Gated on ADR-0002's Revisit-when**: only if browser/remote access, or non-Michael users, become a real requirement. Do not build speculatively. |

**Exit criteria**

- [ ] Admin pages for work items, registries, and automations control live, each mutating only via a named CLI command.
- [ ] Toasts fire end-to-end from at least one EventBus topic.
- [ ] Remote web export stays unbuilt unless the ADR-0002(d) trigger condition is explicitly met and Michael signs off on building it.

---

## How to use this document

Phase 1's checkboxes are close to ground truth as of this writing — check
them against the tree before assuming any are done. Phases 2–4 are proposals:
their scope, ordering, and even existence are open for Michael to change.
What isn't open for renegotiation without a new ADR is *how* each phase's
work is built once picked up — that's what `adr/` is for.
