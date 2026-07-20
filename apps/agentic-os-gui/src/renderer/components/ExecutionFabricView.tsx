import { useMemo, useState } from "react";
import type { RuntimeHealth, RuntimeTask } from "../../shared/contracts";

interface ExecutionFabricViewProps {
  runtime: RuntimeHealth;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

const acronym = new Map([
  ["ai", "AI"], ["api", "API"], ["cli", "CLI"], ["gui", "GUI"], ["jira", "Jira"],
  ["llm", "LLM"], ["los", "LOS"], ["os", "OS"], ["osm", "OSM"], ["pr", "PR"], ["prs", "PRs"], ["sso", "SSO"],
]);

export function humanizeIdentifier(value: string): string {
  return value
    .replace(/[._-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => acronym.get(part.toLocaleLowerCase()) || `${part.charAt(0).toLocaleUpperCase()}${part.slice(1)}`)
    .join(" ");
}

const queueLabels: Record<string, string> = {
  claude: "Claude (LLM)",
  codex: "Codex (LLM)",
  filesystem: "Filesystem compatibility queue",
  non_llm: "Local tools & scripts",
  unrouted: "Unrouted work",
};

const queueLabel = (value: string) => queueLabels[value] || humanizeIdentifier(value);
const poolLabel = (value: string) => humanizeIdentifier(value.replace(/_workers$/, " workers"));
const taskLabel = (task: RuntimeTask) => task.display_name
  ? humanizeIdentifier(task.display_name)
  : `${humanizeIdentifier(task.kind || "Task")} · ${task.id.replace(/^queue_/, "").slice(0, 8)}`;
const workerLabel = (id: string) => {
  const match = id.match(/^runtime-(.+)-(\d+)-[a-z0-9]+$/i);
  return match ? `${match[1].split(".")[0]} · PID ${match[2]}` : humanizeIdentifier(id);
};
const activeLongRunStatuses = new Set(["queued", "preflight", "running", "paused", "cancelling"]);
const statuses = ["active", "all", "dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped", "cancelled", "dead-letter"];

export function operationalWorkers(runtime: RuntimeHealth) {
  const captured = Date.parse(runtime.captured_at);
  return runtime.workers.filter((worker) => {
    if (worker.active_tasks > 0) return true;
    if (worker.status !== "online") return false;
    const lease = worker.lease_until ? Date.parse(worker.lease_until) : Number.NaN;
    return Number.isNaN(captured) || Number.isNaN(lease) || lease >= captured;
  });
}

export function filterRuntimeTasks(tasks: RuntimeTask[], queue: string, status: string, query: string): RuntimeTask[] {
  return tasks.filter((task) => {
    const matchesQueue = queue === "all" || task.queue_name === queue;
    const matchesStatus = status === "all"
      || (status === "active" && ["queued", "approval-needed", "running", "blocked"].includes(task.status))
      || task.status === status;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || [task.id, task.display_name, task.kind, task.execution_target, task.worker_pool]
      .some((value) => value && (
        value.toLocaleLowerCase().includes(needle)
        || humanizeIdentifier(value).toLocaleLowerCase().includes(needle)
      ));
    return matchesQueue && matchesStatus && matchesQuery;
  });
}

export function taskSampleSummary(runtime: RuntimeHealth, shown: number): string {
  return `${shown} shown from ${runtime.task_sample_count}-task operational sample · ${runtime.task_count} retained`;
}

export function ExecutionFabricView({ runtime, onRefresh, refreshing }: ExecutionFabricViewProps) {
  const [queue, setQueue] = useState("all");
  const [status, setStatus] = useState("active");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const tasks = useMemo(() => filterRuntimeTasks(runtime.tasks, queue, status, query), [runtime.tasks, queue, status, query]);
  const selected = runtime.tasks.find((task) => task.id === selectedId);
  const needsAttention = runtime.dead_letter
    + runtime.unhealthy_workers
    + (runtime.stale_queued || 0)
    + (runtime.expired_running_leases || 0);
  const activeLongRuns = (runtime.long_running_runs || []).filter((run) => activeLongRunStatuses.has(run.status));
  const visibleWorkers = operationalWorkers(runtime);
  const hiddenWorkerHistory = runtime.historical_worker_records + Math.max(0, runtime.workers.length - visibleWorkers.length);
  const registeredWorkers = Math.max(runtime.registered_workers, runtime.workers.length);

  return (
    <section className="fabric-view" aria-label="Execution Fabric details">
      <header className="fabric-header">
        <div>
          <span className="eyebrow">Execution Fabric</span>
          <h2>Queue operations</h2>
          <p>Point-in-time backend truth captured {new Date(runtime.captured_at).toLocaleTimeString()}.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void onRefresh()} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh snapshot"}</button>
      </header>

      <div className="fabric-kpis">
        <article><span>Waiting now</span><strong>{runtime.queue_depth}</strong></article>
        <article><span>Running now</span><strong>{runtime.running}</strong></article>
        <article><span>Live workers</span><strong>{runtime.active_workers}</strong></article>
        <article><span>Retrying / delayed</span><strong>{runtime.retrying} / {runtime.delayed_retries}</strong></article>
        <article><span>Needs attention</span><strong>{needsAttention}</strong></article>
        <article><span>Recent failures (1h)</span><strong>{runtime.recent_failures}</strong></article>
        <article><span>Health</span><strong data-health={runtime.status}>{runtime.status}</strong></article>
      </div>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Running now</h3><span>{runtime.running_tasks.length} queue tasks · {activeLongRuns.length} managed runs</span></div>
        {runtime.running_tasks.length > 0 && <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Work</th><th>Queue</th><th>Worker</th><th>Started</th><th>Lease until</th></tr></thead>
            <tbody>{runtime.running_tasks.map((task) => (
              <tr key={task.id}>
                <th title={task.id}>{taskLabel(task)}</th><td title={task.queue_name}>{queueLabel(task.queue_name)}</td><td title={task.lease_owner}>{task.lease_owner ? workerLabel(task.lease_owner) : "Unclaimed"}</td><td>{task.started_at ? new Date(task.started_at).toLocaleTimeString() : "—"}</td><td>{task.lease_until ? new Date(task.lease_until).toLocaleTimeString() : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>}
        {activeLongRuns.length > 0 && <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Managed run</th><th>Status</th><th>Phase</th><th>Progress</th><th>Updated</th></tr></thead>
            <tbody>{activeLongRuns.map((run) => (
              <tr key={run.id}>
                <th title={run.id}>{run.label || humanizeIdentifier(run.id)}</th><td><span className="status-chip" data-status={run.status}>{run.status}</span></td><td>{run.phase || "—"}</td><td>{run.items_total ? `${run.items_completed || 0}/${run.items_total}` : "—"}</td><td>{run.updated_at ? new Date(run.updated_at).toLocaleTimeString() : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>}
        {!runtime.running_tasks.length && !activeLongRuns.length && <p className="fabric-empty">Nothing is running right now.</p>}
      </section>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Named queues</h3><span>{runtime.queue_mode.replaceAll("_", " ")}</span></div>
        <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Queue</th><th>Waiting</th><th>Running</th><th>Retrying</th><th>Delayed</th><th>Dead letters</th><th>Run limit</th><th>Queue limit</th></tr></thead>
            <tbody>{runtime.queues.map((item) => (
              <tr key={item.queue_name} data-selected={queue === item.queue_name}>
                <th title={item.queue_name}><button type="button" onClick={() => setQueue(queue === item.queue_name ? "all" : item.queue_name)}>{queueLabel(item.queue_name)}</button></th><td>{item.depth}</td><td>{item.running}</td><td>{item.retrying ?? 0}</td><td>{item.delayed_retries ?? 0}</td><td>{item.dead_letter}</td><td>{item.max_concurrency ?? "—"}</td><td>{item.max_queued ?? "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <p className="fabric-sample-note">History retained: {runtime.failed.toLocaleString()} failed tasks. {runtime.recent_failures.toLocaleString()} failed within the last hour. Historical failures do not count as currently running or waiting.</p>
      </section>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Worker pools</h3><span>{runtime.active_workers} live · {hiddenWorkerHistory.toLocaleString()} inactive registrations hidden</span></div>
        <div className="pool-grid">{runtime.worker_pools.map((pool) => (
          <article key={pool.name} className="pool-card">
            <div><strong title={pool.name}>{poolLabel(pool.name)}</strong><span>{queueLabel(pool.provider)}</span></div>
            <p>{pool.active_tasks} active of {pool.max_concurrency} task slots</p>
            <progress value={pool.active_tasks} max={Math.max(1, pool.max_concurrency)} />
            <small>{pool.live_workers}/{pool.max_workers} workers live · {pool.unhealthy_workers} unhealthy</small>
          </article>
        ))}</div>
      </section>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Active & unhealthy workers</h3><span>{visibleWorkers.length} operational rows · {registeredWorkers.toLocaleString()} retained registrations</span></div>
        {visibleWorkers.length > 0 && <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Worker</th><th>Status</th><th>Pool</th><th>Provider</th><th>Active</th><th>Capacity</th><th>Lease until</th></tr></thead>
            <tbody>{visibleWorkers.map((worker) => (
              <tr key={worker.id}>
                <th title={worker.id}>{workerLabel(worker.id)}</th><td><span className="status-chip" data-status={worker.status}>{worker.status}</span></td><td title={worker.pool_name}>{poolLabel(worker.pool_name)}</td><td>{queueLabel(worker.provider)}</td><td>{worker.active_tasks}</td><td>{worker.capacity}</td><td>{worker.lease_until ? new Date(worker.lease_until).toLocaleTimeString() : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>}
        {!visibleWorkers.length && <p className="fabric-empty">No workers are active or unhealthy right now.</p>}
      </section>

      <section className="fabric-section fabric-task-section">
        <div className="fabric-section-title"><h3>Task explorer</h3><span>{taskSampleSummary(runtime, tasks.length)}</span></div>
        <p className="fabric-sample-note">Active work is shown first. Choose All statuses to inspect retained history from this bounded sample.</p>
        <div className="fabric-filters">
          <input aria-label="Search sampled tasks" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search task ID, kind, target…" />
          <select value={queue} onChange={(event) => setQueue(event.target.value)} aria-label="Queue filter">
            <option value="all">All queues</option>{runtime.queues.map((item) => <option key={item.queue_name} value={item.queue_name}>{queueLabel(item.queue_name)}</option>)}
          </select>
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status filter">
            {statuses.map((item) => <option key={item} value={item}>{item === "all" ? "All statuses" : item === "active" ? "Active only" : humanizeIdentifier(item)}</option>)}
          </select>
        </div>
        <div className="fabric-task-layout">
          <div className="fabric-table-wrap">
            <table className="fabric-table fabric-task-table">
              <thead><tr><th>Task</th><th>Status</th><th>Queue</th><th>Target</th><th>Attempts</th><th>Updated</th></tr></thead>
              <tbody>{tasks.map((task) => (
                <tr key={task.id} data-selected={selectedId === task.id}>
                  <th title={task.id}><button type="button" onClick={() => setSelectedId(task.id)}>{taskLabel(task)}</button></th><td><span className="status-chip" data-status={task.status}>{task.status}</span></td><td title={task.queue_name}>{queueLabel(task.queue_name)}</td><td>{task.execution_target ? humanizeIdentifier(task.execution_target) : "—"}</td><td>{task.attempts ?? 0}</td><td>{task.updated_at ? new Date(task.updated_at).toLocaleTimeString() : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
            {!tasks.length && <p className="fabric-empty">No sampled tasks match these filters.</p>}
          </div>
          {selected && <aside className="task-drawer">
            <header><span className="eyebrow">Task detail</span><button type="button" onClick={() => setSelectedId(undefined)} aria-label="Close task detail">×</button></header>
            <h4>{taskLabel(selected)}</h4>
            <dl>
              <div><dt>ID</dt><dd>{selected.id}</dd></div>
              <div><dt>Status</dt><dd>{selected.status}</dd></div>
              <div><dt>Queue / pool</dt><dd>{queueLabel(selected.queue_name)} / {poolLabel(selected.worker_pool)}</dd></div>
              <div><dt>Target</dt><dd>{selected.execution_target ? humanizeIdentifier(selected.execution_target) : "—"}</dd></div>
              <div><dt>Worker</dt><dd>{selected.lease_owner ? workerLabel(selected.lease_owner) : "unclaimed"}</dd></div>
              <div><dt>Lease until</dt><dd>{selected.lease_until || "—"}</dd></div>
              <div><dt>Attempts</dt><dd>{selected.attempts ?? 0}</dd></div>
              <div><dt>Next eligible</dt><dd>{selected.due_at ? new Date(selected.due_at).toLocaleString() : "now"}</dd></div>
            </dl>
          </aside>}
        </div>
      </section>
    </section>
  );
}
