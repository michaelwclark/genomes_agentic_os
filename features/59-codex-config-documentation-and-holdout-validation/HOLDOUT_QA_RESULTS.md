# Holdout QA Results

Passed.

- Config holdout matrix: passed for all six layers across dry-run, apply,
  idempotent re-run, and doctor.
- Conflict path: unconfirmed apply blocked; confirmed apply with backup passed;
  doctor passed afterward.
- Missing-config path: doctor failed as expected with remediation.
- `uv run --extra dev pytest -q`: 46 passed in 3.27s.
- Docs/content checks: TOCs, how-to flows, config example, SVG diagram, command
  help, validation log, and summarizer section present.

- Merged-main final config matrix: passed for all layers, conflict/backup path, and missing-config path.
