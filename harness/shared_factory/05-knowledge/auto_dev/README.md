# Auto-Dev policy library

This folder is the shared, plain-English operating policy for Auto-Dev. It
explains what a careful agent must do at each software-delivery stage. The
Markdown is loaded by the workflow; it is not a second workflow engine and it
does not replace project configuration, source-repository instructions, or live
provider truth.

Development Delivery owns the canonical delivery state, worktree, stage
transitions, and typed evidence. The work item's `autodev.json` is the readable
resume projection across the Auto-Dev family.

This directory is also the single parent for all five development policy
planes. Auto-Dev stage files live directly here; environment access,
development standards, QA gates, and Gitflow topology live in the four named
nested folders. They are not active sibling folders elsewhere in
`05-knowledge/`.

## How policy is composed

Every run loads all applicable files in this order:

1. shared root policy from this folder;
2. domain policy;
3. project policy;
4. an explicit invocation overlay, when one was supplied.

A later layer may add concrete tools, repositories, branches, environments,
quality checks, vocabulary, or stricter gates. It may not remove inherited
safety, approval, evidence, tenant, security, sanitization, target-verification,
or provider-readback requirements. A run records the selected sources, hashes,
and effective fingerprint so it can be resumed against the same rules.

The other four nested policy planes are loaded when a stage needs them:

- `dev_standards` defines how code is designed, changed, tested, documented,
  secured, and observed;
- `qa_gates` defines risk-based acceptance and regression evidence;
- `gitflow_topology` defines repositories, base branches, sibling pull
  requests, and propagation rules;
- `environment_access` defines hosts, VPN, cloud, and runtime access without
  storing credentials.

`artifact-config` defines provider-native output and rendering rules, and
`investigation-config` defines evidence-led, read-only detective work. They are
adjacent contracts, not sixth and seventh development planes.

## Files and execution order

The numeric filename prefix is a stable policy identifier. It makes policy
source lists deterministic and keeps existing fingerprints explainable. It is
not the runtime order. Read the canonical order below when deciding which stage
runs next.

| Runtime position | Workflow | Shared policy file |
| --- | --- | --- |
| 1 | Grooming | `01-auto-dev-grooming.md` |
| 2 | Detective | `11-auto-dev-detective.md` |
| 3 | Create Artifacts | `02-auto-dev-create-artifacts.md` |
| 4 | Readiness | `15-auto-dev-readiness.md` |
| 5 | Develop | `03-auto-dev-develop.md` |
| 6 | Document | `12-auto-dev-document.md` |
| 7 | PR Create | `18-auto-dev-pr-create.md` |
| 8 | Review Self | `05-auto-dev-review-self.md` |
| 9 | Review Others | `04-auto-dev-review-others.md` |
| 10 | QA | `06-auto-dev-qa.md` |
| 11 | Finalize | `07-auto-dev-finalize.md` |
| 12 | Production Release Validation | `19-auto-dev-validate-production-release.md` |
| 13 | Merge | `08-auto-dev-merge.md` |
| 14 | Release | `10-auto-dev-release.md` |
| 15 | Deploy | `09-auto-dev-deploy.md` |
| 16 | Closeout | `17-auto-dev-closeout.md` |
| 17 | Health | `14-auto-dev-health.md` |

`16-auto-dev-release-propagation.md` is compatibility policy for the
lower-level Development Delivery recorder and legacy command alias used by PR
Create. It is intentionally outside this stage table and never adds a
seventeenth workflow or moves PR creation after QA.

Each workflow has a same-named command and skill and can be started directly.
`/auto-dev-everything` coordinates all seventeen over one work item. A later
external stage may not bypass missing predecessor evidence. When policy truly
makes a stage inapplicable, the stage remains visible with a typed,
frozen-policy-backed `not_required` decision.

## State, logs, and receipts

Before acting, find the existing work item by its canonical id or tracker key.
Reuse its packet, `autodev.json`, Development Delivery task, registered
worktree, receipts, and provider references. Do not create a second packet to
work around an error.

Keep durable evidence in the work item:

- append a short work-log entry for material actions and decisions;
- store typed receipts for commands, tests, reviews, provider mutations, and
  readbacks;
- keep raw or lengthy output in `logs/` or `artifacts/`, not in chat;
- update the plain-English next action and blocker whenever execution pauses;
- never put secrets or unnecessary customer data in the packet.

## How agents should work

The coordinating agent owns routing, policy, approvals, state transitions, and
the final evidence judgment. It may delegate bounded, independent discovery,
implementation, test, or review tasks to subagents. Every delegated task must
name its scope, inputs, expected output, and file ownership. The coordinator
checks the returned evidence and remains responsible for conflicts and done
criteria.

Use quiet, artifact-backed execution for long tests, builds, CI watches,
provider checks, or deployments. A watcher should report a real blocker or
terminal result, not fill chat with unchanged status. Qualifying long-running
commands must use the Agentic OS long-run contract.

## Recovery rule

On failure, preserve the current packet and classify the problem before doing
anything else: code, test, configuration, access, provider, infrastructure,
policy, or product decision. Read the latest receipt and live state, make the
smallest safe correction, and rerun only the affected check. Do not rerun
blindly, loosen a gate, change the base branch, recreate the worktree, or mark a
stage complete merely to advance the state machine.

Finished packets are immutable history. Follow-up QA or support work uses the
canonical reopen command to create a new active run while retaining the old
receipts.
