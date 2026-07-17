# CRUD: Project Domain Intelligence

## Create

Create one domain-local `project_domain_intelligence` instance that identifies
the project root, domain registry, article locations, and receipt location.

## Read

Use `/project-domain-investigate` to select a bounded evidence set and emit a
context receipt. Consumers record the receipt ID they used.

## Update

Refresh evidence in observe mode first. Apply article replacements only through
an explicit approved run; retain conflicting evidence and update freshness.

## Delete or retire

Disable the schedule, preserve receipts and articles, then archive the instance
only after consumers no longer reference it.
