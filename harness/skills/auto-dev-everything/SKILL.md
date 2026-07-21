---
name: auto-dev-everything
description: Take one or many tracker items through every applicable Auto-Dev workflow, resuming the same autodev.json and stopping only at real approval, access, provider, product, security, or infrastructure gates.
---

# Auto-Dev Everything

Use this for “take this ticket all the way” work. It is an orchestrator over
existing owners, not a second implementation or PR engine.

1. Route to the exact domain/project and read the live tracker item.
2. Start or resume with `agentic-os auto-dev everything <domain> <project>
   <ticket> --apply`. Read the resulting work item `autodev.json`.
3. Resolve `auto_dev`, `environment_access`, `dev_standards`, `qa_gates`, and
   `gitflow_topology` policy plus artifact/investigation contracts.
4. Run the first eligible incomplete workflow in this exact order: Groom,
   Detective, Create Artifacts, Readiness, Develop, Document, Review Self,
   Review Others, QA, Release Propagation, Finalize, Merge, Release, Deploy,
   Closeout, Health. Use the named skill in `autodev.json`; do the work before
   recording evidence. Do not reorder stages for convenience.
5. Record standalone outcomes with `auto-dev-stage-evidence/v1`, delivery-owned
   milestones through `agentic-os develop stage`, and the final cleanup through
   strict `auto-dev-health-evidence/v1`. `not_required` uses the typed
   `auto-dev-stage-policy-decision/v1` identity, reason, decision-maker,
   fingerprint, exact frozen policy source, SHA-256, and timestamp; recording
   materializes the decision and policy into packet-local immutable proof.
6. Continue through Closeout until `delivery_complete`; then run
   `$auto-dev-health`. Health audits receipts first, writes the resume manifest,
   removes only reconstructable item-local resources, and preserves the packet
   in the finished lane.
7. Re-sync and stop only when Health is completed, or when a blocker names one
   exact owner action. Health always audits, even when cleanup is a no-op; it
   cannot be `not_required`. Do not
   silently stop after local validation, PR creation, merge, or Closeout.

When several tickets are supplied, the shared run creates one delivery task,
packet, worktree, and `autodev.json` per ticket. Parallelize only independent
work, resume a paused ticket through its own `--state`, and never merge several
tickets into one packet or restart completed siblings.

Keep tests and PR watches quiet and receipt-backed. Health requires the full
packet manifest and ten exact receipt kinds, identity-bound runtime cleanup, a
fresh immediate exit-0-means-absent readback, and exact worktree id/path/branch/
HEAD. It has no force, metadata-sweep, host-wide/all-resource, shared-runtime, or
guessed-identity path. An explicit reopen/hold marker blocks cleanup. Finished
packets remain immutable; a follow-up uses a receipt-backed canonical reopen
and a new delivery run. No schedule or automation is enabled by this skill.
