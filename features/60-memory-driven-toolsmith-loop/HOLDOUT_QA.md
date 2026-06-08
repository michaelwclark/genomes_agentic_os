# Holdout QA

Before implementation is accepted, validate with seeded evidence and runtime
fixtures that cover:

- repeated manual command sequences
- recurring validation failures
- conversation sidecars with useful and useless correction signals
- task/work item lifecycle records with incomplete closeout evidence
- workflow closeout records that suggest a reusable workflow improvement
- automation runs that reference a skill or command later proposed for change
- stale memories
- duplicate memories
- conflicting recommendations
- token-shaped secret values
- prompt-injection text inside logs
- one project-local pattern that should not become a global rule
- one cross-project pattern that should become a shared skill or command
- one repeated pattern that should become a shared workflow or automation
- one proposed skill/command/workflow rename that requires a reference-migration
  plan for scheduled automation
- one Hermes-style "too narrow" artifact that should be demoted into a
  class-level skill's `references/`, `templates/`, or `scripts/` support file
- malformed `.usage.json` sidecars that must be quarantined in the run report
- legacy top-level `shared_factory/` references that are read-only evidence and
  never valid output roots
- symlinked proposal, approval, and draft directories that must be rejected
- locally modified managed files that must receive `.new` or migration-plan
  output rather than being overwritten
- concurrent scheduled apply and manual approve/promote attempts for the same
  proposal

Expected results:

- `run --dry-run` explains opportunities without writes, including no run
  records.
- `run --apply` writes redacted run and proposal files only under
  `harness/shared_factory/06-runs-and-logs/self-improvement/`.
- Redaction refusal reports field names and detector types, never secret values.
- Model review is skipped unless the runtime can enforce no write-capable tools.
- Duplicate active proposals are merged or suppressed by cooldown, while
  approved or drafted proposals are not mutated in place.
- Approval records bind proposal content hash, validation hash, approved target,
  approver marker, approval time, and control-plane hash.
- Promotion exits nonzero and writes nothing when the proposal, validation plan,
  approved target, output allowlist, or control plane differs from approval time.
- Promotion requires approval and creates draft artifacts without mutating live
  skills, commands, workflows, automations, Notion, shell config, or harness
  globals.
- Fresh install includes the self-improvement workflow, control-plane config,
  managed-template manifest, reviewer skill, command prompt, templates,
  run/proposal/approval/draft directories, and disabled-or-dry-run schedule
  target under `harness/shared_factory/`.
- Install, update, run, apply, approve, reject, and promote never write to
  legacy top-level `shared_factory/` paths.
