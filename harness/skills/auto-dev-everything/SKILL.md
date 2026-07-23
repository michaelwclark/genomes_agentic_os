---
name: auto-dev-everything
description: Take one or many tracker items through the owning project's configured Auto-Dev Everything boundary, resuming the same autodev.json and stopping only at that boundary or a real gate.
---

# Auto-Dev Everything

Use this for “take this ticket all the way” work. It is an orchestrator over
existing owners, not a second implementation or PR engine.

1. Route to the exact domain/project and read the live tracker item.
2. Start or resume with `agentic-os auto-dev everything <domain> <project>
   <ticket> --apply`. Read the resulting work item `autodev.json`.
3. Resolve `auto_dev`, `environment_access`, `dev_standards`, `qa_gates`, and
   `gitflow_topology` policy plus artifact/investigation contracts.
4. Read the frozen `everything.start_stage`, `everything.completion_stage`,
   `stage_order`, and stage applicability from the project profile. Run the
   first eligible incomplete workflow in that active window. The configured
   order may vary only when it preserves required lifecycle precedence. Use the
   named skill in `autodev.json`; do the work before recording evidence.
5. Record standalone outcomes with `auto-dev-stage-evidence/v1`, delivery-owned
   milestones through `agentic-os develop stage`, and the final cleanup through
   strict `auto-dev-health-evidence/v1`. `not_required` uses the typed
   `auto-dev-stage-policy-decision/v1` identity, reason, decision-maker,
   fingerprint, exact frozen policy source, SHA-256, and timestamp; recording
   materializes the decision and policy into packet-local immutable proof.
6. Continue until the configured completion stage is receipt-backed. Run
   Closeout and Health only when they are inside the active window. Health
   audits receipts first, writes the resume manifest, removes only
   reconstructable item-local resources, and preserves the packet.
7. Re-sync and stop only at the configured completion stage or when a blocker
   names one exact owner action. Stages outside the window are `out_of_scope`.
   Required stages cannot be skipped; contextual or disabled stages require a
   typed `not_required` policy decision when they are inside the active window.
   Health cannot be `not_required`.

Local validation has three dispositions: `passed`, `deferred_to_ci`, or failed.
Use `deferred_to_ci` only for a typed environment/infrastructure failure when
the pinned project profile enables `ci_fallback_on_environment_failure`; it is
eligible to continue to Document and PR Create so CI can provide the missing
signal. A code or test failure remains blocking. Never label an unavailable
focused test as `passed`.

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
