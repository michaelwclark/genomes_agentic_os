#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
  echo "usage: materialize-image-lock.sh EXECUTION_FABRIC_IMAGE_LOCK_JSON" >&2
  exit 64
}
image_lock=$1
[ -s "$image_lock" ] || {
  echo "execution fabric image lock is missing or empty: $image_lock" >&2
  exit 66
}
command -v jq >/dev/null 2>&1 || {
  echo "jq is required to validate and materialize the image lock" >&2
  exit 69
}

# JSON is the signed/released source of truth. Emit the one deterministic env
# projection consumed by Compose and recovery tooling; never accept a second,
# independently authored env lock.
jq -er '
  def digest_ref:
    type == "string" and
    test("^[a-z0-9.-]+(/[a-z0-9._-]+)+@sha256:[a-f0-9]{64}$") and
    (endswith("@sha256:" + ("0" * 64)) | not);
  if
    .schema_version == "execution-fabric-image-lock/v1" and
    (.release_version | type == "string" and length > 0) and
    (.images | type == "object") and
    (.images | keys) == [
      "control_plane",
      "leadership_witness",
      "minio",
      "minio_client",
      "postgres",
      "valkey",
      "worker"
    ] and
    all(.images[]; digest_ref)
  then
    [
      "FABRIC_CONTROL_PLANE_IMAGE=\(.images.control_plane)",
      "FABRIC_WITNESS_IMAGE=\(.images.leadership_witness)",
      "FABRIC_WORKER_IMAGE=\(.images.worker)",
      "FABRIC_POSTGRES_IMAGE=\(.images.postgres)",
      "FABRIC_VALKEY_IMAGE=\(.images.valkey)",
      "FABRIC_MINIO_IMAGE=\(.images.minio)",
      "FABRIC_MINIO_CLIENT_IMAGE=\(.images.minio_client)"
    ] | .[]
  else
    error("image lock must contain exactly seven immutable nonzero canonical image references")
  end
' "$image_lock"
