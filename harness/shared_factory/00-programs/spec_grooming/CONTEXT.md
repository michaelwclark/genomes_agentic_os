# Context: spec_grooming

`spec_grooming` is the shared Agentic OS capability for turning rough ideas
into implementation-grade spec packets without losing the user's original
intent.

The program is intentionally a thin universal layer. It owns raw intent capture,
capability discovery, route selection, packet completeness, assumption tracking,
and projection receipts. Domain-specific groomers remain responsible for their
own execution details.

## Source Of Truth

- Filesystem work item packets are authoritative.
- Linear, Jira, and Notion are projections.
- Notion writes require verified Genome's Notion.
- External tracker text must be sanitized before posting.

## Key Adapter Rule

LOS Django and Jira-primary work must route to `$jira-product-orchestrator`.
The universal groomer may capture routing context, but it does not replace the
Jira-specific grooming suite.

