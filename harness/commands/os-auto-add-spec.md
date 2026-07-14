# OS Auto Add Spec

Compatibility command: `/auto-add-spec`

Use the canonical `spec-engine` skill when a long, multi-part request should be
durably tracked before implementation continues.

1. Resolve domain/project and search for a matching Spec.
2. Update the match, or call `agentic-os spec add` with the inferred canonical
   type and status.
3. Use `grooming` only when the request actually begins spec development;
   otherwise leave new work at `idea`.
4. Return the YAML receipt to the orchestrator before implementation.

Do not call `agentic-os-intake-row`, create a Notion queue row, or write a
parallel feature packet. Follow `harness/commands/os-add-spec.md`.
