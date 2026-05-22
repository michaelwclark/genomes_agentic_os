# Holdout QA Results

Temp root: `/var/folders/n9/1qn8bnqn0vl70d18byskc4nr0000gn/T/agentic-os-feature53-PUk532/agentic_os`

| Step | Command | Result |
| --- | --- | --- |
| 1 | `uv run agentic-os init --target <temp-root>` | PASS, exit 0 |
| 2 | remove `commands/os-event.md` and `templates/runtime/event-envelope.yml` | PASS, files removed for repair check |
| 3 | `uv run agentic-os docs update --root <temp-root>` | PASS, exit 0; restored both managed files |
| 4 | `uv run agentic-os validate --root <temp-root>` | PASS, exit 0 |
| 5 | `uv run agentic-os event append --root <temp-root> --type github.pull_request.merged --source github:genomes_agentic_os:pull/123 --summary "PR 123 merged into main."` | PASS, exit 0; event `evt_eee46beaacaf` written |
| 6 | enable `feature_merged_to_docs_update` chain rule and clear its repo filter | PASS |
| 7 | `uv run agentic-os chain doctor --root <temp-root>` | PASS, exit 0 |
| 8 | `uv run agentic-os chain test feature_merged_to_docs_update --event <event-file> --root <temp-root>` | PASS, exit 0 |
| 9 | `uv run agentic-os event process-due --root <temp-root> --dry-run` | PASS, exit 0; no run queue write |
| 10 | `uv run agentic-os event process-due --root <temp-root> --apply` | PASS, exit 0; `documentation_update` queue item written |
| 11 | repeat `event process-due --apply` | PASS, exit 0; already processed idempotency key skipped |
| 12 | `uv run agentic-os event replay evt_eee46beaacaf --root <temp-root> --dry-run` | PASS, exit 0 |
| 13 | append `example.failed` event and broken enabled chain rule | PASS |
| 14 | `uv run agentic-os chain doctor --root <temp-root>` | PASS, expected exit 1 with missing enqueue action |
| 15 | `uv run agentic-os event process-due --root <temp-root> --apply` | PASS, exit 0; dead-letter record written |
| 16 | create workflow/run-log and run `run-log close --emit-events` | PASS, exit 0; closeout event emitted |
| 17 | `uv run --extra dev pytest -q` | PASS, 39 passed in 2.92s |

Assertions:

- Restored event command: yes.
- Restored event envelope template: yes.
- Event ledger index exists: yes.
- Apply mode wrote a documentation update queue item: yes.
- Repeated apply skipped duplicate work: yes.
- Dead-letter records written: 1.
- Run closeout emitted event evidence: yes.
