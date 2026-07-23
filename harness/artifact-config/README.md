# Artifact Configuration

This is the root artifact-authoring policy plane for every Agentic OS workflow.
Contracts are Markdown with YAML frontmatter, so operators can improve quality
without changing Python or registering every new file.

## Inheritance

```text
harness/artifact-config/<provider>/<artifact-type>.md
harness/artifact-config/<provider>/<artifact-type>/*.md
domains/<domain>/artifact-config/<provider>/<artifact-type>.md
domains/<domain>/artifact-config/<provider>/<artifact-type>/*.md
domains/<domain>/02-projects/<project>/artifact-config/<provider>/<artifact-type>.md
domains/<domain>/02-projects/<project>/artifact-config/<provider>/<artifact-type>/*.md
```

At each scope, resolution is least to most specific:

```text
any/any.md
any/any/*.md
any/<artifact-type>.md
any/<artifact-type>/*.md
<provider>/any.md
<provider>/any/*.md
<provider>/<artifact-type>.md
<provider>/<artifact-type>/*.md
```

Files inside an addenda directory all use the directory identity in
frontmatter. Prefix names with `10_`, `20_`, and so on when order matters.
Use addenda for separable quality modules such as acceptance criteria,
technical mapping, QA rollout, review, or closeout—not for another workflow or
state machine.

Scopes then compose root → domain → project → explicit invocation overlay.
Narrower files may specialize layout, terminology, evidence, and destination;
they cannot weaken inherited sanitization, approval, target verification, or
readback requirements. Use `agentic-os artifacts resolve ... --explain` to see
every source and blocked override.

## Operator loop

1. Resolve the effective contract.
2. Render a local provider-adapter draft from a structured evidence mapping.
3. Validate required evidence receipts, semantic assertions, sections, and
   external-output safety.
4. Apply only with `--execute`; external providers also require matching typed
   approval and target-verification receipts.
5. For an external provider, use the registered tool from the generated
   adapter handoff, read the artifact back, and record normalized live content
   in an `artifact-provider-readback/v1` receipt. The engine verifies its hash.

The three external-governance schemas are `artifact-approval/v1`,
`artifact-target-verification/v1`, and `artifact-provider-readback/v1`.
Receipts must live under the installed OS root and match provider, artifact
type, contract fingerprint, and verified target exactly.

`README.md` is explanatory and is not a contract candidate.
