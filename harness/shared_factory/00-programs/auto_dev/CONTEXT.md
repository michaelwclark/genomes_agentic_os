# Auto-Dev Context

## Purpose

Provide one discoverable SDLC front door from a signal or idea through evidence,
excellent artifacts, implementation, review/repair, release/deploy, and durable
closeout.

## Source hierarchy

1. Live tracker/provider state for lifecycle and target identity.
2. Deployed-version/environment authority before environment-scoped code analysis.
3. Exact code plus configured domain/project evidence sources.
4. Root → domain → project Markdown policy planes.
5. Local run receipts for resumability and proof.
6. Notion as a rich operator-facing projection, not runtime state.

## Shared foundations

| Foundation | Conventional policy roots | Consumers |
| --- | --- | --- |
| Development standards | `05-knowledge/dev_standards` + domain/project addenda | implementation and review |
| QA gates | `05-knowledge/qa_gates` + domain/project addenda | validation and QA handoff |
| Gitflow topology | `05-knowledge/gitflow_topology` + domain/project addenda | branch/PR/release planning |
| Artifact contracts | `artifact-config/<provider>/<type>.md` at root/domain/project | every artifact-producing workflow |
| Investigation config | `investigation-config/` at root/domain/project | Detective and ticket grooming |

Every resolver is dynamic: add a Markdown file and the next run consumes it.
