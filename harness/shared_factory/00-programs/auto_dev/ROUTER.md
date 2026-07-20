# Auto-Dev Router

| User intent or signal | Workflow | Manual entrypoint |
| --- | --- | --- |
| Reported bug, QA failure, log/error, ticket comment, alert, “why is this happening?”, or RCA | Detective | `/auto-dev-detective` |
| Create/update Jira, Linear, Notion, Confluence, GitHub, Slack, PR text, RCA, report, or local artifact | Create Artifacts | `/auto-dev-create-artifacts` |
| Implement/fix/build one or many tracker items | Development Delivery | `/auto-dev` or `/develop` |
| Establish tracker/repository/policy context | Readiness and Context | `/auto-dev-readiness` |
| Implement in an isolated worktree | Isolated Implementation | `/auto-dev-implementation` |
| Review/repair own active delivery | Testing, Review, and PR Repair | `/auto-dev-review-repair` |
| Review another author's PR | PR review adapter | `/pull-request` |
| Release propagation | Release Propagation | `/auto-dev-release-propagation` |
| Merge, deploy watch, cleanup, or final closeout | Merge, Deployment, and Cleanup | `/auto-dev-closeout` |
| Idea/spec grooming before implementation | Spec Engine, then Create Artifacts | `/groom-spec` |

Route first to the target domain/project. Domain evidence and policy adapters
extend the shared workflow; they do not fork it.
