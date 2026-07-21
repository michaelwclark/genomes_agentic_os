# `/auto-dev-everything`

Take one or many tickets through every applicable Auto-Dev workflow using the
same `autodev.json`. Use `$auto-dev-everything`; approvals and provider gates
still apply.

The exact order is Groom, Detective, Create Artifacts, Readiness, Develop,
Document, Review Self, Review Others, QA, Release Propagation, Finalize, Merge,
Release, Deploy, Closeout, Health. A multi-ticket run creates one task, packet,
worktree, and `autodev.json` per ticket; “same” means the same ticket-local file
across its stages. Resume a paused ticket with its own `--state`.
