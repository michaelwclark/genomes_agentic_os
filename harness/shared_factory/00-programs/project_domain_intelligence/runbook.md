# Runbook: Project Domain Intelligence

## Investigate

1. Load the program context pack and the project's instance configuration.
2. Run `/project-domain-investigate` with tracker text, touched paths, symbols,
   or a focus topic.
3. Record the returned context receipt in the calling artifact.

## Observe-only refresh

1. Run `scripts/project-domain-refresh --root <project> --receipt <path>`.
2. Confirm the receipt says `mode: observe` and `article_writes: false`.
3. Route stale coverage or contradictory evidence to operator attention.

## Recovery and rollback

Disable the refresh schedule before a manual repair. Restore the prior article
revision recorded in the last approved receipt; do not infer rollback content
from a generated summary.
