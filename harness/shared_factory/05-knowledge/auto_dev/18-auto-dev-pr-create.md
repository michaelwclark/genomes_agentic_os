# Auto-Dev: PR Create

PR Create is the only Auto-Dev workflow that selects pull-request targets and
creates or reuses a 1-N PR family. It runs after Develop and Document and
before Review Self.

Resolve targets from the effective GitFlow topology plus tracker and registry
authority. A caller-supplied base branch is a candidate only. Record every
configured target as `pr_required`, `already_equivalent`, or `not_applicable`;
fail closed on omissions, ambiguity, stale authority, or an unreceipted
mismatch. Existing open or merged equivalents are idempotent success.

Provider rendering/apply/readback delegates to Create Artifacts. Review Self
consumes the exact family receipt and cannot create or retarget PRs. The legacy
GitFlow PR Create and Release Propagation names delegate here and retain only
argument/receipt compatibility.
