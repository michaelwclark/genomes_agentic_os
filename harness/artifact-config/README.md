# Artifact Configuration

This is the root artifact-authoring policy plane for every Agentic OS workflow.
Contracts are Markdown with YAML frontmatter, so operators can improve quality
without changing Python or registering every new file.

## Inheritance

```text
harness/artifact-config/<provider>/<artifact-type>.md
domains/<domain>/artifact-config/<provider>/<artifact-type>.md
domains/<domain>/02-projects/<project>/artifact-config/<provider>/<artifact-type>.md
```

At each scope, resolution is least to most specific:

```text
any/any.md
any/<artifact-type>.md
<provider>/any.md
<provider>/<artifact-type>.md
```

Scopes then compose root → domain → project → explicit invocation overlay.
Narrower files may specialize layout, terminology, evidence, and destination;
they cannot weaken inherited sanitization, approval, target verification, or
readback requirements. Use `agentic-os artifacts resolve ... --explain` to see
every source and blocked override.

## Operator loop

1. Resolve the effective contract.
2. Render a local provider-native draft from a structured evidence mapping.
3. Validate required sections and external-output safety.
4. Apply only with `--execute` and a verified target.
5. For an external provider, use the registered tool from the generated
   adapter handoff, read the artifact back, and record its ID and hash.

`README.md` is explanatory and is not a contract candidate.
