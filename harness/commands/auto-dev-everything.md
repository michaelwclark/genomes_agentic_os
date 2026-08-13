# `/auto-dev-everything`

Take one or many tickets through every applicable Auto-Dev workflow using the
same `autodev.json`. Use `$auto-dev-everything`; approvals and provider gates
still apply.

The exact order is Groom, Detective, Create Artifacts, Readiness, Develop,
Document, PR Create, Review Self, Review Others, QA, Finalize, Production Release
Validation, Merge, Release, Deploy, Closeout, Health. Release Propagation is only the lower-level
compatibility recorder/alias for PR Create; it does not add a stage. A
multi-ticket run creates one task, packet, worktree, and `autodev.json` per
ticket; “same” means the same ticket-local file across its stages. Resume a
paused ticket with its own `--state`.
