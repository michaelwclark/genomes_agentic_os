---
name: los-version-registry
description: Read or refresh the deterministic LOS environment, GitFlow, Jira fixVersion, release membership, and SHA-boundary registry.
---

# LOS Version Registry

1. Start in `/Users/genome/agentic_os`.
2. Read `los/00-programs/los_version_registry/context-pack.md`.
3. Follow `harness/skills/los-version-registry/SKILL.md`.
4. Scheduled refreshes use the deterministic hourly script and never invoke an
   LLM.
5. The daily Release Tracker report is also deterministic and must not be used
   to infer permission to change Jira labels or statuses.
