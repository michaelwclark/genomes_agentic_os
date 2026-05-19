# Client OS Patterns

Each client OS should be a domain overlay on the core model, not a full fork.

## Client Domain Shape

```text
<client_domain>/
  AGENTS.md
  AGENT.md
  README.md
  domain.yml
  00-control-plane/
    active-work.md
    decisions.md
    routing-rules.md
    approval-rules.md
  01-inbox/
    raw-ideas.md
    triage.md
  02-projects/
  03-workflows/
  04-automations/
  05-knowledge/
    source-map.md
    glossary.md
    memory-policy.md
  06-runs-and-logs/
    activity-log.md
    runs/
    failures/
  07-metrics/
  08-archive/
```

The client domain can live beside `personal`, `clarks_consulting`, `los`, `lenders`, `shared_factory`, and `archive` in the installed root.

## Client Operations Pattern

Useful for service businesses or advisory clients:

- Notion cockpit for intake, approvals, and client-visible state.
- Meeting notes as first-class input.
- Automation runs tracked visibly.
- Human approval before outbound or customer-facing changes.

Recommended starting folders:

```text
<client_domain>/
  03-workflows/
    operations/
      inbound_message_triage/
    support/
      client_status_update/
  04-automations/
    operations/
      weekly_digest_prepare/
```

## Candidate Pipeline Pattern

Useful for recruiting, staffing, marketplace, or matching-heavy workflows:

- Notion cockpit for operators and approvals.
- Database-backed active state for matching, dedupe, sync, and embeddings.
- Workers or lightweight functions for glue tasks and syncs.
- Agent workflows for analysis, enrichment, routing, and reporting.

Recommended starting folders:

```text
<client_domain>/
  03-workflows/
    operations/
      candidate_intake/
      shortlist_review/
  04-automations/
    operations/
      source_sync_prepare/
```

## Internal Product Pattern

Useful for the operator's own software and operations:

- `los`, `lenders`, `clarks_consulting`, `personal`, and `shared_factory` remain separate domain roots.
- Engineering workflows handle feature work, PR review, release management, and production support.
- Daily operating dashboards can pull from GitHub, Jira, Slack, Notion, and local run logs.

Recommended starting folders:

```text
los/
  03-workflows/
    engineering/
      feature_dev/
      pull_request_review/
      release_management/
    support/
      production_issue_triage/
  04-automations/
    support/
      production_thread_intake/
```

## Customization Rule

Only customize:

- Domain context.
- Workflow choices.
- Automation permissions.
- Notion views.
- Integration adapters.

Do not customize:

- Core object vocabulary.
- Run log format.
- Approval state model.
- Context pack contract.
- Audit evidence requirements.
