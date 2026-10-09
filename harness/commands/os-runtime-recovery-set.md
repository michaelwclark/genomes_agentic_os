---
name: os-runtime-recovery-set
description: Capture, encrypt, verify and restore complete Execution Fabric recovery sets.
---

# Execution Fabric recovery sets

Use `agentic-os runtime recovery-set` for complete recovery sets. Installation leaves daily whole-set capture and BigMac collection disabled until the installed stores, custody, maintenance hold and restore drill have been qualified.

- `plan` resolves a closed capture plan from explicit component paths.
- `prepare` stages a consistent complete set under a verified maintenance receipt.
- `pull` transports one closed set from the configured primary's fixed staging root.
- `collect` encrypts a transported set into the custodian's repository and verifies restored bytes.
- `verify` hashes component bytes and rejects partial or changed sets.
- `restore-plan` and `restore-isolated` operate on an exact immutable snapshot in an empty isolated target.
- `retention-plan` and `retention-apply` preserve qualified recovery points under custodian control.

Mutation defaults to dry run; use `--apply` only after reviewing the exact plan. Paths, credentials and authority come from an explicit reviewed configuration, never guessed placeholder databases. Commands do not start production services, change witness authority, replay work or clear the personal fallback latch. Use the dedicated cold recovery protocol for a fenced authority transfer.

See [backup and recovery](../../docs/operations/execution-fabric-backup-recovery.md) for clone, configure, capture, collection, isolated restore and failure recovery. A PostgreSQL backup-health result alone does not establish a complete recovery set.
