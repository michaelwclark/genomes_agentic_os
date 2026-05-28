# Remaining Roadmap Orchestration Index

This index tracks the follow-on orchestration prompts created after the Plan 15 kickoff.

## Prompt Set

| Plan | Priority | Prompt | Role |
| --- | --- | --- | --- |
| 16 | P0 | `/Users/genome/projects/genomes_agentic_os/PLANS/16-connected-source-watch-registry.orchestration.md` | Register connected systems and watch sources, then emit normalized source events. |
| 17 | P0 | `/Users/genome/projects/genomes_agentic_os/PLANS/17-event-graph-and-chained-automations.orchestration.md` | Process source/run events through deterministic chain rules and guarded queue entries. |
| 18 | P0 | `/Users/genome/projects/genomes_agentic_os/PLANS/18-visible-capability-registry.orchestration.md` | Make installed capabilities visible through registries and generated inventory. |
| 20 | P0 | `/Users/genome/projects/genomes_agentic_os/PLANS/20-operator-pushed-customer-updates-and-backups.orchestration.md` | Build the practical V1 customer update and backup path. |
| 19 | P1 | `/Users/genome/projects/genomes_agentic_os/PLANS/19-update-channel-and-customer-fleet.orchestration.md` | Define the broader update-channel and fleet-status contract. |

## Recommended Order

1. Finish Plan 15 runtime queue and scheduler semantics.
2. Run Plan 16 so external systems produce normalized source events.
3. Run Plan 17 so events can chain into guarded work.
4. Run Plan 18 so installed capabilities are visible and validated.
5. Run Plan 20 for the practical operator-pushed customer update path.
6. Run Plan 19 after Plan 20, keeping hosted fleet/phone-home work behind explicit policy gates.

## Analysis Notes

- Plans 16 and 17 already have implementation modules, templates, harness commands, skills, docs, and tests. Their prompts focus on hardening semantics rather than creating first files.
- Plan 18 has a compact spec and a supporting capability-registry spec. Its first safe slice should be additive registry visibility and inventory generation.
- Plan 20 is more immediately practical than Plan 19 because it avoids hosted fleet infrastructure and can be tested locally with fake billing fixtures.
- Plan 19 should stay local-first until update policies, rollback, phone-home payload safety, and customer fleet boundaries are proven.
