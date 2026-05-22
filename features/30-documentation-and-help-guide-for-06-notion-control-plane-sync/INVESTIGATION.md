# Investigation

Feature 06 is implemented in `src/genomes_agentic_os/notion_sync.py` and wired
through the `agentic-os notion` command group in `src/genomes_agentic_os/cli.py`.

The sync planner discovers domain runtime files, active work, approvals,
decisions, metrics, projects, workflows, automations, and run logs. Apply writes
`.notion-sync/mapping.yml` only after workspace verification.

Workspace rules are explicit: Genome roots require `Genome's Notion`; customer
roots require the workspace configured in `customer.yml`; personal Notion
markers are blocked.
