# Memory Policy: <domain>

## Purpose

Define what agents may store in durable memory for this domain.

## Store In Memory

- Stable user preferences.
- Durable domain rules.
- Repeated repo facts.
- Known failure modes.
- Useful workflow shortcuts.

## Do Not Store In Memory

- Secrets.
- Active status as the only source of truth.
- Large transcripts.
- Customer-sensitive raw data unless explicitly allowed.
- Temporary assumptions.

## Required Memory Note Shape

- Fact:
- Scope:
- Source:
- Date:
- Expiration or review trigger:

## Review Policy

Memory should be reviewed when:

- A workflow changes.
- A client operating rule changes.
- A repo layout changes.
- A stored fact causes an agent mistake.
