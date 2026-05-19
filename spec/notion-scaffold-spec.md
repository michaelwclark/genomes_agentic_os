# Notion Scaffold Spec

Notion provides the control plane for humans. The scaffold should create consistent pages and databases for each OS or client domain.

## Page Tree

```text
<Domain OS Home>
  Inbox
  Work Items
  Workflows
  Automations
  Runs
  Approvals
  Decisions
  Meeting Notes
  Artifacts
  Dashboards
```

## Databases

### Inbox

Properties:

- `Title`
- `Source`
- `Source URL`
- `Domain`
- `Lane`
- `Type`
- `Status`
- `Priority`
- `Received At`
- `Linked Work Item`
- `Raw Captured`

### Work Items

Properties:

- `Title`
- `Domain`
- `Lane`
- `Workflow`
- `Status`
- `Priority`
- `Owner`
- `Source`
- `Next Action`
- `Due`
- `Related Runs`
- `Related Approvals`
- `Related Artifacts`

### Runs

Properties:

- `Title`
- `Run Type`
- `Domain`
- `Workflow Or Automation`
- `Status`
- `Started At`
- `Completed At`
- `Agent`
- `Input`
- `Validation`
- `Artifacts`
- `Next Action`

### Approvals

Properties:

- `Title`
- `Domain`
- `Work Item`
- `Run`
- `Risk Level`
- `Requested Action`
- `Status`
- `Approver`
- `Decision At`
- `Decision Notes`

### Meeting Notes

Properties:

- `Title`
- `Domain`
- `Client`
- `Date`
- `Participants`
- `Raw Notes`
- `Extracted Actions`
- `Extracted Decisions`
- `Extracted Risks`
- `Linked Work Items`

## Scaffold Rules

- Every domain should have its own OS Home.
- Shared internal OS pages may aggregate across domains.
- Do not create pages in the wrong Notion workspace.
- Store Notion page/database IDs in the domain's `domain.yml` or `05-knowledge/source-map.md`.
- Generated Notion structure should be idempotent.
