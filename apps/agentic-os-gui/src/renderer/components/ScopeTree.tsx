import type { DomainScope } from "../../shared/contracts";

export interface ScopeSelection {
  domain?: string;
  project?: string;
  view?: "active" | "all" | "archive";
}

interface Props {
  displayName: string;
  domains: DomainScope[];
  selected: ScopeSelection;
  counts: Map<string, number>;
  onSelect(scope: ScopeSelection): void;
}

function selected(scope: ScopeSelection, expected: ScopeSelection): boolean {
  return scope.domain === expected.domain && scope.project === expected.project && scope.view === expected.view;
}

export function ScopeTree({ displayName, domains, selected: active, counts, onSelect }: Props) {
  const visibleDomains = domains
    .map((domain) => ({
      ...domain,
      projects: domain.projects.filter((project) => (counts.get(`project:${domain.id}:${project.id}`) ?? 0) > 0),
    }))
    .filter((domain) => (counts.get(`domain:${domain.id}`) ?? 0) > 0);
  return (
    <nav className="scope-tree" aria-label="Domains and projects">
      <div className="brand-block">
        <span className="brand-mark">AOS</span>
        <div>
          <strong>{displayName}</strong>
          <span>Agentic OS</span>
        </div>
      </div>
      <button className="scope-all active-scope" data-active={active.view === "active"} onClick={() => onSelect({ view: "active" })}>
        <span>Active</span><b>{counts.get("active") ?? 0}</b>
      </button>
      <button className="scope-all" data-active={active.view === "all"} onClick={() => onSelect({ view: "all" })}>
        <span>All work</span><b>{counts.get("all") ?? 0}</b>
      </button>
      <div className="scope-groups">
        {visibleDomains.map((domain) => (
          <section className="scope-domain" key={domain.id}>
            <button
              className="domain-button"
              data-active={selected(active, { domain: domain.id })}
              onClick={() => onSelect({ domain: domain.id })}
            >
              <span>{domain.name}</span><b>{counts.get(`domain:${domain.id}`) ?? 0}</b>
            </button>
            <div className="project-list">
              {domain.projects.map((project) => (
                <button
                  key={project.id}
                  data-active={selected(active, { domain: domain.id, project: project.id })}
                  onClick={() => onSelect({ domain: domain.id, project: project.id })}
                >
                  <span>{project.name}</span><b>{counts.get(`project:${domain.id}:${project.id}`) ?? 0}</b>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
      <div className="scope-footer">
        <span className="live-dot" /> Local sources live
      </div>
      <button className="scope-all archive-scope" data-active={active.view === "archive"} onClick={() => onSelect({ view: "archive" })}>
        <span>Archive</span><b>{counts.get("archive") ?? 0}</b>
      </button>
    </nav>
  );
}
