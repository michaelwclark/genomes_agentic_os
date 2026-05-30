# Plan

1. Establish the source-package plan.
   - Add a numbered plan under `PLANS/`.
   - Update `PLANS/README.md` so installed agents can discover it after docs update.

2. Capture the project lifecycle contract.
   - Define lifecycle states from captured idea through documented finish.
   - Define required files for work items.
   - Define state-specific agent read/write rules.

3. Normalize project artifact placement.
   - Keep domain ideas in `01-inbox/`.
   - Put project work packets under `<domain>/02-projects/<project>/work-items/`.
   - Keep reusable OS product plans under `harness/shared_factory/05-knowledge/plans/`.
   - Preserve old top-level `shared_factory` installs until a migration is explicit.

4. Define project policy configuration.
   - Support local source feature folders for `genomes_agentic_os`.
   - Support Jira promotion with local mirror for LOS Django.
   - Leave Notion as a projection guarded by workspace verification.

5. Specify conversation auto logging.
   - Use `YYYY_MM_DD_<slug>.jsonl` transcript names.
   - Extract tool calls to JSONL and Markdown sidecars.
   - Redact secrets before write.
   - Keep hook behavior best-effort and non-blocking.

6. Analyze hooks against the OS shape.
   - Compare current hooks with lifecycle needs.
   - Record missing hooks or command ideas.
   - Split implementation into safe follow-on slices.

7. Prepare implementation validation.
   - Add lifecycle template tests.
   - Add route/context lifecycle tests.
   - Add hook payload and redaction tests.
   - Add LOS Jira-policy and source-feature fixtures.

8. Close this planning pass.
   - Update `WORKLOG.md`, `SUMMARY.md`, `NEXT.md`, and `MEMORY.md`.
   - Do not mutate live `~/agentic_os`.
