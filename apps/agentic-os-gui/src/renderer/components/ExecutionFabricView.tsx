import { useMemo, useState } from "react";
import type { RuntimeHealth, RuntimeTask } from "../../shared/contracts";

interface ExecutionFabricViewProps {
  runtime: RuntimeHealth;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

const taskLabel = (task: RuntimeTask) => task.id;
const statuses = ["all", "dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped", "cancelled", "dead-letter"];

export function filterRuntimeTasks(tasks: RuntimeTask[], queue: string, status: string, query: string): RuntimeTask[] {
  return tasks.filter((task) => {
    const matchesQueue = queue === "all" || task.queue_name === queue;
    const matchesStatus = status === "all" || task.status === status;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || [task.id, task.kind, task.execution_target, task.worker_pool]
      .some((value) => value?.toLocaleLowerCase().includes(needle));
    return matchesQueue && matchesStatus && matchesQuery;
  });
}

export function taskSampleSummary(runtime: RuntimeHealth, shown: number): string {
  return `${shown} shown from latest ${runtime.task_sample_count}-task sample · ${runtime.task_count} total`;
}

export function ExecutionFabricView({ runtime, onRefresh, refreshing }: ExecutionFabricViewProps) {
  const [queue, setQueue] = useState("all");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const tasks = useMemo(() => filterRuntimeTasks(runtime.tasks, queue, status, query), [runtime.tasks, queue, status, query]);
  const selected = runtime.tasks.find((task) => task.id === selectedId);

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
        <article><span>Queued</span><strong>{runtime.queue_depth}</strong></article>
        <article><span>Running</span><strong>{runtime.running}</strong></article>
        <article><span>Workers</span><strong>{runtime.active_workers}</strong></article>
        <article><span>Failed / dead</span><strong>{runtime.failed + runtime.dead_letter}</strong></article>
        <article><span>Health</span><strong data-health={runtime.status}>{runtime.status}</strong></article>
      </div>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Named queues</h3><span>{runtime.queue_mode.replaceAll("_", " ")}</span></div>
        <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Queue</th><th>Depth</th><th>Running</th><th>Failed</th><th>Dead</th><th>Run limit</th><th>Queue limit</th></tr></thead>
            <tbody>{runtime.queues.map((item) => (
              <tr key={item.queue_name} data-selected={queue === item.queue_name}>
                <th><button type="button" onClick={() => setQueue(queue === item.queue_name ? "all" : item.queue_name)}>{item.queue_name}</button></th><td>{item.depth}</td><td>{item.running}</td><td>{item.failed}</td><td>{item.dead_letter}</td><td>{item.max_concurrency ?? "—"}</td><td>{item.max_queued ?? "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <section className="fabric-section">
        <div className="fabric-section-title"><h3>Worker pools</h3><span>{runtime.workers.length} registered workers</span></div>
        <div className="pool-grid">{runtime.worker_pools.map((pool) => (
          <article key={pool.name} className="pool-card">
            <div><strong>{pool.name}</strong><span>{pool.provider}</span></div>
            <p>{pool.active_tasks} active of {pool.max_concurrency} task slots</p>
            <progress value={pool.active_tasks} max={Math.max(1, pool.max_concurrency)} />
            <small>{pool.live_workers}/{pool.max_workers} workers live · {pool.unhealthy_workers} unhealthy</small>
          </article>
        ))}</div>
      </section>

      {runtime.workers.length > 0 && <section className="fabric-section">
        <div className="fabric-section-title"><h3>Workers</h3><span>Most recently active 200</span></div>
        <div className="fabric-table-wrap">
          <table className="fabric-table">
            <thead><tr><th>Worker</th><th>Status</th><th>Pool</th><th>Provider</th><th>Active</th><th>Capacity</th><th>Lease until</th></tr></thead>
            <tbody>{runtime.workers.map((worker) => (
              <tr key={worker.id}>
                <th title={worker.id}>{worker.id}</th><td><span className="status-chip" data-status={worker.status}>{worker.status}</span></td><td>{worker.pool_name}</td><td>{worker.provider}</td><td>{worker.active_tasks}</td><td>{worker.capacity}</td><td>{worker.lease_until ? new Date(worker.lease_until).toLocaleTimeString() : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>}

      <section className="fabric-section fabric-task-section">
        <div className="fabric-section-title"><h3>Task explorer</h3><span>{taskSampleSummary(runtime, tasks.length)}</span></div>
        <p className="fabric-sample-note">Filters apply to the latest {runtime.task_sample_limit} tasks captured in this snapshot.</p>
        <div className="fabric-filters">
          <input aria-label="Search sampled tasks" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search task ID, kind, target…" />
          <select value={queue} onChange={(event) => setQueue(event.target.value)} aria-label="Queue filter">
            <option value="all">All queues</option>{runtime.queues.map((item) => <option key={item.queue_name} value={item.queue_name}>{item.queue_name}</option>)}
          </select>
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status filter">
            {statuses.map((item) => <option key={item} value={item}>{item === "all" ? "All statuses" : item}</option>)}
          </select>
        </div>
        <div className="fabric-task-layout">
          <div className="fabric-table-wrap">
            <table className="fabric-table fabric-task-table">
              <thead><tr><th>Task</th><th>Status</th><th>Queue</th><th>Target</th><th>Attempts</th><th>Updated</th></tr></thead>
              <tbody>{tasks.map((task) => (
                <tr key={task.id} data-selected={selectedId === task.id}>
                  <th title={task.id}><button type="button" onClick={() => setSelectedId(task.id)}>{taskLabel(task)}</button></th><td><span className="status-chip" data-status={task.status}>{task.status}</span></td><td>{task.queue_name}</td><td>{task.execution_target || "—"}</td><td>{task.attempts ?? 0}</td><td>{task.updated_at ? new Date(task.updated_at).toLocaleTimeString() : "—"}</td>
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
              <div><dt>Queue / pool</dt><dd>{selected.queue_name} / {selected.worker_pool}</dd></div>
              <div><dt>Target</dt><dd>{selected.execution_target || "—"}</dd></div>
              <div><dt>Worker</dt><dd>{selected.lease_owner || "unclaimed"}</dd></div>
              <div><dt>Lease until</dt><dd>{selected.lease_until || "—"}</dd></div>
              <div><dt>Attempts</dt><dd>{selected.attempts ?? 0}</dd></div>
            </dl>
          </aside>}
        </div>
      </section>
    </section>
  );
}
