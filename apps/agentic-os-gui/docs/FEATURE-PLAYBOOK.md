# Feature Playbook

The "add anything in ~30 minutes" manual for `apps/agentic-os-gui`. Every recipe is a
numbered file-path checklist; if you are pattern-matching, pattern-match these, not whatever
file you happened to open first.

**Prerequisites — read before your first feature:**

1. `docs/ARCHITECTURE.md` — layers, import rules (§4), IPC conventions (§5), anti-patterns (§9)
2. `docs/DESIGN-SYSTEM.md` — tokens, component styling rules
3. `docs/DATA-AND-EVENTS.md` — required before any recipe that touches live data (B, C)
4. Baseline first: `pnpm typecheck && pnpm test` must be green before you start, so that a
   red gate afterward is unambiguously yours.

Pick a recipe:

| You are adding | Recipe |
|---|---|
| A page with no new data (composes existing snapshot/feature data) | A |
| A dashboard/report page needing a new data read | B |
| A new file/state source feeding invalidation or a feed | C |
| A widget in the metadata rail or a side panel | D |
| A new main-process capability (any new IPC channel) | E |

---

## Recipe A — New page (no new data)

A page is one registry entry rendering feature components. Worked example: the
**execution-fabric page-tab conversion** that just landed — the former fullscreen overlay
(`role="dialog"` mount at `src/renderer/components/ConversationList.tsx:133-135`) became an
ordinary workspace tab.

Files it touched — this is the complete shape of "add a page":

1. `src/renderer/pages/registry.tsx` — added the first entry: `'execution-fabric'` →
   `{ title: 'Execution Fabric', render: () => <ExecutionFabricView …/> }`.
2. `src/renderer/layout/workspaceModel.ts` — nothing to add; `openPageTab('execution-fabric')`
   already handles any registered `PageId` (tabs are a `'conversation' | 'page'` union).
3. Call site — the runtime strip / command palette entry now calls `openPageTab(…)` instead
   of toggling the overlay state.
4. `src/renderer/components/ExecutionFabricView.tsx` — reused as-is; page content renders
   inside the workspace tab instead of a `.fabric-overlay` dialog.
5. `src/renderer/styles.css` — dropped the overlay-specific chrome; page layout uses tokens.
6. Tests — pure helpers (`filterRuntimeTasks`, `operationalWorkers`, …) already covered in
   `tests/executionFabricView.test.ts`; unchanged.

Checklist for your page:

1. Add the `PageId` + entry in `src/renderer/pages/registry.tsx`. Kebab-case id, human title.
2. Put the page component in `src/renderer/features/<feature>/` (new pages do NOT add to
   `src/renderer/components/` — that dir is legacy).
3. Wire the open affordance (palette command, nav item, or link) to `openPageTab(id)`.
4. Style with tokens only. No new colors, no per-page CSS forks.
5. `pnpm typecheck && pnpm test`.

Pages get split-view (⌘\, max 2 groups), tab lifecycle, and layout persistence for free from
`workspaceModel.ts` + `layoutState.ts`. Do not build page-local tab/window management.

## Recipe B — New dashboard page with live data

Fully worked hypothetical: **Automation Runs dashboard** — table of recent automation runs
(id, status, duration, last failure), live-updating. Read DATA-AND-EVENTS.md §5–6 first to
pick your caching tier and update mechanism; the default is SWR-over-IPC: render cached →
invoke fresh → subscribe to a topic.

Decision 0: **does `GuiSnapshot` already carry the data?** Runtime health, queues, workers,
tasks, and long-running runs are already in `snapshot.runtime`
(`src/shared/contracts.ts:181-213`). If your dashboard is a projection of existing snapshot
data, skip steps 2–8 entirely: it's Recipe A plus a `useMemo`. Only add IPC for data the
snapshot does not carry. For this example, assume runs history needs a new CLI read
(`agentic-os automation runs --json` or equivalent).

1. **Verify the CLI can serve it.** Run the subcommand by hand. If the CLI can't produce the
   JSON, stop — grow the CLI first (ARCHITECTURE.md §9.1). The GUI never parses OS files
   itself.
2. `src/shared/contracts.ts` — add payload types, extend `IPC` with
   `automationRuns: "aos:automation-runs"`, and add the `AgenticOSApi` method. One
   commit-able surface; channel names exist nowhere else.

   ```ts
   export interface AutomationRunSummary {
     id: string;
     automation: string;
     status: "queued" | "running" | "succeeded" | "failed" | "skipped";
     started_at?: string;
     finished_at?: string;
     duration_seconds?: number;
     failure_summary?: string;
   }
   export interface AutomationRunsResult {
     generated_at: string;
     runs: AutomationRunSummary[];
     diagnostics: Diagnostic[];
   }
   // IPC: automationRuns: "aos:automation-runs"
   // AgenticOSApi: getAutomationRuns(): Promise<AutomationRunsResult>;
   ```

3. `src/main/services/automationRuns.ts` — factory, not class; house pattern verbatim:

   ```ts
   export interface AutomationRunsServiceDeps {
     cli: string;                     // resolveAgenticOsCli() at the composition root
     osRoot: string;
     execFile?: typeof execFileAsync; // injectable for tests — no vi.mock, ever
   }
   export function createAutomationRunsService(deps: AutomationRunsServiceDeps) {
     return {
       async list(): Promise<AutomationRunsResult> {
         const { stdout } = await (deps.execFile ?? execFileAsync)(
           deps.cli, ["automation", "runs", "--root", deps.osRoot, "--json"],
           { encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 30_000 },
         );
         return normalizeAutomationRuns(JSON.parse(stdout)); // defensive, never trust shape
       },
     };
   }
   export type AutomationRunsService = ReturnType<typeof createAutomationRunsService>;
   ```

   Mirror `AosBridge`'s call discipline: `--json`, 30s timeout, bounded `maxBuffer`, and a
   defensive normalizer (`normalizeSnapshot` at `src/main/aosBridge.ts:41-131` is the
   reference — every array defaulted, every number coerced). Cache per DATA-AND-EVENTS.md §5
   tier 2 if the read is expensive.
4. `src/main/ipc/automationRuns.ipc.ts` — `registerAutomationRunsIpc(ctx)` with the
   validated `ipcMain.handle(IPC.automationRuns, …)`. (Until the §3.2 registry refactor
   lands, this is a handler block inside `registerIpc()` at `src/main/index.ts:180-276` —
   same code, different host file.)
5. `src/main/ipc.registry.ts` — one `registerAutomationRunsIpc(ctx)` line. (Pre-refactor:
   nothing; `registerIpc` is the registry.)
6. **Push topic** — if the data changes while the user watches: emit on the multiplexed
   `aos:feed-event` channel with topic `automation-runs` (DATA-AND-EVENTS.md §4), invalidated
   from the watcher (Recipe C) or from the service's own write path. Pre-backbone fallback:
   piggyback on `aos:snapshot-changed` and re-invoke on push.
7. `src/preload/index.ts` — one line: `getAutomationRuns: () =>
   ipcRenderer.invoke(IPC.automationRuns)`. Typecheck fails until this exists (the `api`
   object is declared `AgenticOSApi`).
8. `src/renderer/features/automation-runs/useAutomationRuns.ts` — the SWR hook (render
   cached → invoke fresh → subscribe topic; DATA-AND-EVENTS.md §6.3):

   ```ts
   export function useAutomationRuns() {
     const [result, setResult] = useState<AutomationRunsResult>();
     const [error, setError] = useState<string>();
     const refresh = useCallback(() => {
       window.agenticOS.getAutomationRuns().then(setResult).catch((e) => setError(String(e)));
     }, []);
     useEffect(refresh, [refresh]);            // invoke on mount (stale value renders first)
     useFeed("automation-runs", refresh);      // topic events trigger re-invoke; auto-unsub
     return { runs: result?.runs, generatedAt: result?.generated_at, error, refresh };
   }
   ```

   All non-trivial derivation (grouping, failure windows) goes in exported pure helpers next
   to the hook so `tests/` can hit them without React.
9. `src/renderer/features/automation-runs/AutomationRunsPage.tsx` (+ small components in the
   same dir) — presentational; all derivation in the hook or pure helpers next to it.
   Imports only `layout`/`theme`/`shared` (ARCHITECTURE.md §4).
10. `src/renderer/pages/registry.tsx` — entry `'automation-runs'` → `{ title: 'Automation
    Runs', render: () => <AutomationRunsPage/> }`.
11. Styling — tokens from `src/renderer/theme/tokens.css`; table/KPI patterns per
    DESIGN-SYSTEM.md (`ExecutionFabricView`'s `.fabric-kpis`/`.fabric-table` are the sibling
    to mirror).
12. Tests — `tests/automationRuns.test.ts`: service factory with a fake `execFile`
    (the `tests/sessionBroker.test.ts` fake-spawner style; zero `vi.mock`), normalization
    edge cases (empty/malformed CLI output), and the hook's pure derivation helpers.
13. `pnpm typecheck && pnpm test` — green, zero regressions vs baseline.

## Recipe C — New watcher feed

For a new on-disk source that should refresh the UI (or feed a topic) when it changes.

1. **Same snapshot, new trigger** (most common): extend `RELEVANT` at `src/main/watch.ts:5`
   (filename regex) and/or `watchTargets()` at `src/main/watch.ts:11-19` (watched roots —
   currently the OS root, `~/.codex`, `~/.claude/projects`, `~/.claude/sessions`,
   `~/Library/Application Support/Claude/claude-code-sessions`). The existing 500ms debounce,
   invalidate-then-push pipeline (`src/main/index.ts:290-294`) does the rest. Add a regex
   case to `tests/watch.test.ts`. Done.
2. **New feed with its own topic** (data outside the snapshot): new
   `createXxxWatcher(deps: { onChange })` service following `WatchCoordinator`'s shape —
   recursive `fs.watch`, relevance filter, debounce, swallow-errors-on-missing-target
   (`watch.ts:37-39`). Its `onChange` invalidates the owning service's cache (tier-2, keyed
   by topic) and emits `{ topic, event }` on `aos:feed-event` (DATA-AND-EVENTS.md §4).
   Register start/close in the composition root next to `watchCoordinator`
   (`src/main/index.ts:290-294`, close at `:305`).
3. Renderer side: `useFeed(topic)` subscription in the owning feature's hook.
4. Rules: debounce ≥ the existing 500ms unless you have a measured reason; never emit an
   unbounded event per fs event (coalesce); always handle the target-missing case silently —
   optional stores are a supported condition, and the snapshot diagnostics own visibility.

## Recipe D — New panel / rail widget

For content that rides alongside a conversation or page rather than owning a tab: the right
rail (today `MetadataPanel`, mounted at `src/renderer/components/ConversationView.tsx:106`,
visibility toggled by `railVisible` in `layoutState.ts` / ⌘U).

1. Build the widget in `src/renderer/features/<feature>/` as a self-contained component
   taking data via props (or its own hook if it has its own IPC — then Recipe E first).
2. Mount it in the rail host (`MetadataPanel` region) or the relevant page — widgets never
   position themselves; the layout shell owns geometry (`layout/Sash.tsx`, `layoutState.ts`
   widths are clamped and persisted).
3. Collapse/empty behavior: a widget with nothing to show renders nothing — the rail stays
   scannable at 100 features.
4. Tokens only; widget chrome patterns per DESIGN-SYSTEM.md.
5. Pure-logic tests for any derivation; `pnpm typecheck && pnpm test`.

## Recipe E — New IPC capability

The 4 hand-synced surfaces (ARCHITECTURE.md §5), **in this order** — the order makes
`pnpm typecheck` your progress meter:

1. `src/shared/contracts.ts` — channel in `IPC` (`aos:<feature>-<verb>`), payload types,
   `AgenticOSApi` method. Typecheck now fails at the preload: good.
2. `src/shared/validation.ts` (or feature-local validator) — `unknown` in, typed out; throw
   on anything else. Write this before the handler so the handler can't skip it.
3. `src/main/index.ts` `registerIpc()` — the handler: validate → resolve trusted state
   server-side → act → return typed result. (Post-refactor: `src/main/ipc/<feature>.ipc.ts`
   + one `ipc.registry.ts` line — ARCHITECTURE.md §3.2. The first PR to push `registerIpc`
   past ~10 handlers performs that extraction as its first commit.)
4. `src/preload/index.ts` — the one-line mirror. Typecheck green again.
5. Renderer call site — feature hook only; components never call `window.agenticOS` directly
   for new features.

Security review, every time (§2 of ARCHITECTURE.md): renderer input is hostile — ids get
looked up in trusted snapshot/operator state (`trustedClaudeResumeId`,
`src/main/index.ts:55-71` is the reference), paths get realpath + containment
(`trustedWorkItemPath`, `index.ts:88-136`), URLs get the allowlist
(`validation.ts:39-52`). New shell/spawn/fs capability needs the "renderer fully
compromised" argument written into the PR description.

Tests: validator cases in `tests/validation.test.ts` style; handler logic extracted into a
testable function or service factory if it exceeds a few lines.

---

## Near-term feature map

| Feature (named) | Recipe | Suggested ids / dirs |
|---|---|---|
| Automation dashboards (runs, schedules, failures) | B (data beyond snapshot) | `features/automation-runs/`, pages `automation-runs`, `automation-schedule` |
| Reporting engine (daily handoff, work-rhythm, token/cost reports) | B + C (report artifacts on disk → watcher feed) | `features/reports/`, pages `reports`, `report-viewer`; topic `reports` |
| Work-queue watchers (intake DBs, PR queues, tracker sync) | C feeding B-style pages | `features/work-queues/`, page `work-queues`; topics `work-intake`, `pr-queue` |
| System health dashboards (services, timers, memory MCP, watchers) | B; start as A if health lands in `GuiSnapshot.diagnostics`/`runtime` | `features/system-health/`, page `system-health` |
| Admin pages (display config, allowlists, watch targets, kill switches) | E (mutating IPC) + A for the page | `features/admin/`, pages `admin-general`, `admin-security` |
| Execution-fabric drilldowns (per-queue, per-worker) | A (all data already in `snapshot.runtime`) | `features/execution-fabric/`, pages `execution-fabric`, `queue-detail` |

Rule of thumb: **start every dashboard as Recipe A against existing snapshot data; upgrade to
B only when a field you need is genuinely absent.** The snapshot is deliberately rich
(`RuntimeHealth`, `src/shared/contracts.ts:181-213`) — most "new dashboards" are projections.

## Definition of done — every recipe

- [ ] `pnpm typecheck` — 0 errors; `pnpm test` — 0 failures, no baseline regressions
- [ ] Strict types at every public contract (contracts.ts, service factory signatures); no
      `any`, no silent `as`, `unknown` narrowed at the validation edge only
- [ ] Tokens only — no new colors/spacing/fonts outside `theme/tokens.css`
- [ ] Import rules hold (ARCHITECTURE.md §4) — especially: no cross-feature imports, no
      renderer→main imports, channel names only from `contracts.ts`
- [ ] New pure logic has tests in `tests/<module>.test.ts`, fake-injection style, no `vi.mock`
- [ ] No new runtime deps (an ADR in `docs/adr/` is the only path around this)
- [ ] Docs entry: page/feature added to the map above (or the relevant doc section) in the
      same PR — the next agent pattern-matches what you leave behind
- [ ] Anti-pattern sweep against ARCHITECTURE.md §9 — self-review the diff before handoff
