# Documentation: Spec Engine

## Filesystem Documentation

This program ships from the legacy-compatible source path
`harness/shared_factory/00-programs/spec_grooming/` with canonical identity
`spec_engine`. It is copied into installed OS roots by docs install/update.

## Provider Documentation

The canonical operator guide is `docs/29-spec-engine.md`. CLI truth comes from
`agentic-os spec --help`; compatibility commands must link to the canonical
guide instead of restating lifecycle rules.

## Notion Projection

When requested, create an operator-facing Genome's Notion page after verifying
the target workspace. The page should summarize:

- what capability is being groomed;
- why it exists;
- route decision and existing capability evidence;
- packet links or repo-relative references;
- tracker projection receipts;
- validation and next actions.

Notion is optional and never an intake dependency. Do not paste private local
paths into external tracker text. Internal Notion receipts may record page ids
and private links.
