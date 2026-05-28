# Domain Template

Use this when creating a new top-level operating boundary such as `personal`, `clarks_consulting`, `los`, `shared_factory`, or a client domain.

## Required Files

- `ROUTER.md`
- `AGENTS.md`
- `CLAUDE.md`
- `CONTEXT.md`
- `RULES.md`
- `TOOLS.md`
- `README.md`
- `domain.yml`
- `REFERENCES.md`
- `00-control-plane/active-work.md`
- `00-control-plane/decisions.md`
- `00-control-plane/routing-rules.md`
- `00-control-plane/approval-rules.md`
- `01-inbox/raw-ideas.md`
- `01-inbox/triage.md`
- `02-projects/README.md`
- `03-workflows/<lane>/`
- `04-automations/<lane>/`
- `05-knowledge/source-map.md`
- `05-knowledge/glossary.md`
- `05-knowledge/memory-policy.md`
- `06-runs-and-logs/activity-log.md`
- `06-runs-and-logs/runs/`
- `06-runs-and-logs/failures/`
- `07-metrics/baselines.md`
- `07-metrics/scorecards.md`
- `08-archive/README.md`

## Setup Steps

1. Create the domain folder.
2. Fill `domain.yml`.
3. Fill `CONTEXT.md` using the room template: inputs, process, output folders, load/skip rules, tools, and done criteria.
4. Fill `ROUTER.md` and the control plane rules.
5. Add source maps and memory policy notes.
6. Create or link the Notion control plane.
7. Add first workflows before adding automations.
8. Set approval rules before allowing external writes.
