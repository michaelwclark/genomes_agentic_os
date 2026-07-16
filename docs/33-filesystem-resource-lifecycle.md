# 33 · Filesystem Resource Lifecycle

Automations, workflows, OSPrograms, and InstanceOSPrograms expose one governed
`resource-actions/v1` lifecycle for Command Center. The surface is intentionally
narrower than a file editor: it derives every location from resource identity,
updates a small metadata overlay, and never accepts a path, shell fragment,
provider query, or execution destination.

## Identity and ownership

| Kind | Canonical identity | Canonical folder |
| --- | --- | --- |
| `automation` | domain + lane + name | `<domain>/04-automations/<lane>/<name>/` |
| `workflow` | domain + lane + name | `<domain>/03-workflows/<lane>/<name>/` |
| `program` | name | `harness/shared_factory/00-programs/<name>/` |
| `instance-program` | domain + name | `<domain>/00-programs/<name>/` |

An InstanceOSProgram remains a domain-owned instance and may record a
`definition_id`; it is never resolved as the shared OSProgram merely because
the names match. The source package owns target resolution, validation, and
receipt formats. The installed root owns resource content and the
`.agentic-resource.yml` lifecycle overlay in each managed folder.

## Actions

`resource list`, `get`, `create`, `update`, `validate`, `disable`, `repair`, `archive`,
`restore`, and `rollback` support the four filesystem kinds. Mutations are
dry-run by default. A plan returns a SHA-256 drift hash; an apply requires that
hash through `--expected-drift-hash`, except create, which retains the existing
scaffold compatibility contract. Queue-only run-now may use the current
resource hash directly so a derived schedule never embeds a stale hash.

Only these overlay fields are editable: display name, summary, lifecycle
status, harness class, model, complexity, and notes. Automations also expose
enabled state and maturity level. Instance programs expose `definition_id` and
must reference an installed shared definition when that field changes. Unknown
overlay fields survive updates.

Archive is a reversible state change, never a delete. Every applied mutation
creates a fixed-location backup and receipt, validates the overlay, verifies
readback, and restores the exact prior overlay bytes if validation or readback
fails. Rollback accepts only the opaque backup ID and rejects identity or
canonical-target mismatches.

`resource repair` is intentionally bounded to the lifecycle overlay. It fixes
canonical identity and invalid lifecycle defaults while preserving unknown
mapping fields; it does not invent missing workflow, automation, or program
contract content, which remains visible through `resource validate`.

## Automation controls

`resource run-now automation` appends an idempotent local run request and never
dispatches it. Repeating the same caller-supplied idempotency key does not add a
second queue item.

`resource schedule-configure automation` accepts cadence, timezone, local time,
and enabled state. It derives both the schedule ID and command from canonical
automation identity; callers cannot provide a command. The bound schedule is
read with `resource schedule-get automation`. Existing top-level schedule
commands and their `resource-actions/v1` envelopes remain unchanged.

```bash
agentic-os resource get automation daily_digest \
  --domain personal --lane operations --root ~/agentic_os --json

agentic-os resource update automation daily_digest \
  --domain personal --lane operations --enabled --status active \
  --expected-drift-hash <hash-from-get-or-plan> --apply \
  --root ~/agentic_os --json

agentic-os resource schedule-configure automation daily_digest \
  --domain personal --lane operations --cadence daily --local-time 08:00 \
  --expected-drift-hash <hash-from-dry-run> --apply \
  --root ~/agentic_os --json
```

## Extension rule

Add a mutable field or resource kind only with a fixed identity map, an
allowlisted value contract, drift and conflict handling, exact-byte rollback,
readback validation, and destination-denial tests. Execution remains a separate
runtime concern; lifecycle actions may queue a request but do not dispatch it.
