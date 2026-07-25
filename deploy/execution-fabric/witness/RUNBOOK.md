# Leadership witness deployment and operations

## Boundary

Deploy this stack into an AWS account and region whose failure domain is
independent from `genomesbox` and `bigmac`. The repository does not select an
account, create secrets, or enable promotion. The operator supplies all network
IDs, an ACM certificate, an existing ECS cluster, and digest-pinned images.

## Provision

1. Build, scan, sign, and publish the witness container. Record the immutable
   `image@sha256:...` reference.
2. Select a digest-pinned AWS CLI bootstrap image.
3. Create distinct random reader and admin bearer tokens, a JSON map containing
   one unique candidate token per host, and one Ed25519 PKCS8 private key in
   Secrets Manager. Distribute each host only its candidate token, the reader
   token where status readback is required, and only the corresponding SPKI
   public key to control-plane and gateway hosts. Keep the admin token
   operator-controlled. Do not put secret values into parameters, environment
   files, logs, or this repository.
4. Make the task subnets private with outbound AWS API access. Restrict the ALB
   security group to approved operator/host egress addresses; restrict the task
   security group to port 3195 from the ALB security group only.
5. Validate and deploy:

   ```bash
   aws cloudformation validate-template \
     --template-body file://cloudformation.yml

   aws cloudformation deploy \
     --template-file cloudformation.yml \
     --stack-name execution-fabric-witness \
     --capabilities CAPABILITY_IAM \
     --parameter-overrides file://operator-owned-parameters.json
   ```

   The operator parameter file is local and must not be committed.

6. Verify stack completion, two healthy ECS tasks, HTTPS certificate validity,
   DynamoDB point-in-time recovery, TTL, encryption, retained deletion policy,
   and ALB deletion protection.
7. Set `FABRIC_LEADERSHIP_API_BASE` and a local
   `FABRIC_LEADERSHIP_TOKEN_FILE`, then run `bin/smoke-test.sh`.

## Candidate reporting

Each host Compose profile runs `candidate-reporter`. It reports its own
database recovery state, timeline, receive and replay LSNs, measured replay
lag, absolute WAL positions, upstream system ID, receiver state and
last-message time, database clock, and canonicalized Execution Fabric config SHA-256 every
bounded interval. It does not accept caller-supplied health or lag. Monitor the
durable host-side health receipt with:

```bash
installers/execution-fabric/bin/candidate-reporter-health.sh --require-active
installers/execution-fabric/bin/candidate-reporter-health.sh --require-standby
```

Never report `healthy` from a remote ping alone. The report must be derived from
local PostgreSQL role/readiness, replication position, and the effective
schema-validated config digest. Candidate observations expire automatically for
eligibility even though their audit record remains durable. The host freshness
monitor alerts independently of the primary API and watchdog. Promotion and
failback scripts require the appropriate fresh mode-specific receipt.

The status response must show a fresh `leaderWalPosition`,
`leaderBaselineAt`, and `upstreamSystemId`. Candidate eligibility is calculated
against that upstream baseline. Never promote based only on a candidate's local
receive/replay difference: a disconnected standby can report a zero local gap
while remaining behind the primary. The shipped primary profile bootstraps with
local commits and no synchronous target, which keeps application mutations
fenced. Run `enable-postgres-durable-primary.sh` only after a standby is
streaming; the script enables and reads back `synchronous_commit=remote_apply`
with one synchronous standby. That verified receipt is required for the
promised zero acknowledged-write-loss mode.

## Promotion

Promotion is permitted only after:

- the status endpoint shows `currentLeader=genomesbox`;
- `promotionAllowed=true`;
- `bigmac` is eligible and inside the configured lag limit;
- the watchdog has a durable outage incident receipt;
- the emergency bundle validates;
- an approved drill has proven the exact release;
- the operator has explicitly enabled automatic promotion.

Promotion waits for the former leader's entire signed proof-lease window to
expire; a single negative health report is not revocation. The promotion
command sends the expected leader and epoch. DynamoDB atomically
checks those values, checks both leader and candidate evidence, advances the
epoch, and stores the audit receipt. Before PostgreSQL is promoted, the local
installer verifies the Ed25519 signature and exact cluster, leader, epoch,
receipt ID, expiry, and current witness readback. A stale request returns HTTP
409 and must never be retried with guessed values.

## Manual failback

1. On `bigmac`, authorize a state- and epoch-bound standby reseed:

   ```bash
   installers/execution-fabric/bin/failback.sh --prepare
   ```

2. Use the returned preparation receipt to rebuild `genomesbox`, then request a
   transfer plan only after the witness reports the target eligible:

   ```bash
   installers/execution-fabric/bin/failback.sh \
     --reseed \
     --preparation-file /exact/path/to/failback.reseed-authorization.json

   installers/execution-fabric/bin/failback.sh \
     --plan \
     --preparation-file /exact/path/to/failback.reseed-authorization.json
   ```

3. Review the exact source, target, epoch, expiry, replication state, timeline,
   and config digest. Record an approval artifact bound to the transfer plan:

   ```bash
   installers/execution-fabric/bin/failback.sh \
     --approve \
     --operator 'operator-identity'
   ```

4. Apply with the returned approval file:

   ```bash
   installers/execution-fabric/bin/failback.sh \
     --apply \
     --approval-file /exact/path/to/failback.approval.json
   ```

5. The preparation phase creates the replication slot, rebuilds `genomesbox`
   from the still-witnessed `bigmac` primary, and stores measured eligibility.
   The apply phase stops `bigmac` mutation roles before asking the witness to
   advance the epoch. The witness verifies the approval hash and freshness,
   atomically consumes the transfer plan, and returns a new signed fence
   receipt. `genomesbox` validates that receipt and current witness state before
   PostgreSQL promotion. Its application mutations remain fenced until
   durable-primary activation proves the rebuilt `bigmac` standby.
6. Only after `genomesbox` is active does the installer erase and rebuild
   `bigmac` as the new standby. Treat a failure in this final reseed as a
   critical degraded-redundancy incident, but do not roll leadership backward.
   Reused plans, stale approvals, stale timelines, and ambiguous data volumes
   fail closed.

## Backup, alarm, and recovery

- Alarm on fewer than two healthy ECS tasks, ALB 5xx, target response time,
  DynamoDB throttling/system errors, and absence of fresh candidate reports.
- Retain CloudWatch logs and DynamoDB point-in-time recovery across stack
  deletion. Test table restore in a non-production account.
- A DynamoDB restore is not automatically authoritative. Recover into a new
  table, verify the latest audit/leader/epoch with the incident commander, then
  deploy a new task definition that points at that table.
- Rotate reader, candidate, admin, and signing credentials independently by
  forcing a new ECS deployment and distributing only the credentials needed
  by each host. Never rotate the signing key during an unresolved promotion or
  failback.

## Activation prerequisite

The implementation and template are portable, but AWS activation remains an
operator action. Until a real stack, endpoint, secrets, alarms, candidate
reporters, and successful promotion/failback drill have provider readback,
automatic promotion must remain disabled.
