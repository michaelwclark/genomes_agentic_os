# OS Auto Add Feature

Compatibility alias for `/auto-add-spec`.

Use `/auto-add-spec` as the primary command for long OS-shaping requests that
need a durable local spec packet before implementation continues. Keep
`/auto-add-feature` working during the migration window for users and harnesses
that still use the older name.

## Procedure

Follow `harness/commands/os-auto-add-spec.md`.

## Compatibility Notes

- `/auto-add-feature` routes to the same doc-config and project work-item intake
  as `/auto-add-spec`.
- New packets use `SPEC.md` as the raw-capture plus refined-spec file.
- Existing `IDEA.md` files remain readable legacy capture, but new packets
  should not generate them.
