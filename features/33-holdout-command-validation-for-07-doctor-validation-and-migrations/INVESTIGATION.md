# Investigation

Feature 07 is implemented by `src/genomes_agentic_os/doctor.py` and
`src/genomes_agentic_os/migrations.py`. The holdout uses public CLI commands
instead of importing implementation helpers.

The most useful coverage is a mixed path: first create a missing managed file
blocker, then repair it, then create a stale run log, then exercise migration
preview/apply failure and success.
