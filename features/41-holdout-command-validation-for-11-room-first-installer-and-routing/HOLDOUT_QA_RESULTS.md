# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: `39 passed in 3.20s`.
- `uv run agentic-os profile validate <profile>`: returned `ok: true` with rooms `writing_room` and `operations_room`.
- `uv run agentic-os init --target <temp-root> --profile <profile>`: created the temp root and reported both rooms.
- `uv run agentic-os validate --root <temp-root>`: returned `valid: <temp-root>`.
- Filesystem check: `writing_room` and `operations_room` exist; `personal`, `clarks_consulting`, `los`, and `archive` do not.
- Pointer check: root `AGENTS.md` and `CLAUDE.md` reference `ROUTER.md`.
- Managed-room check: both room `CONTEXT.md` and `ROUTER.md` files include `room-profile-managed`.

`shared_factory` is present because profile installs still ship shared runtime
documentation. It is not treated as a Genome default operational domain for
this holdout.
