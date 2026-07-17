# Project Domain Intelligence Documentation

## Operator guide

Run `/project-domain-investigate <topic>` to retrieve a bounded domain context
receipt. Use the receipt ID in grooming, planning, coding, review, and upkeep
artifacts. Run the refresh script only in observe mode unless a human has
approved article replacement.

## Developer guide

The canonical workflow is `project-domain-architecture-analysis`; the portable
toolkit is `project-domain-analysis`. Source code, tests, config, and runtime
observations outrank articles. Roll back by restoring the previous article
revision referenced by its receipt; the observe-only refresh itself has no
article mutation to undo.
