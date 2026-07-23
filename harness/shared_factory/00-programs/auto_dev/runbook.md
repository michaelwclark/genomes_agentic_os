# Auto-Dev Operator Runbook

## Start or route

1. Classify the request with `ROUTER.md`; route to domain/project.
2. Read the selected workflow and project configuration.
3. Run its resolver/status command before mutation.
4. Start or resume one run id; verify its policy fingerprint and source list.

For a bare Auto-Dev request, `agentic-os auto-dev default <domain> <project>
<ticket> --apply` uses the project's Default boundary and always includes PR
Create. `agentic-os auto-dev everything ...` uses the project's configured
Everything boundary; it is not inherently a release or deploy request. Both
provision the canonical work item, worktree, delivery task, and `autodev.json`.
A single verb uses `agentic-os auto-dev <verb> ...`; branch
PR creation is `auto-dev pr-create`; `auto-dev propagate` and
`auto-dev release-propagation` are compatibility aliases
and release publication remains `auto-dev release`. Run the
named stage skill to do the work, write one
`development-stage-evidence/v1` JSON receipt per target state, then use
`develop stage` to record the stage. Direct `develop transition` is disabled.
Independent workflows use `auto-dev-stage-evidence/v1` and `auto-dev record`.

For one active pre-vNext packet that has no `autodev.json`, run
`agentic-os auto-dev adopt <domain> <project> <ticket> --state <packet>
--run-id <stable-id> --apply`. Adoption requires exactly one canonical row for
that packet and source key. It reuses only an exact active project-registered
Git worktree with matching branch metadata. If that identity cannot be proven,
adoption stops before writing the run, packet, task, or canonical work state;
repair the registration and rerun the same command. It never creates a
replacement packet or worktree.

The shared safe order is Groom, Detective, Create Artifacts, Readiness,
Develop, Document, PR Create, Review Self, Review Others, QA, Finalize, Merge,
Release, Deploy, Closeout, Health. A project may declare a full alternative
order only when it preserves required lifecycle precedence. Everything runs
the frozen slice from its configured start through completion; stages outside
that slice are `out_of_scope`. A single-stage run uses the same predecessor
gates.

When a stage permits `not_required`, use
`auto-dev-stage-policy-decision/v1`. It binds work-item/canonical identity,
domain/project/stage, decision maker, reason, timestamp, the frozen delivery
policy fingerprint, and the exact policy receipt plus SHA-256. Recording copies
the policy source and decision into immutable packet-local proof. Frozen stage
applicability controls the decision: required stages must complete, while
contextual or disabled Detective, Create Artifacts, Document, Review Others,
QA, Finalize, and Release stages may use the typed decision. Delivery-managed
stages use their existing typed path. No in-scope stage is silently omitted.

Several positional tickets produce several independent task/packet/worktree/
`autodev.json` records under one run. Resume only the selected ticket with its
own `--state`.

## During execution

- Keep chat quiet while tests/checks/watchers are pending; store raw evidence in
  the run packet.
- Pause unavailable VPN/provider/environment sources instead of emitting
  repeated failures. Resume the same run when the prerequisite returns.
- Detective accepts only declared source IDs, a typed deployed-version
  authority receipt, evidence matching policy authority/prerequisites, explicit
  dispositions for sources not used, and evidence-ID-backed conclusions.
- External artifact apply requires `artifact-approval/v1` and
  `artifact-target-verification/v1`; close it only with a normalized
  `artifact-provider-readback/v1` receipt whose content matches the draft.
- A workflow hands off only a compact receipt, not duplicated raw state.

## Closeout, then Health

Closeout verifies acceptance evidence, external readback, unresolved gaps,
tracker/PR/release/deploy state, provider reconciliation, and the final summary.
It records `delivery_complete`; it does not erase the work packet or perform
host-wide cleanup.

After `delivery_complete`, run `/auto-dev-health` or `agentic-os auto-dev health
...`. Health always uses the `clean_only` path. A dirty checkout is preserved
and blocks physical cleanup even when useful evidence has been copied into the
packet. Reconcile or preserve dirty changes through a separate operator
workflow, verify a clean `git status --porcelain`, then rerun Health with a new
preflight. Health follows this order:

1. Read back merge/delivery/provider truth and audit the required receipts.
2. Write a compact resume manifest and full packet manifest. Hash every durable
   pre-cleanup packet file outside Health output; freeze the packet-local Health
   preflight.
3. Tear down or read back the exact target-local runtime and write
   `auto-dev-runtime-cleanup/v1` bound to the preflight SHA-256.
4. Dry-run cleanup with exact domain, project, worktree, preflight, and runtime
   receipt; stop on missing proof, a reopen/hold marker, an unknown worktree
   root, or an unscoped runtime.
5. Require the exact worktree id/path/branch/HEAD and an identity-bound runtime
   containing domain/project/worktree. Accept only a runtime receipt newer than
   the preflight and at most 15 minutes old; immediately execute the registered
   readback again, where exit 0 means that exact runtime is absent. Remove only
   that registered reconstructable worktree, then preserve both
   final resource readbacks in one `auto-dev-resource-cleanup/v1` receipt.
   Snapshot its exact live `worktrees/closed.yml` row in a packet-local
   `auto-dev-closed-worktree-readback/v1` receipt, or record `not_managed` when
   no worktree was registered. Do not force removal, sweep Git metadata or
   container resources, use a host-wide/all selector, guess an identity, or touch
   a shared runtime.
   For LOS fast-worktree runtimes, use the configured source-owned Health
   wrapper. It must prove the exact compose project's containers, project-owned
   networks and volumes, Postgres database, Redis prefix, Valkey prefix,
   registry row, and `.env.worktree` are absent. The shared external LOS network
   is not selected. A Docker enumeration error or stopped shared Postgres/cache
   service is a failed proof, not an absent resource; do not substitute
   `status.sh | grep`.
6. Move the preserved work-item packet to the canonical finished lane, refresh
   its state links, and read it back before recording the Health receipt. All
   pre-cleanup hashes must match after the move except the semantic
   `work.yml`/`autodev.json` relocation updates; parse those two again. Use
   `project work-item set ... --state finished --health-relocation` so the move
   does not rewrite packet-local `WORKLOG.md` or `NEXT.md` after they were hashed.

Health is also independently callable for a completed item. It is manual and
exact-item scoped; this program does not enable a cleanup schedule, automation,
host-wide/all-resource cleanup path.

The finished packet is immutable. For a QA or development follow-up, run:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<why work resumed>" --stage qa \
  --root <root> --apply
```

That command verifies completed Health and the closed canonical row, writes a
receipt in one new active packet, relinks canonical state, and provisions a new
worktree and runtime registration. It is idempotent by run id. Never use
`agentic-os work set` to make the finished packet active, and never reuse its
retired runtime/worktree.

## Object Library self-hosting

Use `$object-library` and the `library_self_hosting` workflow for reusable
definition changes. Author in `michaelwclark/genomes_agentic_lib`, not in
installed `<root>/lib/`. Develop builds the candidate archive; QA validates
that exact archive; Release publishes it; Deploy installs the immutable tag or
commit and reads it back; Document is rerun after release/deploy to record the
actual version and receipts.

Deploy is dry-run-first:

```bash
agentic-os library install --root <root> --ref <tag-or-commit>
agentic-os library install --root <root> --ref <tag-or-commit> --apply
agentic-os library verify-install --root <root>
agentic-os library doctor --root <root>
agentic-os library rollback-install --root <root>
agentic-os library rollback-install --root <root> --apply
```

Linked library worktrees or uncaptured installed edits block replacement.
Preserve/re-home them and repeat the same Deploy run; do not use an installed
edit, moving branch, or local archive as a substitute for the verified release.

## Health checks

```bash
agentic-os detective doctor --root <root>
agentic-os artifacts doctor --root <root>
agentic-os develop policy <domain> <project> --plane dev_standards --root <root> --json
agentic-os develop policy <domain> <project> --plane qa_gates --root <root> --json
agentic-os develop policy <domain> <project> --plane gitflow_topology --root <root> --json
agentic-os develop policy <domain> <project> --plane auto_dev --root <root> --json
agentic-os develop policy <domain> <project> --plane environment_access --root <root> --json
agentic-os auto-dev status <work-item>
agentic-os validate --strict --root <root>
agentic-os library doctor --root <root>
```
