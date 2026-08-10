# `/auto-dev-validate-production-release`

Run the blocking Auto-Dev production release-candidate validation after
Finalize and before Merge.

The workflow must verify:

- Jira Fix Version and GitHub branch/PR-family alignment for every target;
- exact source, build, PR head, merge, and artifact identity;
- one matching terminal-passing QA Run for every Jira item;
- the complete exact-head diff against the frozen effective Auto-Dev rules;
- all applicable performance, configuration, migration, security/tenancy,
  dependency, and compatibility gates; and
- artifact provenance, rollback/recovery, observability, and post-release
  verification.

It records a receipt and `ready_for_merge` decision or one exact blocker. It
does not mutate Jira, GitHub, release systems, or production.
