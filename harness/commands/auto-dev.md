# `/auto-dev`

Route a request to `$auto-dev-everything` or one named Auto-Dev workflow. The
same work item and `autodev.json` are reused throughout.

Canonical order is Groom, Detective, Create Artifacts, Readiness, Develop,
Document, Review Self, Review Others, QA, Release Propagation, Finalize, Merge,
Release, Deploy, Closeout, Health. Each stage remains manually callable, but
project policy cannot reorder this lifecycle.

For an active packet created before `autodev.json`, use `agentic-os auto-dev
adopt ... --state <exact-packet> --run-id <stable-id> --apply`. Adoption keeps
the canonical packet/source identity and may attach only its exact registered
worktree after Git and branch readback.

For QA or development after Health, use `agentic-os auto-dev reopen --state
<finished-packet> --run-id <new-id> --reason "<why>" --stage qa --apply`.
This command keeps the finished packet byte-for-byte unchanged, writes a reopen
receipt into one new active packet, relinks canonical work state, and provisions
a fresh worktree and runtime registration. A plain `agentic-os work set` is not
a reopen operation and cannot make a `03-complete` packet writable.
