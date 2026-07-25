#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { verify } from "node:crypto";

const [receiptPath, publicKeyPath, expectedCluster, expectedLeader, expectedEpoch] =
  process.argv.slice(2);
if (
  !receiptPath ||
  !publicKeyPath ||
  !expectedCluster ||
  !expectedLeader ||
  !expectedEpoch
) {
  throw new Error(
    "usage: verify-leadership-receipt.mjs RECEIPT PUBLIC_KEY CLUSTER LEADER EPOCH",
  );
}
const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
const [version, encoded, signature, ...extra] = String(
  receipt.fenceToken ?? "",
).split(".");
if (version !== "v2" || !encoded || !signature || extra.length) {
  throw new Error("receipt fence token envelope is invalid");
}
if (
  !verify(
    null,
    Buffer.from(encoded),
    readFileSync(publicKeyPath, "utf8"),
    Buffer.from(signature, "base64url"),
  )
) {
  throw new Error("receipt fence token signature is invalid");
}
const proof = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
if (
  proof.v !== 2 ||
  proof.cluster !== expectedCluster ||
  proof.leader !== expectedLeader ||
  proof.epoch !== Number(expectedEpoch) ||
  proof.receiptId !== receipt.receiptId ||
  receipt.clusterId !== expectedCluster ||
  receipt.currentLeader !== expectedLeader ||
  receipt.fabricEpoch !== Number(expectedEpoch)
) {
  throw new Error("receipt identity, cluster, leader, epoch, or id does not match");
}
if (Date.parse(proof.expiresAt) <= Date.now()) {
  throw new Error("receipt fence token has expired");
}
process.stdout.write(
  JSON.stringify({
    valid: true,
    clusterId: proof.cluster,
    leader: proof.leader,
    fabricEpoch: proof.epoch,
    receiptId: proof.receiptId,
    expiresAt: proof.expiresAt,
  }),
);
