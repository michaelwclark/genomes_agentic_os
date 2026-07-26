# Process Gates

Focus: commit/PR hygiene and scrubbed external text are release gates, not suggestions.

## Write
- Repo commit convention with the ticket key, real operator identity, no
  `--no-verify`, PR body from the repo template with tracker link and test
  evidence.
- Scrubbed external text: no local paths, no internal tool names, no em
  dashes in copy-paste prose.

## Review
- Identity check on outgoing commits, PR body completeness, and
  scrubber-clean external writebacks are verified before declaring a run
  done.

Blocking: always.
