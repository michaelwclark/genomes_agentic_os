# Development Standards Policy Plane

Every development, own-PR finalization, and others'-PR review run loads every
Markdown file in this folder, followed by the routed domain and project
folders. Files are ordered lexicographically within each folder. Later scopes
may add precision; the strictest safety and quality requirement still wins.

Conventional folders:

```text
harness/shared_factory/05-knowledge/auto_dev/dev_standards/
domains/<domain>/05-knowledge/auto_dev/dev_standards/
domains/<domain>/02-projects/<project>/config/auto_dev/dev_standards/
```

Projects may replace the ordered folder list through
`config/development.yml policies.dev_standards.paths`. Adding a Markdown file
changes the next run without a code or registry edit. `README.md` is explanatory
and is not loaded as policy.
