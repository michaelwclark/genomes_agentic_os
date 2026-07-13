import type { DomainScope } from "../../shared/contracts";

export interface ScopeSelection {
  domain?: string;
  project?: string;
}

interface Props {
  domains: DomainScope[];
  selected: ScopeSelection;
  counts: Map<string, number>;
  onSelect(scope: ScopeSelection): void;
}

function selected(scope: ScopeSelection, expected: ScopeSelection): boolean {
  return scope.domain === expected.domain && scope.project === expected.project;
}

export function ScopeTree({ domains, selected: active, counts, onSelect }: Props) {
  return (
    <nav className="scope-tree" aria-label="Domains and projects">
      <div className="brand-block">
        <span className="brand-mark">AOS</span>
        <div>
          <strong>AgenticOS</strong>
          <span>Conversation driver</span>
        </div>
      </div>
      <button className="scope-all" data-active={selected(active, {})} onClick={() => onSelect({})}>
        <span>All work</span><b>{counts.get("all") ?? 0}</b>
      </button>
      <div className="scope-groups">
        {domains.map((domain) => (
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
    </nav>
  );
}
