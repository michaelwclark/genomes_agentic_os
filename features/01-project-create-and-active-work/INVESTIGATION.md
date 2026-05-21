# Investigation

- Existing CLI had domain, workflow, automation, run-log, docs, and validate commands, but no project command.
- Existing scaffold already had domain aliases and domain `02-projects/README.md` creation.
- Validation does not need to require every project file globally; project creation tests verify the project contract directly while root validation continues to check structural OS health.
- Existing write helpers preserve files by default, so feature implementation extends that model with append-only index rows.
