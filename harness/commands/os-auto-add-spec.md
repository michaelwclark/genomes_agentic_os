# OS Auto Add Spec

Use when a long request is clearly creating or changing Agentic OS behavior and
would otherwise remain only in chat.

Primary slash command: `/auto-add-spec`
Compatibility alias: `/auto-add-feature`

## Trigger

Use this command when a request includes several requirements, asks for durable
rules or conventions, mentions Notion/filesystem organization, or asks agents to
remember a new operating pattern.

## Procedure

1. Load the routed Agentic OS layer and `harness/rules/os-authoring-rules.md`.
2. Run `agentic-os doc-config plan` with the original user request.
3. Search for an existing active or intake work item that matches the request.
4. If none exists, create a project work-item packet with `SPEC`, `PLAN`,
   `WORKLOG`, `NEXT`, `QUESTIONS` when needed, and `CONVENTIONS` when reusable
   rules are requested.
5. Record the route, assumptions, and next action before implementation work.
6. Delegate bookkeeping to a subagent when orchestration is active, while the
   main agent focuses on product and engineering decisions.

## Guardrails

- Do not create a duplicate spec packet for a short one-off question.
- Do not load every historical work item to decide; use doc-config search
  methods in priority order.
- Do not write Notion until workspace verification succeeds.
- Do not generate `IDEA.md` for new packets. Existing `IDEA.md` files remain
  readable legacy capture.
