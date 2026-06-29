# OS Run Build Runner

Use when driving the source repository from the configured Kanban queue through
the shared `build-runner` skill.

## Procedure

1. Read root `CONFIG.md`.
2. Read `harness/skills/skill-registry.yml`.
3. Read `harness/skills/build-runner/SKILL.md`.
4. Verify Notion access points to Genome's Notion before any board write.
5. Load the configured Notion Kanban database.
6. Filter to `BUILD_RUNNER_QUEUE`.
7. Sort by `BUILD_RUNNER_ORDER`.
8. Run preflight:
   - git status
   - target branch detection
   - baseline verification commands
   - existing `SPECS/`, `WORKLOGS/` or `worklogs/`, legacy `features/`,
     legacy `PLANS/`, legacy `BUILD_LOGS/`, and `RUN_STATE.json`
9. Start with the first unblocked, incomplete card.
10. Execute the build-runner phases for that card.
11. Persist `RUN_STATE.json` after every phase.
12. Sync the source card after every major state change.

## Immediate Bootstrap Run

For the current Genome's Agentic OS source build, use:

```text
Use /Users/genome/projects/genomes_agentic_os/harness/skills/build-runner/SKILL.md.
Use /Users/genome/projects/genomes_agentic_os/CONFIG.md.
Use /Users/genome/projects/genomes_agentic_os/harness/skills/skill-registry.yml.

Run Build Runner against the configured Notion Kanban.
Queue: Ready.
Order: title-prefix-ascending.
Start with the lowest incomplete prefix.
For the first live run, execute only one feature unless the user explicitly asks for the full queue.
Do preflight first and stop if Notion write access is not verified as Genome's Notion.
```

## Output

Return:

- Feature selected.
- Preflight result.
- Created or reused artifact paths.
- Worktree and branch.
- Verification baseline.
- Board writeback status.
- Next action.
