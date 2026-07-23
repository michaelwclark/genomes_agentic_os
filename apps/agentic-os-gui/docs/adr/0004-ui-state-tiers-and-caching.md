# ADR-0004: UI State Tiers and Caching

## Status

Accepted.

## Context

State is accumulating in several different places with no written rule for
"where does new state go": ephemeral React state inside components, a
cross-session JSON file on disk, an about-to-land localStorage layout blob,
and an in-memory snapshot cache inside the CLI bridge (ADR-0001). Without an
explicit tier model, the default failure mode is state landing in whichever
mechanism its author reached for first — up to and including, eventually,
someone reaching for direct disk/DB access from the renderer, which ADR-0001
already forecloses.

## Decision

Five tiers. Each has one owning module and a one-line admission rule.

**Tier 1 — Ephemeral React state.** Selection, palette/menu open-state,
in-progress form input. Component state or a lightweight context. Never
persisted. This is the default; it needs no dedicated module.

**Tier 2 — `localStorage` key `aos.layout.v1`.** Layout **chrome only**:
`navWidth`, `listWidth`, `railWidth`, `visibility`, `centerSplitRatio`.
`schemaVersion: 1`; values clamped on read; writes debounced ~150ms. Owning
module: `src/renderer/layout/layoutState.ts`.
**Implemented** (landed in the same Phase 1 change as this ADR):
`createLayoutStore` persists with a 150ms debounce plus a `beforeunload`
flush, `deserializeLayout` repairs garbage per-field back to defaults, and
`useLayoutState` exposes the store via `useSyncExternalStore`.
Rule: if it's pixels/visibility of chrome and nothing else, it's
Tier 2. If it's "what did the operator decide," it's Tier 3.

**Tier 3 — `operator-state.json`.** Cross-session operator *semantics*: pins,
route overrides, launched sessions. **Confirmed implemented**,
`src/main/operatorState.ts`, class `OperatorStateStore`:

- Path: `join(app.getPath("userData"), "operator-state.json")`, where
  `userData` is remapped early in `src/main/index.ts` via
  `app.setPath("userData", join(app.getPath("appData"), "agentic-os-gui"))`
  — resolving to `~/Library/Application Support/agentic-os-gui/operator-state.json`
  on macOS, deliberately kept stable across the product's display-name
  rename (per the comment at that call site) so existing pins/overrides/leases
  survive it.
- Atomic write: `write()` writes to a temp path
  `${path}.${process.pid}.${Date.now()}.tmp` via `writeFile(..., { mode:
  0o600 })`, then `rename(temporary, this.path)` — no reader ever observes a
  partial write.
- Serialized mutation: `mutationTail: Promise<void>` — every `mutate()` call
  chains onto the prior one, so concurrent `setPinned`/`setLaunchedSession`
  calls apply in order instead of racing a read-modify-write.
- Schema-versioned: `schemaVersion: 1` on `OperatorState`; `read()` resets to
  `EMPTY_OPERATOR_STATE` if the stored value's `schemaVersion !== 1`.

Rule: if losing it on next launch would annoy the operator, it's Tier 3.

**Tier 4 — Main-process in-memory caches.** Not persisted; scoped to the
running process.

- **Confirmed today**: class `AosBridge` (`src/main/aosBridge.ts`) —
  `snapshotCache`, `snapshotInFlight: Promise<GuiSnapshot> | undefined`,
  `snapshotGeneration` counter. `snapshot()` returns the cached value unless
  `force`; concurrent callers share the one `snapshotInFlight` promise
  (single-flight) rather than triggering N CLI spawns for N simultaneous
  callers. `invalidate()` clears the cache and increments
  `snapshotGeneration`. Critically, the in-flight promise's continuation
  checks `generation !== this.snapshotGeneration` — if the generation moved
  while a load was already in flight, that stale result is discarded and
  `this.snapshot(true)` is called again, guaranteeing whoever called
  `invalidate()` gets a genuinely fresh snapshot rather than one that was
  already stale when it started loading. This is the "guaranteed trailing
  refresh after invalidate" behavior referenced elsewhere in this doc set.
- **Planned**: a general-purpose TTL query cache, shaped after
  `~/projects/ledgerline/src/ports/cache.port.ts`'s pattern. Confirmed real:
  `createCachePort(options)` returns an in-memory implementation
  (`createMemoryCacheRuntimePort`, backed by
  `~/projects/ledgerline/src/utils/memory-cache.util.ts`) when no URL is
  configured, or a Valkey/Redis-backed adapter when one is; the type contract
  lives in `~/projects/ledgerline/src/types/cache-port.types.ts`
  (`ICacheRuntimePort extends ICachePort`, `ICachePortOptions`). The command
  center only ever needs the memory-impl half — there is no server to point a
  URL at. *Caveat: this ADR confirms the port/factory file and the
  memory-vs-remote fallback split; it does not independently re-verify the
  literal `get<T>`/`set<T>(k, v, ttlSeconds)`/`del`/`setNx` method signatures
  on `ICacheRuntimePort` line-by-line — that method shape is carried forward
  as design intent, not a re-read citation.* Invalidation is topic-keyed,
  tying into ADR-0003's event topics: when a topic fires, cache entries
  registered under it drop.

Rule: if it's expensive to recompute and safe to lose on quit, it's Tier 4.

**Tier 5 — The OS state plane itself** (`state.db`, JSONL). Never cached to
disk by the GUI. Never written to directly, by any tier above. Reachable only
through the `agentic-os` CLI (ADR-0001). Authoritative, and lives outside
this app entirely.

### Decision table — where does new state go?

| New state is... | Goes in |
|---|---|
| UI-only, fine to lose on reload (selection, hover, open menu) | Tier 1 — component state |
| Chrome geometry/visibility only (pane widths, split ratio) | Tier 2 — `aos.layout.v1` |
| An operator decision that should survive restart (pin, route override, launched session) | Tier 3 — `operator-state.json` |
| A derived/expensive read from the OS state plane, safe to lose on quit | Tier 4 — in-memory cache (`AosBridge` today; TTL cache planned) |
| Anything the OS itself writes | Tier 5 — never touched directly; go through the CLI |

## Consequences

- No tier is a dumping ground. Tier 2 is explicitly *not* for operator
  semantics — chrome geometry and "what did the operator choose" look
  similar but carry different persistence/versioning needs, and conflating
  them is the most likely first violation of this ADR. Tier 4 is explicitly
  never written back to Tier 5.
- Every persisted tier (2, 3) carries a `schemaVersion`; a future format
  change is a version bump plus migration, not a silent shape drift.
- The renderer has zero direct filesystem or disk-backed-IPC access under
  this model. Tiers 2/3/4 are each owned by exactly one module
  (`layoutState.ts`, `operatorState.ts`, `AosBridge`); everything else routes
  through them.

## Revisit-when

- A sixth kind of state is proposed that does not map cleanly onto any of the
  five rows above — first sign is usually a change description that says
  "I'll also stash X in `operator-state.json`" for something that is not an
  operator decision. Resolve by adding a row to the decision table, not by
  overloading an existing tier; **or**
- Tier 4 needs to survive a main-process restart, not just persist within one
  run — at that point it has become Tier 3 (or a new tier), not "a bigger
  in-memory cache."

## Diagram

```
 Tier 1  Ephemeral React state         component / context, no persistence
   |
   v
 Tier 2  aos.layout.v1 (localStorage)  chrome geometry only     [PLANNED - Phase 1]
   |     layoutState.ts, schemaVersion 1, clamped, ~150ms debounce
   v
 --------------------------- IPC boundary ---------------------------------
   v
 Tier 3  operator-state.json           operator semantics       [CONFIRMED]
   |     operatorState.ts: atomic tmp+rename, mode 0600, mutationTail-serialized
   v
 Tier 4  Main-process in-memory cache  derived/expensive reads
   |     AosBridge: single-flight + generation counter          [CONFIRMED]
   |     TTL query cache, cache.port.ts shape                   [PLANNED - Phase 2]
   v
 --------------------------- CLI boundary (ADR-0001) -----------------------
   v
 Tier 5  OS state plane (state.db + JSONL)   never cached to disk by the GUI,
         never written to directly — CLI commands only.
```
