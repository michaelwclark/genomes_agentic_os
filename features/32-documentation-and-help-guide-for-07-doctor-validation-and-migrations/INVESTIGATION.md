# Investigation

Feature 07 is implemented through `src/genomes_agentic_os/doctor.py` and
`src/genomes_agentic_os/migrations.py`, with CLI wiring in
`src/genomes_agentic_os/cli.py`.

The doctor aggregates validation, workflow, automation, active-work, project,
and run-log findings. `--fix-missing` invokes additive managed repair before
running checks.

The migration surface currently exposes `notion-sync-readme-v1`, which writes
`.notion-sync/README.md` after a saved preview confirms the target has not
changed.
