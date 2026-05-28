# 19 - Update Channel And Customer Fleet

## Intent

Support many installed Agentic OS roots across operator and customer
environments. Each install should know its version, update channel, update
policy, and whether it can safely phone home.

## Source Spec

- `spec/update-channel.md`

## Build Order

1. Add update metadata to `.agentic_root` and `agentic-os.lock.json`.
2. Add `UPDATE_POLICY.md` and `registries/updates.yml`.
3. Add update manifest schema.
4. Add CLI commands for `update check`, `update plan`, `update apply`,
   `update rollback`, and `update status`.
5. Add a heartbeat-safe phone-home command that emits only approved operational
   metadata.
6. Add additive update application for templates, registries, docs, and command
   definitions.
7. Add approval gates for executable, hook, MCP, rule, and permission changes.
8. Add rollback snapshots and post-update doctor checks.

## Acceptance Criteria

- Fresh installs declare update channel and policy.
- `agentic-os update check` reports available updates without mutating files.
- `agentic-os update plan` writes an inspectable plan.
- Safe additive updates can apply without overwriting local edits.
- Risky updates are blocked until policy approval.
- Phone-home payloads exclude prompts, customer files, source code, logs, and
  secrets.
- Update status is visible locally and can be mirrored into the control plane.

## Notes

Phone home is an operations feature, not an excuse to centralize customer data.
The safe default is metadata-only status plus explicit policy for auto-apply.

