# `agentic-os develop`

Canonical entry point for one or many Agentic OS programming tasks.

```bash
# Plan only (default)
agentic-os develop start <domain> <project> <ticket> [<ticket> ...]

# Multi-repository project (repository.catalog + selection_required)
agentic-os develop start <domain> <project> <ticket> --repository <repository-id>

# Ticket/release-derived base and invocation policy addenda
agentic-os develop start <domain> <project> <ticket> \
  --base-branch <branch> --policy-overlay dev_standards=<file.md>

# Provision portfolio, one active work item, and one isolated worktree per task
agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply

# Compact portfolio/task readback
agentic-os develop status <run-dir>
```

Project behavior comes from `config/development.yml`, the canonical code
settings file for projects in every domain. Repository, base branch, worktree
directory, branch template, and date-prefix inheritance are configured there.
Multi-repository projects declare a catalog and require explicit `--repository`;
the engine never guesses from the ticket. The program contract and
five complete workflow specifications live in
`harness/shared_factory/00-programs/development_delivery/` and
`harness/shared_factory/04-workflows/development_delivery/`.

Every run snapshots its dynamic Markdown policy planes:

```bash
agentic-os develop policy <domain> <project> --plane dev_standards --json
agentic-os develop policy <domain> <project> --plane qa_gates --json
agentic-os develop policy <domain> <project> --plane gitflow_topology --json
agentic-os develop policy <domain> <project> --plane auto_dev --json
agentic-os develop policy <domain> <project> --plane environment_access --json
```

The conventional folder order is root → domain → project. Projects may provide
an ordered 1-N path list in `config/development.yml`; adding a Markdown file is
picked up automatically on the next run.

Direct state transitions fail closed. Named workflow stages are the only normal
advancement route; failures, recovery, and leases remain receipt-backed:

```bash
agentic-os develop fail <state.json> --kind <classification> --detail <text> --receipt <ref> --idempotency-key <key>
agentic-os develop recover <state.json> --receipt <ref> --idempotency-key <key>
agentic-os develop heartbeat <state.json> --owner <worker> --idempotency-key <key>
```

Each delivery workflow also has a manual chat skill and a stage recorder:

```bash
agentic-os develop stage <state.json> --stage <readiness|implementation|review|release_propagation|merge|deploy|closeout> \
  --receipt <state>=<development-stage-evidence.json> ... \
  --idempotency-prefix <stable-key>
```

`stage` records work already performed by the named skill; it is not a provider
executor. It preflights every receipt before mutation. Each JSON file must use
`development-stage-evidence/v1`, match the target state, contain terminal
status, summary, structured evidence, and `verified_at`; PR, merge, deploy,
readiness, and completion states require their specific readback fields.
In particular, a completed `merged` receipt requires `merge_sha`, provider-read
`source_head_sha` equal to the reviewed `subject_revision`, `provider`,
`pull_request`, and `readback_verified: true`. See the Auto-Dev Merge template;
Health later reuses that provider, PR reference, and merge revision exactly.

Manual named stage skills are `/auto-dev-readiness`, `/auto-dev-develop`,
`/auto-dev-review-self`, `/auto-dev-release-propagation`, `/auto-dev-merge`,
`/auto-dev-deploy`, and `/auto-dev-closeout`. Develop delegates to
`/auto-dev-implementation`, and Review Self delegates to
`/auto-dev-review-repair`; both preserve the same canonical delivery state.
They also route implicitly from equivalent chat requests.

The friendlier operator facade is `agentic-os auto-dev`. It creates or resumes
the same delivery task and `<work-item>/autodev.json`; it never owns another
delivery transition engine.
