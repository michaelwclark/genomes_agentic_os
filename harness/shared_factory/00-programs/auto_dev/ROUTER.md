# Auto-Dev Router

| User intent or signal | Workflow | Manual entrypoint |
| --- | --- | --- |
| Reported bug, QA failure, log/error, ticket comment, alert, “why is this happening?”, or RCA | Detective | `/auto-dev-detective` |
| Create/update Jira, Linear, Notion, Confluence, GitHub, Slack, PR text, RCA, report, or local artifact | Create Artifacts | `/auto-dev-create-artifacts` |
| Implement/fix/build one or many tracker items | Development Delivery | `/auto-dev` or `/develop` |
| Review/repair own active delivery | Testing, Review, and PR Repair | `/auto-dev` resume |
| Review another author's PR | PR review adapter | `/pull-request` |
| Release propagation, deploy watch, or cleanup | matching Development Delivery workflow | `/auto-dev` resume |
| Idea/spec grooming before implementation | Spec Engine, then Create Artifacts | `/groom-spec` |

Route first to the target domain/project. Domain evidence and policy adapters
extend the shared workflow; they do not fork it.
