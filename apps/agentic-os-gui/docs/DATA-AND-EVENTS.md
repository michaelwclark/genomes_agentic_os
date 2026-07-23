# Data & Events

Where truth lives, how it reaches the UI, and the rules every dashboard/feed feature follows.
Read with ARCHITECTURE.md §6; recipes that apply this doc are in FEATURE-PLAYBOOK.md (B, C).

## 1. Inventory of truth

| Store | Owner | Mutated by | How the GUI sees changes |
|---|---|---|---|
| `state.db(-wal)`, `state_5.sqlite(-wal)` under `~/agentic_os` | OS execution fabric | OS/CLI processes only | Watcher regex match → snapshot refresh (§2) |
| Transcript JSONL (`~/.codex`, `~/.claude/projects`, `~/.claude/sessions`, `~/Library/Application Support/Claude/claude-code-sessions`) | Harness CLIs | The CLIs — including broker-spawned turns | Watcher `.jsonl` match → snapshot refresh; live mid-turn via `aos:stream-event` (§3) |
| YAML/MD registries (`project.yml`, `work.yml`, work-item packets) | OS + operator + agents | `agentic-os` CLI, editors | Watcher `(project\|work).ya?ml` match → refresh |
| `local_*.json`, `.codex-global-state.json` | Codex CLI | Codex | Watcher match → refresh |
| `operator-state.json` (`~/Library/Application Support/agentic-os-gui/`) | **GUI only** — the OS never reads it | `OperatorStateStore` via IPC (`aos:set-pinned`; launched-session lease persist in `aos:send-turn`) — atomic temp+rename, mode 0600, serialized mutation tail (`src/main/operatorState.ts:54-86`) | Mutation path itself invalidates + pushes (`src/main/index.ts:190-198, 234-249`) |
| `display.json` (userData) | Operator, hand-edited | Manual | Read per `aos:ui-config` invoke (`src/main/index.ts:34-53`) |
| localStorage `aos.layout.v1` | Renderer | `layoutState.ts` debounced (~150ms) writes | Synchronous, local, chrome-only |
| In-memory: bridge snapshot cache, broker leases, (future) tier-2 query caches | Main | `invalidate()` / lease lifecycle | They ARE the freshness mechanism, not stores of record |

Doctrine (ARCHITECTURE.md §1): rows 1–4 are the state plane — read-only to this app, reads
funneled through the `agentic-os` CLI. Rows 5–8 are GUI-owned. Nothing else may persist.

## 2. Read path today (snapshot pipeline)

```
fs change (any watched root)
  → fs.watch recursive callback                       src/main/watch.ts:31
  → filename relevance regex                          src/main/watch.ts:5
      (?:project|work).ya?ml$ | .jsonl$ | local_*.json$ |
      state_5.sqlite(-wal)$ | .codex-global-state.json$ | state.db(-wal)$
  → 500ms trailing debounce (bursts coalesce)         src/main/watch.ts:25,33-34
  → bridge.invalidate(); bridge.snapshot(true)        src/main/index.ts:290-293
      invalidate = clear cache + bump generation      src/main/aosBridge.ts:190-193
      snapshot   = execFile `agentic-os gui snapshot --root <root> --json`
                   (30s timeout, 32MB maxBuffer)      src/main/aosBridge.ts:158-162
      → normalizeSnapshot + operator-state overlay    src/main/aosBridge.ts:41-131
  → webContents.send("aos:snapshot-changed", snap)    src/main/index.ts:176-178
  → renderer replaces its snapshot state wholesale    src/renderer/App.tsx:66-73
```

### Single-flight + generation counter — exact semantics

`AosBridge.snapshot()` (`src/main/aosBridge.ts:151-188`) maintains three fields:
`snapshotCache`, `snapshotInFlight`, `snapshotGeneration`.

1. Cache hit: `!force && snapshotCache` → return it. No CLI call.
2. Single flight: if a load is in flight, **every** caller (even `force=true`) awaits the
   same promise. At most one CLI process runs at a time.
3. Each load captures `generation = snapshotGeneration` at start.
4. `invalidate()` clears the cache and bumps the generation. It does not cancel the in-flight
   CLI read — it makes its result uncommittable.
5. When a load settles, its continuation compares generations. If they differ, the data was
   read from a world that changed mid-read: the result (or error) is discarded and the
   continuation returns `this.snapshot(true)` — a fresh load under the new generation.

**Why one trailing refresh is guaranteed:** any `invalidate()` that lands during a load bumps
the generation, so that load cannot commit; its continuation must re-run. The re-run began
*after* the last invalidate, so the snapshot that finally commits reflects post-change disk
state. N invalidations during one read cost exactly one extra CLI call, not N. Stale data is
never cached, stale errors are never surfaced (the error path performs the same
generation check, `aosBridge.ts:174-180`), and callers blocked on the old promise transparently
receive the fresh result. The renderer additionally guards against out-of-order delivery with
its own request counter (`src/renderer/App.tsx:42-61`).

### On-demand reads (invoke path)

Two invoke channels also read the state plane, sharing the same bridge funnel:

- `aos:snapshot` — the renderer's explicit `getSnapshot()` **always forces a fresh CLI read**
  (`ipcMain.handle(IPC.snapshot, () => bridge.snapshot(true))`, `src/main/index.ts:185`).
  This is the "Refresh" button semantic: user-initiated refresh never serves cache. It still
  joins any in-flight load (single flight), so mashing refresh cannot stack CLI processes.
- `aos:transcript` — `execFile agentic-os gui transcript --root <root> --provider
  <codex|claude> --conversation-id <id> --json` (`src/main/aosBridge.ts:199-235`). If the
  conversation has a GUI-owned launched session (Claude fork, §3), the read is transparently
  redirected to the owned session id (`:209-211`) while the response keeps the source
  conversation id. Responses carry `truncated` and `continuation` metadata — render both;
  a truncated transcript silently presented as complete is a trust bug.

Transcripts are fetched on demand (tab focus, turn completion — `src/renderer/App.tsx:75-83,
164-172`), never cached across snapshot generations in the renderer.

### Latency budget

| Stage | Budget |
|---|---|
| fs event → debounce fire | 500ms fixed (`watch.ts:25`) |
| CLI snapshot exec + JSON parse | ~0.2–1s typical; 30s hard timeout |
| Normalize + overlay + IPC push + render | single-digit ms |
| **Disk change → UI, total** | **≈0.5–1.5s typical** |
| Stream delta: provider stdout line → renderer paint | **<100ms** |
| `send-turn` accepted → `started` event | spawn latency, ~50–300ms |

Features must tolerate the ~1s snapshot cadence. Anything that needs sub-second updates is a
stream (§3) or feed (§4), not a faster poll — there is no faster poll.

## 3. Live streams (interactive turns)

`SessionBroker` (`src/main/sessionBroker.ts`) is the only path that spawns provider CLIs:

- **Spawn** (`:56-84,168-173`): codex → `codex exec resume <resumeId> - --json
  --skip-git-repo-check`; claude → `claude --print --resume <resumeId> --input-format text
  --output-format stream-json --include-partial-messages --verbose` (+ `--fork-session
  --session-id <uuid>` for first GUI ownership of a Desktop conversation). Binary resolution:
  `CODEX_BIN`/`CLAUDE_BIN` env → known install candidates → bare name (`:33-54`). `cwd` =
  conversation cwd, `NO_COLOR=1`, `shell: false`; the prompt is written to stdin and stdin
  closed (`:257`). `resumeId` is always resolved server-side (`src/main/index.ts:207-233`) —
  never renderer input.
- **Parse** (`:207-215,190-206`): stdout is line-buffered (split on `\n`, partial line kept,
  flushed on close). Each line: JSON-parse → classify → emit `StreamEvent` on
  `aos:stream-event`. Text-bearing events become `kind: "delta"` with extracted content
  (multi-shape extraction, 100k char cap, `:102-135`); the rest become `kind: "tool"` with a
  sanitized `rawType`. Unparseable lines are dropped by design — provider stdout is untrusted.
- **Lifecycle**: `started` on accept → `delta`/`tool`* → `completed` (exit 0, after the
  `onCompleted` persistence hook: Claude-fork lease written to operator state, bridge
  invalidated, snapshot pushed — `src/main/index.ts:234-249`) or `error` (nonzero exit with
  scrubbed stderr summary + a copy-pasteable `fallbackCommand`, or spawn failure). The
  `"message"` kind exists in the contract (`contracts.ts:266`) but is **not emitted by the
  current broker** — do not depend on it.
- **Concurrency**: one lease per conversation (`:157-160`) plus a global interactive cap:
  `interactiveConcurrencyLimit(runtime)` (`src/shared/presentation.ts:3-5`) = `max(1,
  max_interactive_running)` when the OS runs `queue_mode === "execution_fabric"`, uncapped in
  legacy mode. Applied at `src/main/index.ts:250`. Rejections are polite `SendTurnResult`
  refusals, not errors.
- **Kill escalation**: cancel → SIGTERM, then SIGKILL after a 3s grace (`killGraceMs`,
  `:145,280-287`). App quit drains active leases before exiting
  (`src/main/index.ts:304-312`).

Renderer contract: subscribe via `window.agenticOS.onStreamEvent`, filter by
`conversationId`, keep a bounded buffer (the shell keeps the last 500, `App.tsx:76`), refetch
the transcript on `completed` — deltas are display transient; the transcript JSONL is truth.

## 4. Target event backbone (documented design — partially future)

Today there are exactly two push channels. That is correct for two producers and wrong for
twenty. **The rule: no third dedicated push channel, ever.** The first feature needing a new
push topic builds this backbone (losmon eventbus semantics, mapped to Electron):

```
main services / watchers                       renderer
  bus.emit(topic, event, {correlationId?})       useFeed(topic, handler)
        │  auto-stamps ts + version                    ▲ filters by topic,
        ▼                                              │ unsubscribes on unmount
  EventBus ── on(topic) / onAll() ──► feedBridge ──────┘
  (typed map, wildcard '*' then topic,   │ webContents.send("aos:feed-event",
   both return unsubscribe fns)          │                 { topic, event })
                                         └── ONE multiplexed push channel
```

- **Typed bus in main** (`src/main/services/eventBus.ts` when built): `emit<T extends
  FeedTopic>(topic: T, event: FeedEventMap[T], opts?: { correlationId?: string })`
  auto-stamps `ts` (ISO) and `version`; emits to `'*'` subscribers then topic subscribers;
  `on`/`onAll` return unsubscribe functions; handlers registered once at bootstrap via an
  explicit events registry — never at runtime, never by scanning.
- **One push channel**: `aos:feed-event` carrying `{ topic, event }`. Preload exposes one
  `onFeedEvent` listener; the renderer `useFeed(topic)` hook multiplexes. `FeedTopic` and
  `FeedEventMap` live in `src/shared/contracts.ts` like every other contract:

  ```ts
  // src/shared/contracts.ts — when the backbone lands
  export interface FeedEventMap {
    "automation-runs": { kind: "changed" } | { kind: "run-finished"; runId: string };
    "reports":         { kind: "changed"; reportId?: string };
    // one entry per topic — discriminated unions, no stringly-typed payloads
  }
  export type FeedTopic = keyof FeedEventMap;
  export interface FeedEnvelope<T extends FeedTopic = FeedTopic> {
    topic: T;
    event: FeedEventMap[T];
    ts: string;              // auto-stamped by the bus
    version: 1;              // envelope schema version, auto-stamped
    correlationId?: string;
  }
  ```

  ```ts
  // src/renderer/layout|shared hook — the ONLY way features consume pushes
  export function useFeed<T extends FeedTopic>(topic: T, onEvent: () => void): void {
    useEffect(
      () => window.agenticOS.onFeedEvent((envelope) => {
        if (envelope.topic === topic) onEvent();
      }),                       // preload returns the unsubscribe fn; cleanup calls it
      [topic, onEvent],
    );
  }
  ```
- **Invalidation topics per feature**: a feature's watcher/service emits on its own topic
  (`automation-runs`, `reports`, `work-intake`, …); tier-2 cache entries (§5) keyed by that
  topic drop on its events. `aos:snapshot-changed` is grandfathered as the de facto
  `snapshot` topic; `aos:stream-event` as the `turn` feed.
- **Batching (mandatory for high-frequency producers)**: coalesce to ≤1 push per animation
  frame — target the 30–60fps band. Emit arrays per topic per flush rather than event-per-fs-tick.
- **Backpressure**: per-topic bounded queue, drop-oldest beyond N (default 500, matching the
  renderer's stream buffer bound). When dropping, increment a per-topic dropped counter and
  surface it as a diagnostic — silent loss is worse than loss.

## 5. Caching tiers

| # | Tier | Lives in | Keyed by | Invalidated by | Use for |
|---|---|---|---|---|---|
| 1 | Snapshot memo + generation *(exists)* | `AosBridge` | singleton | Watcher → `invalidate()` | The OS projection. Never duplicate it |
| 2 | Main TTL query cache *(planned)* | Per-service, ledgerline `cache.port` shape: `get<T>(key)` / `set<T>(key, value, ttlSeconds?)` / `del` / `setNx`; in-memory impl | Query key, namespaced by topic | Topic events (§4) **and** TTL as backstop | Expensive CLI reads outside the snapshot (report renders, run histories) |
| 3 | Renderer derived *(exists)* | `useMemo` / pure helpers | Render inputs | Prop identity change | All pure derivation (`App.tsx:136-162` is the pattern). Never fetches |
| 4 | localStorage chrome *(exists)* | `aos.layout.v1` via `layoutState.ts` (schemaVersion 1, clamped, ~150ms debounce) | Schema-versioned key | User action; schema bump resets | Window chrome only — widths, visibility, split ratio. **Never OS data** |
| 5 | `operator-state.json` *(exists)* | `OperatorStateStore` | File (schemaVersion 1) | Mutation methods only, serialized | Durable operator overlay: pins, route overrides, launched-session leases |

**Choosing a tier**

- Comes from the state plane → it is already in tier 1, or belongs in tier 2 with a topic.
- Derivable from props/snapshot in front of you → tier 3. Always the first choice.
- Must survive restart: operational meaning → tier 5; cosmetic/layout → tier 4.
- Renderer module-scope caches of fetched data are tier-2 data in the wrong process — move
  them to main, or make them explicit SWR hook state with a topic subscription.

**Invalidation discipline** — the one rule that keeps 100 dashboards honest: **never cache
across a generation without a topic subscription.** Any copy of snapshot-derived or
CLI-derived data that outlives the read that produced it (tier-2 entry, hook-held SWR value,
module cache) must be subscribed to its invalidation topic (or `aos:snapshot-changed`) and
dropped/refreshed on events. TTLs are a backstop against missed events, not the mechanism.
An unsubscribed cache is a second source of truth — ARCHITECTURE.md §9.1, rejection.

## 6. Streaming-data rules for dashboards

1. **Push over poll, always.** The watcher + snapshot push and the §4 feed exist so features
   never poll local state. A `setInterval` against `getSnapshot()` is a rejected diff.
2. **Polling is legal only for external systems** with no local event source (e.g. a GitHub
   API a future feature queries directly from main). Requirements: a named interval constant
   in the feature dir (`const PR_POLL_INTERVAL_MS = 60_000` — greppable, reviewable), pause
   when the page/tab is not visible, and results cached in tier 2 so N widgets don't multiply
   the poll.
3. **SWR over IPC** — the standard dashboard hook shape:
   render cached value immediately → `invoke` fresh in the background → `useFeed(topic)`
   subscription triggers refresh (or applies small payloads directly). First mount: invoke,
   then subscribe, dedupe by stamped `ts` so the mount gap can't lose an update.
4. **Events carry facts, invokes carry state.** Feed events are small notifications
   ("runs changed", "run 42 finished"); bulk state always flows through the invoke path so
   normalization and caching stay in one place. Exception: §3 stream deltas, which are
   display-transient by contract.
5. **Never render per event.** Buffer feed/stream events and flush ≤ once per frame; keep
   buffers bounded (500-entry reference bound). The transcript/CLI read is truth; streams are
   ephemeral UI.
6. **Every stream/feed consumer unsubscribes on unmount.** The preload returns unsubscribe
   functions (`src/preload/index.ts:14-23`); `useFeed`/`useEffect` cleanup must call them —
   leaked listeners across 100 pages is death by a thousand pushes.
