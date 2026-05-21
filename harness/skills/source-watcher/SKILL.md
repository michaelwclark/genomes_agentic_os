# Source Watcher

Use this skill to configure or audit provider-agnostic connected source watchers.

## Workflow

1. Load `shared_factory/00-control-plane/connected-systems.yml` and `source-providers.yml`.
2. Verify workspace or account identity before reading customer or private systems.
3. Create or inspect `watch-sources.yml`.
4. Confirm every enabled source has a cursor, idempotency key, trigger rule path, and route/context contract.
5. Prefer dry-run polling before provider triggers or webhooks.
6. Normalize provider output into `source-event.yml` shape.

## Done

- Provider choice is explicit.
- No secrets are stored in registries or source events.
- Dry-run output can be inspected before any queued work is created.
