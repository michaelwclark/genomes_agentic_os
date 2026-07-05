# Review Lanes

Use only lanes that match the PR. Small PRs can run on the main thread with Graybeard plus Testing and Acceptance.

| Change Type | Required Lanes |
|---|---|
| Django model, migration, query | Database, Django, Testing, Architecture |
| Serializer, view, API | Django, Security, Existing Patterns, Testing, Documentation |
| Vue2 or Vue3 | Vue, Existing Patterns, Testing, Accessibility when relevant |
| Constance, config, env | DevOps, Documentation, Testing, Existing Patterns |
| Celery or background jobs | Durable Execution, DevOps, Testing, Database if persistence changes |
| Auth, permissions, tenant scoping | Security, Django, Existing Patterns, Testing |
| PR with Jira | Project Manager Acceptance |
| Large or refactor PR | Architecture, Existing Patterns, Readability, Testing |

Merge rules:

1. Drop findings below the requested severity threshold.
2. Drop findings without current evidence.
3. Merge duplicates by keeping the most concrete file or line anchor.
4. Prefer question-led comments with implementation paths.
5. Choose the shortest markdown depth that remains actionable.
6. Include code suggestions where feasible.
7. Label uncertainty as an open question.

