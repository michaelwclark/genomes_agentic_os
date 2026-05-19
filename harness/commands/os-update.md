# OS Update

Use when updating an installed Agentic OS from the source package.

## Rule

Default updates are additive and idempotent. They add missing files and folders, but do not overwrite, delete, move, or archive existing runtime state.

## Procedure

1. Run `agentic-os docs update --root ~/agentic_os`.
2. Run `agentic-os validate --root ~/agentic_os`.
3. Review created files.
4. Leave existing runtime files untouched.
5. If an existing file needs to change, stop and prepare a migration plan with a reviewable diff.

## Output

Report created files, validation status, and any migration candidates.
