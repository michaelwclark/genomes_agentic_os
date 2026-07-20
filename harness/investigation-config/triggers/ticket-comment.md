---
schema_version: 1
id: ticket-comment
kind: trigger
title: Ticket comment
priority: 15
applies_to:
  triggers: [ticket-comment]
evidence:
  - ticket identity and current status
  - exact comment and author context
  - linked acceptance criteria
  - linked releases and changes
---

# Ticket comment trigger

Treat the current tracker item as lifecycle truth and the comment as a new
signal, not automatically a new requirement. Resolve ambiguity against the
ticket, linked artifacts, and deployed behavior before recommending scope.
