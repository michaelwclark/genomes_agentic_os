# Auto-Dev Artifact Producer Contract

This rule applies whenever a skill, command, workflow, automation, report,
investigation, or development stage creates durable human-facing output.

1. The owning workflow gathers evidence and lifecycle state; it does not own
   provider formatting.
2. Resolve root → domain → project → invocation `artifact-config`, including
   every ordered addendum for the provider/type.
3. Render a local provider-adapter envelope and validate verified evidence
   receipts, semantic assertions, structure, and sanitization.
4. External apply is a separate approved provider action with typed approval
   and target-verification receipts. Verify workspace,
   project/repository/space/team, parent/object, and create-versus-update intent.
5. Read normalized live provider content back, compare semantic identity and
   the engine-computed content hash, and record provider ID, URL when safe,
   observed target fields, contract/evidence hashes, and timestamp.
6. A producer may retain specialized discovery, analysis, decomposition, or
   transport logic. It must not retain a competing renderer, copied formatting
   policy, external safety policy, or second readback contract.

Use `$auto-dev-create-artifacts` or `agentic-os artifacts ...` even when
artifact authoring is nested inside Spec Engine, Detective, Auto-Dev, review,
release, report, intake, closeout, program, or workflow creation.
