# 32 · Governed Registry Authoring

Rules, reports, skills, and commands can be authored through one deterministic
CLI contract suitable for Command Center. This is deliberately narrower than a
general file editor: the CLI owns target selection, registry projection,
validation, backup, and readback.

## Resource and action contract

Supported kinds are `rule`, `report`, `skill`, and `command`. Supported scopes
are `system`, `domain`, and `project`.

| Action | Required inputs | Behavior |
| --- | --- | --- |
| `resource list` | kind and scope | Returns stable ID order and `mutable` on each row. |
| `resource get` | kind, ID, and scope | Returns registry metadata and prompt document content. |
| `resource validate` | kind, ID, and scope | Checks registry, canonical source, checksum, and capability projection. |
| `resource create` | identity, display name, description, prompt | Creates a draft managed resource. Dry-run by default. |
| `resource update` | identity and at least one editable field | Updates display name, description, or prompt. Dry-run by default. |
| `resource archive` | identity | Soft-deletes a managed resource. Dry-run by default. |
| `resource restore` | identity | Restores its pre-archive status. Dry-run by default. |
| `resource rollback` | identity and backup ID | Restores an exact prior managed state. Dry-run by default. |

Every JSON result uses `api_version: resource-actions/v1`. Applied mutations
include a backup ID, receipt path, and `readback.ok`. Existing built-in or
unmanaged registry rows remain visible but return `mutable: false`.

## Canonical routing

The server derives all locations from kind and scope:

- System resources use `harness/registries/` and the matching fixed visible
  source directory.
- Domain resources use the selected domain's `00-control-plane/` registry and
  prompt-document directories.
- Project resources use the selected project's `config/` registry and
  prompt-document directories.
- Every managed resource is projected into the system capability registry.

The API accepts no source path, executable path, shell command, URL, or query.
IDs are canonical `snake_case` on create. Safe hyphenated built-in IDs remain
readable for backward compatibility but cannot be changed through this surface.

## Mutation safety and rollback

Mutations only apply with `--apply`. Before writing, the CLI saves the current
registry entry, capability projection, and source document in a fixed evidence
directory. It atomically writes each file and then reads the complete state
back. `resource rollback` accepts only the opaque backup ID format and verifies
both resource identity and derived targets before restoring anything.

```bash
agentic-os resource create rule safe_delivery \
  --display-name "Safe delivery" \
  --description "Require verified delivery receipts." \
  --prompt "Do not claim delivery without a current receipt." \
  --dry-run --root ~/agentic_os --json

agentic-os resource create rule safe_delivery \
  --display-name "Safe delivery" \
  --description "Require verified delivery receipts." \
  --prompt "Do not claim delivery without a current receipt." \
  --apply --root ~/agentic_os --json
```

## Analytics metric presentation registry

Fresh and updated installs include
`harness/registries/analytics-metrics.yml`. It contains presentation metadata
for Command Center graphs: label, summary, category, unit, default window,
enabled state, and visualization hints. Defaults cover queue depth, task process
time, messages, workers, tokens, chats by harness, automation runs, errors, and
tool runs.

This file intentionally contains no data-source query language. Runtime
collectors and reporting components own values and aggregation; the registry
only controls safe presentation. A strict JSON schema rejects unknown fields,
including attempts to add query, command, URL, or path properties.

## Ownership and extension

The source package owns the schema, default analytics presentation registry,
CLI implementation, and system registry defaults. Installed roots own managed
resource content created through the CLI. Add a new resource kind only when it
has a deterministic target map, a validation contract, capability projection,
backup/readback coverage, and tests for path and identity rejection.
