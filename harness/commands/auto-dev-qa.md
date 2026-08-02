# `/auto-dev-qa`

Run and receipt the project-configured QA gates as a standalone step. Use
`$auto-dev-qa`; unavailable infrastructure is evidence, not a passing result.

## Ticket-family invocation

For a project that has configured ticket-family QA, the operator-facing request
may include one or more ticket keys:

```text
Auto-Dev QA FLYWL-1234 FLYWL-5678
```

The equivalent explicit CLI form names the project that owns the QA stage:

```text
agentic-os auto-dev qa <domain> <project> FLYWL-1234 FLYWL-5678 --apply
```

The CLI establishes one durable work item per ticket. The effective project
policy defines eligibility, test type, fixtures/configuration, merge authority,
and tracker transitions; it must not be inferred from a shared harness skill.
