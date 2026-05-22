# Judgment

The guide is additive and keeps runtime state file-backed.

It explicitly separates Notion control-plane tracking from runtime storage and
keeps provider execution behind dry-run/setup records until credentials and
approval gates are verified.
