# Auto-Dev Operator Runbook

## Start or route

1. Classify the request with `ROUTER.md`; route to domain/project.
2. Read the selected workflow and project configuration.
3. Run its resolver/status command before mutation.
4. Start or resume one run id; verify its policy fingerprint and source list.

For code delivery, `develop start --apply` provisions the canonical work item
and worktree. Run the named stage skill to do the work, write one
`development-stage-evidence/v1` JSON receipt per target state, then use
`develop stage` to record the stage. Direct `develop transition` is disabled.

## During execution

- Keep chat quiet while tests/checks/watchers are pending; store raw evidence in
  the run packet.
- Pause unavailable VPN/provider/environment sources instead of emitting
  repeated failures. Resume the same run when the prerequisite returns.
- Detective accepts only declared source IDs, a typed deployed-version
  authority receipt, evidence matching policy authority/prerequisites, explicit
  dispositions for sources not used, and evidence-ID-backed conclusions.
- External artifact apply requires `artifact-approval/v1` and
  `artifact-target-verification/v1`; close it only with a normalized
  `artifact-provider-readback/v1` receipt whose content matches the draft.
- A workflow hands off only a compact receipt, not duplicated raw state.

## Closeout

Verify acceptance/evidence, external readback, unresolved gaps, tracker/PR/
release/deploy state, cleanup decision, and final summary. Update program
worklog and Notion projection only from verified behavior.

## Health checks

```bash
agentic-os detective doctor --root <root>
agentic-os artifacts doctor --root <root>
agentic-os develop policy <domain> <project> --plane dev_standards --root <root> --json
agentic-os develop policy <domain> <project> --plane qa_gates --root <root> --json
agentic-os validate --strict --root <root>
agentic-os library doctor --root <root>
```
