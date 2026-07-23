# Auto-Dev: release

Use `/auto-dev-release` to publish or verify a version, tag, package, changelog,
container/image, or provider release. Release Propagation is a separate stage
for moving code across GitFlow branches. Project policy decides which outputs
exist and which merged revision is eligible.

## Inputs and authority

- exact merged or otherwise policy-authorized revision;
- project versioning, changelog, signing, build, packaging, and release rules;
- expected artifact names, registries/providers, target channels, and
  compatibility matrix;
- required checks, approvals, and prior propagation state;
- evidence that the proposed version/tag does not conflict with live provider
  state.

Never invent the next version from a branch name when the project has a release
authority, manifest, semantic-release rule, or provider registry.

## Release behavior

1. Resolve the release owner and verify the exact source revision.
2. Determine the version through project policy and confirm it is available.
3. Build from a clean, reproducible source boundary using the project workflow.
4. Validate package/image contents, metadata, migrations, generated files,
   dependency locks, signatures/attestations, and changelog/release notes as
   required.
5. Render teammate/customer-facing release text through Create Artifacts and
   sanitize unsupported or private information.
6. Obtain approval for provider publication when required.
7. Publish through the registered project owner.
8. Read back the tag/release/package/image from the provider and verify version,
   digest, source revision, files, and visibility/channel.

Do not overwrite an existing immutable version or silently republish different
bits under the same tag. A failed or partially published release is preserved as
an exact provider blocker and recovery plan.

## Done criteria

Record version, source commit, artifact identities/digests, build and validation
commands, approvals, provider references, and live readback. Release completes
only when the intended provider exposes the exact verified output.

Local packaging is `local_validation`, not a published release. A published
release is not proof it was deployed anywhere.
