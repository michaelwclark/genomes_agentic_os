# AgenticOSGui Desktop Conversation Driver

AgenticOSGui is the native local operator surface for driving Agentic OS work
through Codex and Claude. It adds interaction to the read-only engineering
cockpit without moving project, work-item, report, or lifecycle authority out of
the installed Agentic OS.

## What It Fixes

The Phase 1 cockpit intentionally inventories bounded transcript files. That is
useful for history and self-improvement mining, but it is not an open-task list.
AgenticOSGui instead reads each harness's current local session registry:

- Codex Desktop UI references and pins are joined read-only to its SQLite thread
  index and native session-name index.
- Claude Desktop local-agent metadata supplies native title, archive state,
  activity time, model, effort, cwd, and PR metadata; its `cliSessionId` joins to
  the transcript.
- Raw JSONL transcripts are loaded only for a selected conversation or for
  bounded reference extraction. They never determine whether a conversation is
  open.

Opaque labels such as `Conversation <uuid>` are not a valid title fallback. The
desktop index prefers the harness-native title, then a saved session name, then
a concise first-human-message title, and finally a route-aware `Untitled task`.

## Launch

```bash
agentic-os gui snapshot --root ~/agentic_os
agentic-os gui open --root ~/agentic_os
```

Source development lives in `apps/agentic-os-gui/`:

```bash
pnpm --dir apps/agentic-os-gui install
pnpm --dir apps/agentic-os-gui dev
pnpm --dir apps/agentic-os-gui test
pnpm --dir apps/agentic-os-gui build
pnpm --dir apps/agentic-os-gui package:mac
```

The desktop app does not run a web server in production. Electron loads local
packaged assets and communicates with its main process through a small typed IPC
bridge.

## Information Architecture

The primary hierarchy is:

```text
All Work
  Domain
    Project
      Conversations, work, reviews, reports, and assets
Unclassified
```

The conversation list defaults to provider-backed active/open sessions. Codex
history/backlog and Claude archived or CLI-only history are separate views. Pins
sort first, then native recency. Every row includes human title, compact age,
harness/provider, model presentation, and its current Agentic OS route.

Selecting a conversation exposes the visible user/assistant transcript and
locally derived Jira, PR, Slack, work-item, branch/worktree, report, and
filesystem references. Absence is shown as an explicit empty state rather than
invented linkage.

## Execution Fabric Operations

Open the `Execution Fabric` page from Command Center for the first-class
operator view. It consumes `agentic-os gui snapshot`, which in turn uses the
selected backend's normalized runtime snapshot; the renderer never opens
SQLite, PostgreSQL, Valkey, or service files directly.

The page exposes:

- waiting, running, completed, failed, retrying, delayed, and dead-letter work;
- named queue depth and limits;
- worker-pool utilization plus live, unhealthy, capacity, heartbeat, and lease
  state;
- active host, leader/standby role, epoch, failover state, and witness health
  when the selected backend reports them;
- effective config source/fingerprint and drift;
- effect outbox counts, active alarms, and healer status;
- current managed runs, bounded task history, and recent terminal run reports.

`Unknown` or `Not reported` is intentional when a compatibility backend does
not provide a field. Command Center does not manufacture cross-host health from
local process listings. Use `agentic-os runtime snapshot --json` for the same
machine-readable projection and CLI filtering when the bounded UI sample is
not exhaustive.

## Model Presentation And Routing

Provider and complexity are separate dimensions:

- OpenAI uses a teal/green hue.
- Anthropic uses an orange/coral hue.
- Unknown providers use neutral slate.
- `economy`, `balanced`, `frontier`, `frontier_max`, and `human_gate` increase
  brightness/chroma.
- reasoning effort adds a smaller intensity step from `low` through `ultra`.

Text always names provider/model/tier because color is not the only carrier.
The existing adaptive router is currently observe-only and its installed model
catalog is OpenAI-focused. The GUI may display current Anthropic sessions and a
provider-neutral presentation, but it must not claim automatic cross-provider
selection until the policy contract is deliberately extended and validated.

## Continuation And Realtime

Local updates do not require webhooks or WebSockets:

- Debounced filesystem watching refreshes Codex/Claude registries, transcript
  files, installed project/work-item state, and Agentic OS state-plane changes.
- Codex can stream through its local app-server protocol when the versioned
  adapter is supported; a one-shot JSON/PTY path remains the compatibility
  fallback because app-server is experimental.
- Claude supports public stream-JSON CLI output. Imported Claude Desktop
  sessions should fork into a GUI-owned session or use a single-writer lease so
  two applications do not mutate the same conversation concurrently.

WebSockets belong at a later authenticated remote-host boundary, not between a
local renderer and its own main process.

## Security Boundary

- `contextIsolation: true`, `nodeIntegration: false`, renderer sandboxing, and
  web security are required.
- The renderer cannot read arbitrary files, spawn processes, or construct shell
  commands.
- Main-process actions use fixed executable/argument arrays with validated IDs,
  prompt limits, URL schemes, and path boundaries. Shell interpolation is not
  used.
- Claude and Codex stores are read-only. AgenticOSGui pins, focus, route
  overrides, leases, and launched-session mappings are written atomically to its
  own application-support state.
- Raw user/assistant text is delivered only to the selected local renderer. It
  is not copied into fixtures, build logs, reports, or source control.
- Thread archival, cleanup, external Jira/Slack/GitHub writes, and remote-host
  mutation remain explicit guarded workflows.

## Contracts And Ownership

- `agentic-os-gui/v1` is the desktop composition contract.
- `agentic-os-cockpit/v1` remains the broad read-only work/report/review input
  and rollback view.
- Installed filesystem work items remain lifecycle source of truth.
- Existing state-plane tables remain the future event/queue/cursor substrate;
  the GUI does not create a competing event database.
- Electron-owned operator preferences are presentation state, not operational
  truth.

## Deep Documentation

The app maintains its own architecture suite under
[`apps/agentic-os-gui/docs/`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/ARCHITECTURE.md) —
read it before building app features:

- [`ARCHITECTURE.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/ARCHITECTURE.md) — process/layer
  model, IPC conventions, import rules, anti-patterns.
- [`FEATURE-PLAYBOOK.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/FEATURE-PLAYBOOK.md) —
  recipes for new pages, dashboards, watcher feeds, rail widgets, IPC.
- [`DESIGN-SYSTEM.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/DESIGN-SYSTEM.md) — design
  tokens, component conventions, data-viz standards.
- [`DATA-AND-EVENTS.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/DATA-AND-EVENTS.md) — truth
  inventory, read paths, streams, caching tiers.
- [`adr/`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/adr/README.md) and
  [`ROADMAP.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/docs/ROADMAP.md) — decision records and
  the phased growth plan (resizable shell, editor groups, page registry landed
  in Phase 1).

Agents landing directly in the app directory get the same map from
[`apps/agentic-os-gui/AGENTS.md`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/apps/agentic-os-gui/AGENTS.md).

## Rollback

Quit or remove the local app and continue using:

```bash
agentic-os cockpit open --root ~/agentic_os
codex resume <thread-id>
claude --resume <cli-session-id>
```

Removing AgenticOSGui does not alter vendor transcripts, project repositories,
work items, worktrees, or the Phase 1 cockpit. Its operator-state JSON can be
backed up or removed independently after the app is closed.
