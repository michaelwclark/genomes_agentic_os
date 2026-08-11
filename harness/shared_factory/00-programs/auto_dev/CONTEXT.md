# Auto-Dev Context

## Purpose

Provide one discoverable SDLC front door whose project profile can stop at a
mergeable or merged pull request or continue through release/deploy, closeout,
and receipt-backed lifecycle hygiene, while leaving a resumable work packet.

## Source hierarchy

1. Live tracker/provider state for lifecycle and target identity.
2. Deployed-version/environment authority before environment-scoped code analysis.
3. Exact code plus configured domain/project evidence sources.
4. Root → domain → project → invocation composition across all five nested
   Auto-Dev Markdown policy planes.
5. Local run receipts for resumability and proof.
6. Notion as a rich operator-facing projection, not runtime state.

## Shared foundations

| Foundation | Conventional policy roots | Consumers |
| --- | --- | --- |
| Auto-Dev behavior | `05-knowledge/auto_dev` + domain/project addenda | every Auto-Dev stage |
| Environment access | `05-knowledge/auto_dev/environment_access` + domain/project addenda | hosts, VPN, cloud, and runtime access |
| Development standards | `05-knowledge/auto_dev/dev_standards` + domain/project addenda | implementation and review |
| QA gates | `05-knowledge/auto_dev/qa_gates` + domain/project addenda | validation and QA handoff |
| Gitflow topology | `05-knowledge/auto_dev/gitflow_topology` + domain/project addenda | branch/PR/release planning |
| Artifact contracts | `artifact-config/<provider>/<type>.md` at root/domain/project | every artifact-producing workflow |
| Investigation config | `investigation-config/` at root/domain/project | Detective and ticket grooming |
| Rules Engine validation kits | `lib/programs/domains/los/los_rules_engine/` selected by investigation context | LOS caller/rulebook Readiness, implementation, review, and QA |

Every resolver is dynamic: add a Markdown file and the next run consumes it.

A Rules Engine selector result is a frozen, evidence-only delivery input. It
always records matching paths/subjects and source hashes. It records a
canonical contract, five concrete artifact hashes, snapshot freshness/coverage,
and known findings only when local catalog and snapshot evidence actually
exist. Otherwise it carries `kit-unavailable` or `insufficient-evidence` into
review and QA; it never grants live rule or tenant configuration mutation
authority.

Closeout and Health are separate responsibilities. Closeout reconciles live
provider/delivery truth and proves `delivery_complete`. Health audits that proof
before removing reconstructable local resources, writes the resume manifest,
and preserves the work-item packet in the finished lane. It must not infer
permission for a host-wide/all-resource container operation or an automated schedule.
