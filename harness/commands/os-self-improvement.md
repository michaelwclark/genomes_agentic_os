# OS Self-Improvement

Run a local, proposal-only review of installed Agentic OS evidence.

## Dry Run

```bash
agentic-os self-improvement run --root ~/agentic_os --dry-run
```

Dry-run reads bounded evidence from allowlisted roots, redacts secret-shaped
values, derives deterministic findings, and prints a report. It writes no run
records, proposals, approvals, drafts, Notion pages, skills, commands,
workflows, automations, shell config, or harness globals.

## Proposal Lifecycle

```bash
agentic-os self-improvement run --root ~/agentic_os --apply
agentic-os self-improvement status --root ~/agentic_os
agentic-os self-improvement list --root ~/agentic_os
agentic-os self-improvement show <proposal_id> --root ~/agentic_os
agentic-os self-improvement approve <proposal_id> --target feature-spec --root ~/agentic_os
agentic-os self-improvement reject <proposal_id> --root ~/agentic_os
agentic-os self-improvement promote <proposal_id> --target feature-spec --root ~/agentic_os
```

Apply writes run records and proposal files only under
`harness/shared_factory/06-runs-and-logs/self-improvement/`. Promotion creates
draft artifacts only; it does not install generated skills, commands, workflows,
automations, validators, or Notion pages.
