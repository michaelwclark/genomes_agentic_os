# Verified MinIO release images

These two images package the official signed MinIO server
`RELEASE.2025-09-07T16-13-09Z` and client `RELEASE.2025-08-13T08-35-41Z`
payloads. Their versions remain unchanged. The [input lock](upstream-lock.json)
pins both architectures, release and asset identifiers, annotated source tags,
full payload checksums, Minisign signatures and verifier, upstream entrypoint
and license files, and the UBI base index and platform manifests.

`prepare-minio-build-inputs.py` validates this closure, observes the official
release and signed source tags, verifies full download hashes, checks ELF
architecture and upstream checksum records, and executes Minisign before it
emits a build context. A bad cache entry fails verification without falling
back to another source. The Dockerfile downloads nothing; it copies only
verified context files into the immutable base, which already supplies curl.

The PR workflow builds both server and client on `linux/amd64` and
`linux/arm64`. Real container checks compare binary, version, source commit
and curl bytes, then exercise readiness, root credentials from environment
and files, the upstream user-switch entrypoint, private versioned buckets,
object write/read/delete and persistence across an actual restart. Fixtures
are isolated and removed before a passed receipt is emitted.

On a normal release tag, the publisher builds both owned multi-architecture
indexes, attaches build provenance and SBOMs, runs the same checks against the
published immutable references, and reads back each index and child manifest.
GitHub attestation verification binds the index digest to the repository,
release workflow, source commit and tag. The asset builder requires the
complete current input, publication and runtime receipts before assembling
the existing eight release assets. MinIO and client references in the runtime
image lock use owned `repository@sha256` values; PostgreSQL and Valkey retain
their upstream image repositories.

Changing an upstream version, source, verifier or base requires a reviewed
lock change and fresh checks. An unavailable payload, registry, signature or
runtime proof stops publication. There is no mirror, mutable-tag fallback,
SDK-only publication or retry of an immutable failed release tag. Rebuilt
containers have a new owned image identity; matching upstream binary and
runtime contracts does not claim byte parity with historical upstream images.
