# Create Artifacts

![Create Artifacts flow](../../../00-programs/auto_dev/assets/auto-dev-create-artifacts.svg)

## What this does

Turns verified evidence into a provider-adapter, audience-safe artifact by
composing root, domain, project, and invocation Markdown contracts. Rendering
is local; external mutation is a separately approved, read-back action.

## Manual run

Use `/auto-dev-create-artifacts` from chat. The deterministic surface is
`agentic-os artifacts resolve|render|validate|apply|record-readback|doctor`.
Equivalent artifact-authoring requests route here implicitly.

## Inputs

- Routed domain/project, provider, artifact type, intended audience and target,
  structured evidence, authorization state, and optional invocation overlay.

## Outputs

- Effective-contract explanation and fingerprint, rendered artifact envelope,
  validation receipt, apply or provider-handoff receipt, target readback, and
  unresolved evidence gaps.

## States

`requested -> contract_resolved -> evidence_ready -> rendered -> validated ->
awaiting_approval -> applying -> readback_verified -> completed`. A draft may
stop successfully at `validated`. Provider unavailability uses `paused`, not a
failure storm.

## Steps

1. Verify provider, type, audience, destination, and mutation authorization.
2. Resolve `any/any`, `any/type`, `provider/any`, and `provider/type` across
   root → domain → project → invocation.
3. Normalize evidence and separate facts, inference, recommendations, gaps, and
   confidence.
4. Render the configured provider-adapter payload and Markdown inspection view.
5. Validate required evidence receipts, semantic assertions, sections, safety,
   target policy, and adapter format.
6. If only a draft was requested, return the draft plus receipts.
7. For approved apply, re-verify target, invoke the filesystem or registered
   provider adapter, fetch normalized live content, compare hashes/fields, and
   record the typed readback.

## Validations

- Contract sources are schema-valid, deterministically ordered, and fingerprinted.
- Narrower scopes did not weaken inherited safety or approval.
- Required content is present and allegations are not rendered as facts.
- External text contains no secret, local path, private workspace link, raw
  customer data, or provider-prohibited content.
- Typed approval and target-verification receipts match the exact artifact.
- Target identity and normalized provider content match after write.

## Success modes

- `validated_draft`: a local artifact is ready for operator review with no
  external side effect.
- `completed`: provider ID/URL, rendered readback, and content hash prove the
  intended target contains the validated artifact.

## Failure modes and recovery

- Contract error: block before render with file-and-field diagnostics; repair
  policy and rerun resolution.
- Evidence gap: remain local and gather evidence or record the gap explicitly.
- Validation/scrub failure: repair draft/evidence; never bypass.
- Provider/VPN unavailable: pause with the same idempotency/handoff receipt and
  resume when access returns.
- Target or readback mismatch: stop, preserve before/after evidence, and use the
  provider's governed repair/rollback path.

## Events and receipts

Emit `artifact.contract.resolved`, `artifact.rendered`, `artifact.validated`,
`artifact.apply.requested`, `artifact.provider.paused`,
`artifact.readback.verified|failed`, and `artifact.completed`. Retain evidence,
sources/hashes, effective contract, native payload, validation, provider action,
  typed approval/target/readback receipts, external identity, and readback.

## Cleanup and handoff

Keep compact receipts and the final draft; expire raw evidence by the routed
retention rule. Auto-Dev Detective and ticket intake consume the completed
artifact reference, not a copied rendering implementation.
