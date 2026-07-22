# ADR-0001: CLI Bridge Over Direct DB Reads

## Status

Accepted (retroactive record of existing design — the code below predates this document).

## Context

The Agentic OS state plane is a SQLite database (`state.db`, WAL mode) plus
JSONL files under the OS root, continuously written by the running OS
dispatcher process. The command center needs point-in-time reads of that
state — conversation lists, scope tree, runtime health, per-conversation
transcripts — to render its UI.

Two ways to get there were available:

1. Open `state.db` / the JSONL files directly from the Electron main process (e.g. `better-sqlite3`) and re-implement whatever normalization the state plane already needs.
2. Shell out to the `agentic-os` CLI — a Python package living in the same repo that already owns this normalization — and parse its structured JSON output.

## Decision

The GUI reads OS state **only** by spawning the `agentic-os` CLI. It never
opens `state.db` or the JSONL files directly, from any process.

Implementation, `AosBridge` in `src/main/aosBridge.ts`:

- `execFileAsync` (`promisify(execFile)`) invokes the CLI as a subprocess for every read.
- `MAX_OUTPUT_BYTES = 32 * 1024 * 1024` (32 MiB) is passed as `maxBuffer` on every call.
- `timeout: 30_000` (30s) is set on every call.
- Snapshot: `execFileAsync(executable, ["gui", "snapshot", "--root", root, "--json"], { encoding: "utf8", maxBuffer: MAX_OUTPUT_BYTES, timeout: 30_000 })`.
- Transcript: `execFileAsync(executable, ["gui", "transcript", "--root", root, "--provider", provider, "--conversation-id", id, "--json"], { ...same options })`.
- The executable path is resolved by `resolveAgenticOsCli()`: an `AGENTIC_OS_CLI` env var override, then the packaged runtime binary (`~/Library/Application Support/AgenticOSGui/runtime/bin/agentic-os`), then `~/.local/bin/agentic-os`, then Homebrew paths, falling back to a bare `agentic-os` on `PATH`.
- Output is parsed with `parseJson<T>()`, which throws a named error (`"<operation> returned invalid JSON: ..."`) on malformed output instead of failing silently.

Freshness without polling comes from `WatchCoordinator` in `src/main/watch.ts`:
`fs.watch(target, { recursive: true }, ...)` on the OS root plus the harness
session directories (`~/.codex`, `~/.claude/projects`, `~/.claude/sessions`,
the Claude desktop session store), filtered through `isRelevantWatchPath()`
(matches `project.yaml`/`work.yaml`, `*.jsonl`, `local_*.json`,
`state*.sqlite(-wal)`, `.codex-global-state.json`, `state.db(-wal)`), debounced
500ms (`debounceMs = 500` default) before calling `bridge.invalidate()` and
re-snapshotting.

### Why not direct DB reads

- **Single owner of state-plane semantics.** The CLI already normalizes this data; a second reader duplicates that logic and the two will drift the moment either side changes independently.
- **No WAL/lock contention with the dispatcher.** The dispatcher writes continuously; a second process holding read locks on the same WAL file is a contention and consistency risk the CLI's own access patterns already account for.
- **Version skew is loud, not silent.** If an installed CLI's `gui snapshot --json` shape changes, `parseJson` throws a named, operation-tagged error. A direct-DB reader would instead silently misread a renamed column or table.
- **500ms-debounced invalidation is an acceptable freshness bound** for a desktop control surface that is not a hard real-time system.

## Consequences

- Snapshot latency floor is CLI-spawn cost plus the CLI's own snapshot-build time, not a raw SQL query cost. This is not benchmarked in this document; it is cheap enough today for one operator with a moderate conversation count.
- Every read pays a process-spawn and JSON (de)serialize cost — fine for a snapshot-per-interaction model, wrong for tight per-keystroke polling.
- Heavier future dashboards (automation dashboard, work-queue watcher, system health — see `../ROADMAP.md` Phase 3) will likely outgrow the two current verbs (`gui snapshot`, `gui transcript`). The extension point is a new CLI surface — e.g. `gui query --json` — not a side-channel direct DB read. This ADR's rule applies to those dashboards equally; it is not scoped to the conversation view alone.
- Repeated in-session snapshot cost is mitigated separately, by `AosBridge`'s single-flight + generation-counter cache (see ADR-0004, Tier 4) — that is a caching decision layered on top of this one, not a substitute for it.

### Alternatives considered

- **Direct SQLite read (`better-sqlite3`) from the main process** — rejected: duplicates CLI parsing/normalization, WAL lock contention with the dispatcher, silent schema drift across CLI upgrades.
- **Direct JSONL tailing** — rejected: same duplication problem; several state facts (scope tree, runtime health aggregates) are computed by the CLI, not stored flat in any single file.

## Revisit-when

- Snapshot p95 latency exceeds 1.5s under real usage, **or**
- A dashboard needs sub-500ms query turnaround that a spawn-per-call model cannot deliver.

Either trigger: extend the CLI with a batched/queryable surface (`gui query
--json` or equivalent). Do not respond to either trigger by reaching around
the CLI into `state.db`.

## Diagram

```
 Renderer                Main process                          Agentic OS
 --------                ------------                          ----------
                    +-----------------+
 useSnapshot() ---> | ipcMain.handle  |
     ^              |  IPC.snapshot   |
     |              +--------+--------+
     |                       |
     |                       v
     |              +-----------------+   execFile (30s, 32MB)   +-------------+
     |              |    AosBridge    | -----------------------> | agentic-os  |
     |              | single-flight + |   gui snapshot --json    |     CLI     |
     |              | gen. counter    | <----------------------- +------+------+
     |              +--------+--------+        stdout JSON              |
     |                       ^                                          v
     |                       | invalidate()                     state.db (WAL)
     |              +--------+--------+                          + JSONL files
     +------------- | webContents.send|
    IPC.snapshotChanged  ^  (sendSnapshot)
                          |
                 +--------+---------+
                 |  WatchCoordinator |
                 |  fs.watch, 500ms  |
                 |  debounce         |
                 +-------------------+
```
