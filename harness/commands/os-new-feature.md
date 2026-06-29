# OS New Feature

Compatibility alias for `/add-spec`.

Use `/add-spec` as the primary command for future work, rough requests,
proposed features, and spec intake. Keep `/new-feature`, `/add-feature`, and
`/new-idea` working during the migration window for users and harnesses that
still use the older names.

## Procedure

Follow `harness/commands/os-add-spec.md`.

## Compatibility Notes

- `/new-feature` routes to the same doc-config and project work-item intake as
  `/add-spec`.
- New packets use `SPEC.md` as the raw-capture plus refined-spec file.
- Existing `IDEA.md` files remain readable legacy capture, but new packets
  should not generate them.
