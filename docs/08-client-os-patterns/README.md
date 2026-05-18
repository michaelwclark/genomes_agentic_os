# Client OS Patterns

Each client OS should be a domain overlay on the core model, not a full fork.

## Client Domain Shape

```text
domains/<client>/
  README.md
  domain.yml
  context/
    business.md
    systems.md
    stakeholders.md
    access-policy.md
  workflows/
  automations/
  meetings/
  decisions/
  notion/
```

## Client Operations Pattern

Useful for service businesses or advisory clients:

- Notion cockpit for intake, approvals, and client-visible state.
- Meeting notes as first-class input.
- Automation runs tracked visibly.
- Human approval before outbound or customer-facing changes.

## Candidate Pipeline Pattern

Useful for recruiting, staffing, marketplace, or matching-heavy workflows:

- Notion cockpit for operators and approvals.
- Database-backed active state for matching, dedupe, sync, and embeddings.
- Workers or lightweight functions for glue tasks and syncs.
- Agent workflows for analysis, enrichment, routing, and reporting.

## Internal Product Pattern

Useful for the operator's own software and operations:

- Personal, internal product, client delivery, and shared services as separate domains.
- Engineering workflows for feature work, PR review, release management, and production support.
- Daily operating dashboard pulling from GitHub, Jira, Slack, Notion, and local run logs.

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
