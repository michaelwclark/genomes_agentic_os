# Router: spec_grooming

Route universal idea-to-spec work through this program before changing
component internals.

| Request | Route |
| --- | --- |
| Rough idea, feature concept, future work, or operating-system proposal | `harness/skills/spec-groomer/SKILL.md` |
| Slash command invocation | `harness/commands/os-groom-spec.md` |
| Packet shape or original-intent requirements | `templates/` |
| Example quality or holdout coverage | `examples/` |
| Registry or harness visibility change | `components.yml` and the linked registries |
| LOS Django or Jira-primary grooming | Delegate to `$jira-product-orchestrator`; keep this program as routing context only |

