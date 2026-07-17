---
name: project-domain-investigate
description: Retrieve bounded, evidence-backed project-domain context and emit a receipt for grooming, planning, coding, review, or documentation upkeep.
---

# Project Domain Investigate

1. Read the target project's router and the `project_domain_intelligence`
   program context pack.
2. Treat source, tests, configuration, and runtime observations as authoritative
   over domain articles.
3. Select only topic-relevant fresh evidence. Exclude stale or invalid articles
   unless explicitly returning them as downgraded context.
4. Emit the context receipt consumed by the caller: selected article IDs and
   revisions, skipped items, budget, source revision, and open questions.
5. Fail open with a `no_context` receipt if the registry is unavailable.

Never modify articles or project source during this skill.
