# ADR-0003: Event and Streaming Backbone

## Status

Accepted, phased. The decision and contracts below are recorded now; the bus,
the multiplexed channel, and the hook are **planned — Phase 2**
(`../ROADMAP.md`). Nothing in this ADR should be read as describing code that
exists in the tree today except where explicitly marked "confirmed today."

## Context

**Confirmed today** (`src/main/index.ts`, `src/preload/index.ts`,
`src/shared/contracts.ts`): the main process pushes to the renderer over
exactly two separate, purpose-built IPC channels:

- `IPC.streamEvent` — per-turn streaming deltas, sent via
  `mainWindow.webContents.send(IPC.streamEvent, streamEvent)` from inside the
  `sendTurn` handler.
- `IPC.snapshotChanged` — pushed by `sendSnapshot(...)`, triggered both by
  `WatchCoordinator`'s debounced invalidation (ADR-0001) and by mutation
  handlers such as `setPinned` that call `bridge.invalidate()` and then
  re-push.

Each channel has its own `ipcMain`/`webContents.send` wiring in
`src/main/index.ts` and its own dedicated preload listener (`onStreamEvent`,
`onSnapshotChanged` in `src/preload/index.ts`). This works fine at two
channels. It does not scale channel-per-feature: each planned Phase 3
dashboard (automation dashboard, work-queue watcher, system health) would
otherwise add its own `ipcMain`/`send`/preload-listener triple, each with its
own ad hoc typing and no shared backpressure or coalescing.

losmon already solved the server-side equivalent of this problem:

- `~/projects/losmon/src/adapters/eventbus.adapter.ts` — a typed in-process
  pub/sub wrapper over Node's `EventEmitter`. Confirmed shape:
  `emit<T extends EventType>(type: T, data: EventPayloadMap[T], opts?: {
  correlationId?: string })` builds an `AppEvent`, auto-stamping `timestamp:
  new Date()`, `instanceSlug`, and `version: 1` (plus the optional
  `correlationId`), then calls `emitter.emit('*', event); emitter.emit(type,
  event);` — a wildcard subscriber and type-specific subscribers both see it.
  `onAll(handler)` and `on(type, handler)` each return an unsubscribe
  closure (`() => emitter.off(...)`).
- `~/projects/losmon/src/adapters/websocket.adapter.ts` does exactly one
  thing with it: one `eventBus.onAll((event) => { for (const client of
  wss.clients) client.send(JSON.stringify(event)) })` subscription fans
  every event to every connected WebSocket client.
- `~/projects/losmon/src/ui/hooks/useWebSocket.ts` mirrors it client-side:
  one shared global `WebSocket`, a `Set<EventHandler>` of listeners,
  `useWsSubscription(handler)` adds/removes from that set inside a
  `useEffect` and reconnects on close.

## Decision

Bring the same shape in-process, adapted for Electron (no network socket, no
reconnect logic needed — IPC doesn't disconnect the way a WebSocket does):

- **Typed main-process EventBus** (planned): same `emit` signature and
  auto-stamping as losmon's — `{ timestamp, version }` at minimum.
  `instanceSlug` is losmon's multi-instance-server concept and is either
  dropped or repurposed (e.g. to a host/machine tag) here, since this is a
  single-instance desktop app, not a server fleet. Same wildcard `'*'` +
  specific-type dual emission. Same `on`/`onAll` returning unsubscribe
  functions.
- **One multiplexed IPC push channel, `aos:feed-event`** (planned), carrying
  `{ topic, event }`. This is the direct Electron analogue of losmon's
  `websocket.adapter`: one wildcard `eventBus.onAll(...)` subscription in the
  main process forwards every event to the renderer over this single
  channel, tagged with its topic, instead of a second transport.
- **A renderer hook `useFeed(topic)`** (planned), mirroring
  `useWebSocket.ts`'s shape: one shared underlying IPC listener, subscribe
  returns an unsubscribe cleanup function, no per-hook-instance IPC listener
  registration.
- **The two channels that exist today are not ripped out on day one.**
  `IPC.streamEvent` and `IPC.snapshotChanged` become the first two internal
  topics carried under this model — `WatchCoordinator`'s invalidation and any
  future watcher become new topics on the same bus rather than new one-off
  channels.
- **Backpressure, from first implementation**: coalesce same-topic events
  per animation frame; bound each topic's queue with drop-oldest semantics
  once full. This is a best-effort delivery bus for UI notification/refresh
  signals, not a guaranteed-exactly-once channel.

Event payloads are typed end-to-end via a discriminated union
(`EventPayloadMap`-shaped, in `src/shared/contracts.ts`, following losmon's
`EventPayloadMap` precedent) — not the ad hoc per-channel typing the two
existing channels use today.

Phasing: this ADR documents the decision and contracts now (Phase 1 doc
suite). The bus, `aos:feed-event`, and `useFeed` are Phase 2, gated on the
first dashboard that actually needs a third independent push topic.

## Consequences

- New push-style features get one hook (`useFeed(topic)`) instead of a
  bespoke IPC channel triple each time.
- rAF-coalescing and drop-oldest bounding mean this bus is for UI-facing
  notification/refresh signals, not for events that must never be dropped.
  Anything requiring guaranteed delivery needs its own explicit
  acknowledgement path — do not put it behind a `'*'` subscription.
- Until Phase 2 lands, feature authors keep using direct
  `ipcMain.handle`/`webContents.send` for anything genuinely one-off. This
  ADR does not retroactively require every future channel to wait on the
  bus — only recommends it once the bus exists.
- `IPC.streamEvent`/`IPC.snapshotChanged` migrating onto the bus (vs. staying
  as-is indefinitely) is an implementation choice for whoever builds Phase 2,
  not fixed by this ADR.

## Revisit-when

- A consumer needs delivery guarantees the coalesce/drop-oldest policy
  cannot provide — losing an intermediate event would be user-visibly wrong,
  not just a skipped animation frame. That consumer needs an explicit
  ack/outbox path, and this ADR's scope should be narrowed to say the bus is
  not for it; **or**
- Observed jank tracks with event volume/frequency on a single channel
  (not render cost) — at that point, consider a `MessagePort`-per-topic
  transport instead of one shared channel.

## Diagram

```
 Main process                                          Renderer
 ------------                                          --------
 +-------------------+
 |  domain code       |  emit<T>(type, data, {correlationId?})
 |  (watch, mutate,    | -------------------------------------+
 |   sendTurn, ...)    |                                       |
 +---------------------+                                       v
                                                     +---------------------+
                                                     |      EventBus        |
                                                     | (planned - Phase 2)  |
                                                     |  stamps {timestamp,  |
                                                     |   version}; emits    |
                                                     |   '*' + type         |
                                                     +----------+-----------+
                                                                | onAll(...)
                                                                v
                                                     +---------------------+
                                                     | webContents.send(    |
                                                     |  "aos:feed-event",   |
                                                     |  { topic, event })   |
                                                     +----------+-----------+
                                                                |
                       ================ IPC boundary ==========|============
                                                                |
                                                                v
                                                     +---------------------+
                                                     |  preload: forwards   |
                                                     |  aos:feed-event      |
                                                     +----------+-----------+
                                                                |
                                                                v
                                                     +---------------------+
                                                     |  useFeed(topic)       |
                                                     |  (planned - Phase 2)  |
                                                     +---------------------+

 Topics riding the bus once it exists:
   "snapshot-changed"  <- today's IPC.snapshotChanged (confirmed channel, existing)
   "stream-event"      <- today's IPC.streamEvent (confirmed channel, existing)
   "<watcher-x>"        <- future watcher invalidations (new topics, no new channels)
```
