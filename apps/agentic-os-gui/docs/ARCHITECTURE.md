# Command Center Architecture

Canonical architecture for `apps/agentic-os-gui` — the Electron desktop command center over
the Agentic OS. Read this before writing any code in this app. Sibling docs:

| Doc | Owns |
|---|---|
| `docs/ARCHITECTURE.md` (this file) | System position, processes, layers, import rules, IPC conventions, growth model |
| `docs/FEATURE-PLAYBOOK.md` | Step-by-step recipes for adding pages, dashboards, watchers, panels, IPC |
| `docs/DATA-AND-EVENTS.md` | Where truth lives, read paths, streams, event backbone, caching tiers |
| `docs/DESIGN-SYSTEM.md` | Visual language, tokens, component styling rules |
| `docs/adr/` | Decisions and their revisit conditions |

Stack (verified against `package.json`): Electron 43 + electron-vite 5 + React 19 + TypeScript
strict + vitest. Runtime deps are exactly `react`, `react-dom`, `react-markdown`, `remark-gfm`.
No state library, no router, no CSS framework. This is a zero-new-deps culture — see §7.

---

## 1. System position

The GUI is a **projection and command surface** over the Agentic OS. It is never a second
source of truth. All OS state is owned by the OS itself and read through the `agentic-os` CLI.

```
~/agentic_os                          THE STATE PLANE (owned by OS + CLI, never this app)
├── harness/.../state.db(-wal)          SQLite execution-fabric state (queues/workers/tasks)
├── <domain>/.../work-items/...         work-item lifecycle packets (MD/YAML)
├── */project.yml, work.yml             YAML registries (domains, projects, routing)
└── ...
~/.codex, ~/.claude/projects,         HARNESS-NATIVE STORES (transcript JSONL, session
~/.claude/sessions, ~/Library/...     state) — also state plane, owned by the CLIs
        │
        │  reads only (never writes)
        ▼
  agentic-os CLI ──── `agentic-os gui snapshot --json` / `gui transcript --json`
        ▲                                          ▲
        │ execFile, 30s timeout, 32MB buffer       │ spawn `codex` / `claude` CLIs
        │ (src/main/aosBridge.ts)                  │ for interactive turns
┌───────┴───────────────────────────────────────────┴──────────────────────────┐
│ MAIN PROCESS  src/main/                                                       │
│   index.ts (composition root + IPC handlers)   aosBridge.ts (snapshot cache)  │
│   watch.ts (fs invalidation)                   sessionBroker.ts (turn spawns) │
│   operatorState.ts (GUI-owned overlay JSON)                                   │
└───────┬──────────────────────────────────────────────────────────────────────┘
        │ IPC — 8 invoke channels + 2 push channels (src/shared/contracts.ts)
┌───────┴───────────────┐
│ PRELOAD  src/preload/  │  frozen `window.agenticOS` bridge, typed AgenticOSApi
└───────┬───────────────┘
┌───────┴──────────────────────────────────────────────────────────────────────┐
│ RENDERER  src/renderer/ — React 19, sandboxed, no Node, connect-src 'none'    │
│   layout/ (shell: sash, layout state, workspace model)   pages/ (registry)    │
│   features/<feature>/ (per-feature hooks + components)   theme/ (tokens)      │
└──────────────────────────────────────────────────────────────────────────────┘
```

Two write paths exist, and only two:

1. **GUI-owned operator overlay** — pins, route overrides, launched-session leases — in
   `~/Library/Application Support/agentic-os-gui/operator-state.json`
   (`src/main/operatorState.ts`). This file belongs to the GUI; the OS never reads it.
2. **Command dispatch** — interactive turns are sent by spawning the same native `codex` /
   `claude` CLIs the OS uses (`src/main/sessionBroker.ts`). The CLIs mutate their own stores;
   the watcher then observes the change like any other and refreshes the projection.

Any feature that wants to "write OS state directly" is wrong by construction. Route it
through the CLI or file it as an OS/CLI feature.

## 2. Process architecture

| Process | Dir | Responsibilities | Must never |
|---|---|---|---|
| Main | `src/main/` | Composition root; CLI execution; fs watching; child-process brokering; operator-state persistence; all validation of renderer input; window lifecycle | Trust renderer-supplied ids/paths/urls; import renderer code; render UI |
| Preload | `src/preload/` | One frozen, typed bridge object per the `AgenticOSApi` contract | Contain logic, validation, or state; expose `ipcRenderer` raw |
| Renderer | `src/renderer/` | All UI; per-feature derived state; chrome persistence (localStorage) | Access fs/network/Node; hold OS truth beyond the last pushed snapshot |
| Shared | `src/shared/` | Contracts (types + channel names), pure validation, pure presentation, fixtures | Import from any other layer; touch Electron, Node APIs beyond types, or the DOM |

### Trust boundary (already enforced — cite these when reviewing)

| Rule | Enforcement |
|---|---|
| Renderer is sandboxed: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true` | `src/main/index.ts:148-155` |
| CSP pins scripts/styles to self and sets `connect-src 'none'` — the renderer cannot make network requests at all | `src/renderer/index.html:5-8` |
| New windows denied, navigation pinned to the app URL, webviews blocked | `src/main/index.ts:161-166` |
| The bridge is a single frozen object exposed as `window.agenticOS` | `src/preload/index.ts:26` |
| The bridge surface is a typed interface — every method and payload | `src/shared/contracts.ts:292-307` |
| Every invoke handler revalidates its arguments at the main edge; bad shapes throw | `src/main/index.ts:180-276`, `src/shared/validation.ts` |
| Resume ids are resolved **server-side** from the trusted snapshot + operator state — renderer ids are looked up, never forwarded to a spawn | `src/main/index.ts:55-71` (`trustedClaudeResumeId`), `src/main/sessionBroker.ts:8-13` (`BrokerTurnRequest.resumeId` doc) |
| External URLs pass an https-only host allowlist (github.com, linear.app, notion.so, `*.atlassian.net`, `*.slack.com`; no credentials, ≤4096 chars) | `src/shared/validation.ts:39-52` |
| Local open targets are realpath-resolved and containment-checked against the snapshot root before `shell.*` calls | `src/main/index.ts:88-136` (`trustedWorkItemPath`) |
| Provider stdout is untrusted: parsed line-by-line as JSON, unparseable lines dropped, extracted text capped at 100k chars, stderr tail capped at 1k | `src/main/sessionBroker.ts:102-135, 190-218` |

Every new IPC capability must preserve this posture. The review question is always: "if the
renderer were fully compromised, what is the worst this channel lets it do?"

## 3. Layer model

### 3.1 Main process — today

Four service singletons, adapter-ish, constructed once at the composition root
(`src/main/index.ts:285-298`), plus one `registerIpc()` containing all eight handlers
(`src/main/index.ts:180-276`):

| Service | File | Role |
|---|---|---|
| `AosBridge` | `src/main/aosBridge.ts` | CLI reads (`gui snapshot` / `gui transcript`), normalization, single-flight snapshot cache with generation counter |
| `WatchCoordinator` | `src/main/watch.ts` | Recursive `fs.watch` over state-plane roots, filename relevance filter, 500ms debounce → invalidate + push |
| `SessionBroker` | `src/main/sessionBroker.ts` | Spawns provider CLIs for turns, line-buffered stream-JSON parse → typed events, lease bookkeeping, SIGTERM→SIGKILL escalation |
| `OperatorStateStore` | `src/main/operatorState.ts` | Atomic JSON persist (temp+rename, mode 0600, serialized mutation tail) |

### 3.2 Main process — target shape (near-term refactor)

The single `registerIpc()` and flat `src/main/*.ts` are fine at 8 channels. They will not be
fine at 30. The target is the losmon registry pattern, adapted to Electron:

```
src/main/
  context.ts            MainContext type + createMainContext() — built ONCE in index.ts
  services/             aosBridge.ts, sessionBroker.ts, watch.ts, operatorState.ts (move as-is)
  ipc/
    conversations.ipc.ts   registerConversationsIpc(ctx)   (snapshot, transcript, set-pinned)
    turns.ipc.ts           registerTurnsIpc(ctx)           (send-turn, cancel-turn)
    shellTargets.ipc.ts    registerShellTargetsIpc(ctx)    (open-external, open-local-target)
    <feature>.ipc.ts       registerXxxIpc(ctx)             one file per feature from here on
  ipc.registry.ts       registerAllIpc(ctx) — explicit imports + calls, NO runtime scanning
  index.ts              composition root only: build ctx, call registry, window lifecycle
```

```ts
// src/main/context.ts — the ledgerline AppContext analog, Electron-flavored
export interface MainContext {
  bridge: AosBridge;
  broker: SessionBroker;
  watch: WatchCoordinator;
  operatorState: OperatorStateStore;
  logger: Logger;                       // console-backed until a real need appears
  paths: { osRoot: string; userData: string };
  clock: { now(): Date };               // injectable for tests; no bare Date.now() in features
  sendToRenderer(channel: string, payload: unknown): void;
}
```

Rules once this lands (and for any new IPC feature even before it lands):

- `MainContext` is built once, passed explicitly. No module-level singletons for new services.
- New main-side capability = factory (`createXxxService(deps)`) + `registerXxxIpc(ctx)` +
  one line in `ipc.registry.ts`. No classes for new services; the four existing classes are
  grandfathered, not precedent.
- Fields are concrete types today. Introduce a port interface only when a second
  implementation actually exists (test fakes inject via constructor/factory params instead —
  see §8).

Trigger for executing the refactor: the first PR that would push `registerIpc()` past ~10
handlers or `src/main/index.ts` past ~400 lines does the extraction as its first commit.

### 3.3 Renderer

```
src/renderer/
  layout/                  shell primitives — LANDED
    Sash.tsx                 pointer-drag divider (role=separator, dblclick resets)
    layoutState.ts           LayoutState schemaVersion 1: navWidth/listWidth/railWidth/
                             navVisible/railVisible/centerSplitRatio; clamped; persisted to
                             localStorage `aos.layout.v1`, debounced ~150ms;
                             createLayoutStore + useLayoutState
    workspaceModel.ts        WorkspaceTab discriminated union (kind 'conversation' | 'page');
                             EditorGroup { id: 'primary' | 'secondary', tabs, activeKey };
                             pure reducers: openConversationTab / openPageTab / closeTab /
                             splitActiveTabRight (max 2 groups, ⌘\) / focusGroup /
                             activateTab; closing a group's last tab collapses the split
  pages/
    registry.tsx             PageId → { title, render } map; first entry 'execution-fabric'
                             (the former fullscreen overlay, now an ordinary page tab)
  features/                  one dir per feature — TARGET (created by the first dashboard)
    <feature>/               <feature>.types.ts? no — payload types live in shared/contracts;
                             use<Feature>.ts hook(s) + components + pure helpers, co-located
  components/                pre-feature-era components (ScopeTree, ConversationList,
                             ConversationView, MetadataPanel, ExecutionFabricView) —
                             migrate into features/ opportunistically; do NOT grow this dir
  theme/
    tokens.css               canonical design tokens — all new styles use tokens
  App.tsx                    shell owner: snapshot subscription, workspace state, palette,
                             keyboard shortcuts
  styles.css                 the single stylesheet (consumes theme/tokens.css)
src/shared/                  leaf-pure: contracts.ts, validation.ts, presentation.ts, fixtures.ts
```

`features/<feature>/` is the losmon `data/<feature>/` analog: everything one feature needs,
co-located, mechanical to add, trivially deletable. Pages are thin: a registry entry whose
`render` composes feature components.

## 4. Import rules

| Importer | May import | Never imports |
|---|---|---|
| `src/shared/*` | other `src/shared` files only (types + pure functions) | electron, node runtime APIs, main, preload, renderer |
| `src/preload/*` | `electron`, `src/shared/contracts` | main, renderer, anything else |
| `src/main/services/*` | node builtins, `electron`, `src/shared` | renderer, preload, other services (wire via context) |
| `src/main/ipc/*` | `src/shared`, services **via `MainContext` param** | renderer, preload |
| `src/main/index.ts` (root) | everything main + shared | renderer internals |
| `src/renderer/theme` | nothing (CSS leaf) | — |
| `src/renderer/layout` | `theme`, `src/shared` | features, pages, main, preload |
| `src/renderer/features/<a>` | `layout`, `theme`, `src/shared` | **any other feature** (rule of three → promote the helper to `src/shared` or `layout`), main, preload |
| `src/renderer/pages` | `features`, `layout`, `theme`, `src/shared` | main, preload |
| `src/renderer/App.tsx`, `main.tsx` | all renderer + shared | main, preload |

Absolute rules: the renderer never imports from `src/main` or `src/preload` (types come from
`src/shared/contracts.ts`, values come through `window.agenticOS`). Main never imports from
`src/renderer`. `src/shared` stays leaf-pure — if a "shared" module wants `fs` or `electron`,
it is a main service, move it.

**Enforcement is by review today.** Listed follow-up (do it with the first `features/`
directory): add ESLint with `no-restricted-imports` / `import/no-restricted-paths` encoding
this exact table, the ledgerline pattern. There is currently no ESLint config in this app;
until it exists, PR review enforces the table verbatim — an import-rule violation is a
rejection, not a nit.

## 5. IPC contract conventions

Single source of truth: the `IPC` const at `src/shared/contracts.ts:279-290` and the
`AgenticOSApi` interface at `src/shared/contracts.ts:292-307`. No channel string literals
anywhere else, ever.

| Convention | Rule |
|---|---|
| Channel naming | `aos:<feature>-<verb>` — e.g. `aos:set-pinned`, `aos:send-turn`, `aos:snapshot-changed` |
| Shape per feature | One invoke pair (request → typed response) + optionally one push topic for unsolicited updates |
| Current invoke channels (8) | `aos:ui-config`, `aos:snapshot`, `aos:transcript`, `aos:set-pinned`, `aos:send-turn`, `aos:cancel-turn`, `aos:open-external`, `aos:open-local-target` |
| Current push channels (2) | `aos:snapshot-changed` (payload `GuiSnapshot`), `aos:stream-event` (payload `StreamEvent`: `started/delta/message/tool/completed/error`) |
| Payload typing | All request/response/push payloads are named interfaces in `contracts.ts`; structured-clone-safe (no functions, no class instances) |
| Validation | Main edge validates every argument before use — `unknown` in, typed out (`src/shared/validation.ts` pattern: `isConversationId`, `validateSendTurn`, `validateOpenLocalTarget`, `isAllowedExternalUrl`). New channels add their validator there or feature-local next to the ipc file |
| Errors | Handlers `throw new Error("operator-actionable message")`; renderer receives a rejected promise. Never return `{ ok: false }` shells for programmer errors — reserve result objects for expected outcomes (`SendTurnResult`) |

### The 4 hand-synced surfaces (today) and how the registry collapses drift

Adding one capability currently touches four files that must agree by hand:

1. `src/shared/contracts.ts` — channel name in `IPC`, payload types, `AgenticOSApi` method
2. `src/preload/index.ts` — one-line bridge method
3. `src/main/index.ts` `registerIpc()` — the validated handler
4. The renderer call site (feature hook)

TypeScript closes most of the gap — the preload `api` object is declared `AgenticOSApi`, so a
missing method fails `pnpm typecheck` — but nothing forces a handler to exist for every
`AgenticOSApi` method; a forgotten handler surfaces at runtime as a rejected invoke. The §3.2
refactor reduces surface 3 to "one `<feature>.ipc.ts` + one registry line" and makes the diff
reviewable per-feature. Surfaces 1, 2, 4 remain, deliberately: contracts stay the single
declaration point, and the preload stays a dumb mirror. Order of operations when adding a
channel is in FEATURE-PLAYBOOK.md Recipe E.

## 6. Data plane summary

All OS truth is read through exactly one funnel: `AosBridge` executes
`agentic-os gui snapshot --root <root> --json` and `gui transcript ... --json` via `execFile`
(30s timeout, 32MB output cap — `src/main/aosBridge.ts:151-235`), normalizes the result
(`normalizeSnapshot`, `aosBridge.ts:41-131`) and overlays the GUI-owned operator state (pins,
route overrides, launched-session ownership). Freshness is event-driven, not polled: the
`WatchCoordinator` watches the OS root plus the four harness-native stores with a relevance
regex and a 500ms debounce (`src/main/watch.ts:5-19,25`); every relevant burst invalidates
the bridge and pushes a fresh `GuiSnapshot` on `aos:snapshot-changed`. A generation counter
in the bridge guarantees one trailing refresh after any invalidation that raced an in-flight
CLI read, so a stale read is never cached as current.

Interactive turns are the second data path: `SessionBroker` spawns the provider CLI
(`codex exec resume … --json` / `claude --print --resume … --output-format stream-json`),
parses line-buffered stdout into typed `StreamEvent`s pushed on `aos:stream-event`, enforces
a per-conversation lease plus a global interactive-concurrency cap, and escalates
SIGTERM→SIGKILL on cancel. Full inventory-of-truth, latency budgets, the target typed event
bus + `aos:feed-event` multiplexed push, and the caching-tier rules live in
`docs/DATA-AND-EVENTS.md` — read that before building any dashboard.

## 7. Growth architecture — how ~100 pages stay sane

The target load is on the order of 100 pages/features: automation dashboards, a reporting
engine, work-queue watchers, system-health dashboards, admin surfaces. The load-bearing
mechanisms, in order:

1. **Page registry** (`src/renderer/pages/registry.tsx`) — a page is one `PageId → {title,
   render}` entry. No router, no route config, no lazy-loading ceremony until measured need.
   Opening a page = `openPageTab(pageId)` in the workspace model. 100 entries in one
   greppable map is a feature, not a smell.
2. **Editor groups** (`src/renderer/layout/workspaceModel.ts`) — conversations and pages are
   the same `WorkspaceTab` union, so every page composes with the split-view (max 2 groups)
   for free. Pages never invent their own window management.
3. **Feature modules** (`src/renderer/features/<feature>/`) — each feature's hooks +
   components co-located, importing only `layout`/`theme`/`shared`. Deleting a feature is
   `rm -r` plus its registry line and contracts entries.
4. **Tokens** (`src/renderer/theme/tokens.css`) — one visual vocabulary; per-page CSS forks
   are banned (§9), so 100 pages look like one product.
5. **One IPC grammar** (§5) — every feature's data access looks identical, so agents can
   build feature N+1 by pattern-matching feature N without re-deriving anything.

Deliberately absent, with revisit conditions (each has/gets an ADR in `docs/adr/`):

| Not here | Why | Revisit when |
|---|---|---|
| Router library | Page registry + workspace tabs IS the navigation model; URLs have no meaning in a desktop shell | Deep-linking from outside the app becomes a requirement |
| Redux/Zustand/etc. | Snapshot push + `App.tsx` shell state + per-feature hooks; the main process is already the store of record | Cross-feature client state (not derivable from snapshot) appears in 3+ features |
| HTTP server / web deploy | Main process IS the backend; IPC is the transport | A second client (browser, mobile) is actually commissioned |
| New runtime deps | Every dep is attack surface inside a shell that spawns CLIs | A dep would replace ≥300 lines of maintained code — requires an ADR before `pnpm add` |

## 8. Verification standard

| Gate | Command | Baseline (2026-07, this worktree) |
|---|---|---|
| Types | `pnpm typecheck` (`tsc --noEmit`, strict) | 0 errors |
| Tests | `pnpm test` (vitest) | 7 files, 43 tests, all pass, <1s |
| Build (before packaging claims) | `pnpm build` | clean |

Both gates green before declaring any change done; a regression against baseline is the
change's problem regardless of where it manifests.

Test style — pure functions + injected fakes, zero module mocks (`grep vi.mock tests/` is
empty; keep it that way):

- Export the logic as pure functions or parameter-injected factories, test those directly:
  `resolveAgenticOsCli(configured, home, exists)` (`aosBridge.ts:18`), `new
  SessionBroker(fakeSpawner, killGraceMs)` (`sessionBroker.ts:145`), `new
  OperatorStateStore(tmpPath)`, `normalizeSnapshot`, everything in `shared/presentation.ts`.
- Tests live in `tests/<module>.test.ts` (this app's existing convention — follow it; do not
  introduce co-located `*.spec.ts`).
- No Electron in tests. If a function can't be tested without Electron, extract the pure part
  until it can; the residue in `index.ts`/components stays thin enough to verify by running
  the app (`pnpm dev`, or `AOS_GUI_FIXTURE=1 pnpm dev` for the CLI-less fixture mode —
  `aosBridge.ts:147`, `index.ts:205`).

## 9. Anti-patterns (rejection list)

House rules adapted to this app. Any of these in a diff is a rejection, not a discussion:

1. **A second source of truth for OS state.** No sqlite readers, JSONL parsers, or YAML
   loaders in this app; reads go through the `agentic-os` CLI via `AosBridge`. If the CLI
   can't serve it, the CLI grows a subcommand first.
2. **Renderer touching fs/network/Node.** The CSP and sandbox make it fail; don't try to
   tunnel around them with new IPC that proxies arbitrary paths/URLs either — every channel
   stays narrow, validated, allowlisted.
3. **Polling where watcher push exists.** No `setInterval` refresh loops against snapshot
   data. Subscribe to `aos:snapshot-changed` (or a feed topic). Polling is legal only for
   external systems with no local event source, with a named interval constant
   (DATA-AND-EVENTS.md §6).
4. **Trusting renderer-supplied identifiers.** Resume ids, paths, URLs are resolved/validated
   main-side against trusted state, always (§2).
5. **Per-page CSS forks.** No page-scoped color/spacing/typography inventions, no inline
   style constants duplicating tokens. Tokens + shared classes only (DESIGN-SYSTEM.md).
6. **New runtime deps without an ADR.** Including "tiny" ones. Dev-deps get the same
   scrutiny at half the weight.
7. **`utils.ts` / `helpers.ts` / `common.ts`.** Named modules co-located with their domain;
   promotion to `src/shared` only on the third use (rule of three).
8. **New classes for services, DI containers, decorators.** Factories taking explicit deps.
   The four existing main classes are grandfathered, not precedent.
9. **Channel string literals outside `contracts.ts`,** or payloads typed `any`/`unknown`
   past the validation edge, or silent `as` casts across the IPC boundary.
10. **Cross-feature imports in `features/`.** Third use promotes the helper; before that,
    duplicate (rule of three beats coupling).
11. **Runtime registration magic.** No directory scanning for pages, ipc files, or handlers.
    Registries are explicit imports — greppable, diffable.
12. **Blocking the main process.** No sync CLI execution, no unbounded buffers beyond the
    existing 32MB snapshot cap; long work is async with a timeout, like every existing call.
