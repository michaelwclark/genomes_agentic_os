# Work Item Archive Health

Runs nightly at 01:30 in the configured OS timezone. It invokes
`agentic-os work-item-archive --root <root> --apply`, uses each project's
configured retention period, and emits local receipts only.

Success means every eligible terminal packet is readable under
`work-items/99-archived/`, the old path is absent, and canonical work-state
paths have been migrated. A `REOPEN.md` file blocks archival.
