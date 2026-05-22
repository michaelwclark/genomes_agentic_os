# Investigation

The existing CLI already uses subcommands and filesystem-backed operations.
The config installer fits that pattern better than a standalone script because
it needs testable behavior, user-preserving writes, and repeatable holdout QA.

The installer should not assume Notion is the runtime database. It writes only
local files and reports conflicts for human review.
