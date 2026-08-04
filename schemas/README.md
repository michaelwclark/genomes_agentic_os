# Schemas

JSON Schema and YAML-schema documents for durable Agentic OS contracts. Runtime
code uses them to validate registries, Specs, workflows, automations, runs,
updates, customer profiles, and operator projections. A schema change should be
paired with fixture coverage and migration/compatibility guidance when it
changes an existing file contract.

Report resources use three independently versioned contracts:
`report-definition.schema.json`, `report-run.schema.json`, and
`report-artifact.schema.json`. Definitions are mutable through governed actions;
runs and artifacts are immutable evidence.

Workflow Studio uses `workflow-definition.schema.json` for the editable,
unknown-field-tolerant definition. Published versions and installed instance
pointers are immutable/readback records owned by `workflow-engine/v1`; they are
not aliases for the editable definition.

`auto-dev-work-item.schema.json` validates the plain-English `autodev.json`
projection stored in each Auto-Dev work item. It points to canonical work and
Development Delivery state; it is not another tracker or transition engine.
`auto-dev-health-evidence.schema.json` validates the stricter, item-scoped final
audit used before Auto-Dev can call a preserved packet healthy and finished.

`program-run-packet.schema.json` validates immutable `00-program.json` and
ordered workflow records in the canonical cross-program run packet. Its
execution outcome is intentionally separate from its quality outcome so a
test regression is routed to tracker-backed remediation without being
misreported as an execution crash.

Auto-Dev Health uses packet-local receipt contracts before
that final audit:

- `auto-dev-health-preflight.schema.json` freezes the exact work item, reviewed
  and merged revisions, hashed delivery receipts, resume manifest, receipt
  audit, and registered resource identities before any cleanup begins.
- `auto-dev-runtime-cleanup.schema.json` records target-local runtime teardown,
  absence, or non-management and binds the readback to the exact preflight
  bytes with `preflight_sha256`. The physical gate also requires the receipt
  to be newer than the preflight and at most 15 minutes old, then immediately
  executes the identity-bound registered readback again; exit 0 means the exact
  registered worktree runtime is absent.
- `auto-dev-resource-cleanup.schema.json` atomically records the final verified
  dispositions of both the worktree and its target-local runtime.
- `auto-dev-closed-worktree-readback.schema.json` captures the exact closed
  registry entry, or `result: not_managed`, inside the packet. Final Health
  audits this receipt as `resource_cleanup` and compares a managed entry with
  the live project `worktrees/closed.yml` row.
- `auto-dev-packet-manifest.schema.json` inventories every durable packet file
  plus the artifacts and logs directories before cleanup. Final Health permits
  only the expected finished-lane changes to `work.yml` and `autodev.json`.
- `auto-dev-stage-policy-decision.schema.json` binds each `not_required` stage
  to work-item/canonical identity, domain/project/stage, decision maker, reason,
  time, and the exact frozen effective-policy fingerprint/source/hash.
- `auto-dev-reopen.schema.json` binds a Health-completed packet and receipt hash
  to one new active packet, reason, stage, and run id without modifying the
  finished history.

Final Health evidence audits ten exact kinds: `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`.

The program templates and knowledge examples for these schemas are valid field
guides, not reusable proof. Every identity, revision, timestamp, reference, and
digest must be replaced with current readback from the work item being cleaned.

Schema validity is only the first gate. Physical cleanup also parses the hashed
canonical task, requires `delivery_complete` and exact worktree/revision
identity, compares the packet Merge and Closeout snapshots with the canonical
typed receipts at JSON level, validates their authority fields, and verifies
the complete ordered non-Health stage audit plus every stage snapshot hash.
