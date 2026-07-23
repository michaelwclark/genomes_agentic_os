# Auto-Dev Router

| User intent or signal | Workflow | Manual entrypoint |
| --- | --- | --- |
| Bare "auto-dev" for one or more tickets | Default | `/auto-dev`; `agentic-os auto-dev default ...` |
| Take a ticket all the way / Auto-Dev Everything | Everything | `/auto-dev-everything` |
| Idea/spec grooming before implementation | Groom | `/auto-dev-grooming` |
| Reported bug, QA failure, log/error, ticket comment, alert, “why is this happening?”, or RCA | Detective | `/auto-dev-detective` |
| Create/update Jira, Linear, Notion, Confluence, GitHub, Slack, PR text, RCA, report, or local artifact | Create Artifacts | `/auto-dev-create-artifacts` |
| Implement/fix/build one or many tracker items | Develop | `/auto-dev-develop` or `/auto-dev-implementation` |
| Establish tracker/repository/policy context | Readiness and Context | `/auto-dev-readiness` |
| Review/repair own active delivery | Review Self | `/auto-dev-review-self` |
| Review another author's PR | Review Others | `/auto-dev-review-others` |
| Run QA separately | QA | `/auto-dev-qa` |
| Document code/issues/architecture/operations | Document | `/auto-dev-document` |
| Resolve and create/reuse the complete PR family | PR Create | `/auto-dev-pr-create` |
| Converge our ticket PR family | Finalize | `/auto-dev-finalize` |
| Make the governed merge decision | Merge | `/auto-dev-merge` |
| Legacy branch-family propagation invocation | PR Create compatibility mode | `/auto-dev-release-propagation` |
| Create a version/tag/package/provider release | Release | `/auto-dev-release` |
| Deploy and validate the exact artifact | Deploy | `/auto-dev-deploy` |
| Reconcile provider/delivery state and prove delivery complete | Closeout | `/auto-dev-closeout` |
| Audit and clean a completed item, then preserve it in the finished lane | Health | `/auto-dev-health` |
| Change, publish, install, or reconcile reusable Object Library definitions | Object Library Self-Hosting profile | `$object-library` and `agentic-os library` |

Route first to the target domain/project. Domain evidence and policy adapters
extend the shared workflow; they do not fork it.
