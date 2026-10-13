/** Offline, per-item reconciliation. No provider call or inferred ownership. */
import { createHash, createPublicKey, randomUUID, verify } from "node:crypto";
import { lstatSync, readFileSync, type Stats } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath, pathToFileURL } from "node:url";
import type pg from "pg";
import { z } from "zod";
import { canonical, coldAnchorSchema, coldPlanSchema, coldPolicySchema, digest, fileHash, safeFile } from "./cold-recovery.js";
import { PolicyManager } from "./policy.js";

const hash = z.string().length(64).regex(/^[a-f0-9]{64}$/);
const text = z.string().min(1).refine((s) => Array.from(s).length <= 128, "identifier is oversized");
const uuid = z.string().length(36).uuid().regex(/^[a-f0-9-]{36}$/);
const counter = z.number().int().positive().max(Number.MAX_SAFE_INTEGER);
const stamp = z.string().datetime({ offset: true }).regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$(?![\s\S])/);
export const dispositionPayloadSchema = z.object({
  schemaVersion: z.literal("execution-fabric-cold-disposition/v1"),
  recoveryId: uuid, generation: counter, fabricEpoch: counter,
  clusterId: text, targetHost: z.string().regex(/^[A-Za-z0-9._-]{1,128}$(?![\s\S])/),
  pgSystemId: z.string().regex(/^[0-9]{1,32}$(?![\s\S])/), planSha256: hash,
  acceptedReceiptSha256: hash, acceptedPolicySha256: hash, policySha256: hash,
  configFingerprint: hash, executionPolicySha256: hash, sourceRelease: text,
  itemKind: z.enum(["task", "effect"]), itemId: uuid,
  itemSha256: hash, historySha256: hash, dependencySha256: hash,
  workItemId: text, workItemSha256: hash, owner: text, operator: text,
  contextSha256: hash, approvalId: text, approvalSha256: hash,
  disposition: z.enum(["hold", "task_cancel", "task_requeue", "effect_delivered", "effect_retry"]),
  priorDispositionSha256: hash.nullable(),
  idempotencyKey: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$(?![\s\S])/),
  reason: z.enum(["outcome_unknown", "owner_cancelled", "local_task_reconciled"]),
  issuedAt: stamp, expiresAt: stamp,
}).strict();
export const dispositionRequestSchema = z.object({
  payload: dispositionPayloadSchema, signature: z.string().length(88).regex(/^[A-Za-z0-9+/]{86}==$/),
}).strict();
export type DispositionPayload = z.infer<typeof dispositionPayloadSchema>;
export type DispositionReceipt = {
  schemaVersion: "execution-fabric-cold-disposition-receipt/v1";
  requestSha256: string; recoveryId: string; generation: number; fabricEpoch: number;
  clusterId: string; targetHost: string; pgSystemId: string; planSha256: string;
  configFingerprint: string; acceptedReceiptSha256: string; executionPolicySha256: string;
  itemKind: string; itemId: string; disposition: string; released: boolean;
  beforeSha256: string; afterSha256: string; historySha256: string;
  dependencySha256: string; owner: string; operator: string; contextSha256: string;
  workItemSha256: string; approvalSha256: string; policySha256: string;
  predecessorSha256: string | null; eventId: string;
};
const acceptedReceiptSchema = z.object({ schemaVersion: z.literal("execution-fabric-cold-ledger-receipt/v1"),
  operation: z.literal("accept"), recoveryId: uuid, planSha256: hash, fabricEpoch: counter,
  generation: counter, held: z.literal(false), residualQuarantine: z.literal(true) }).strict();
function acceptedReceipt(value: unknown, payload: Pick<DispositionPayload, "recoveryId" | "generation" | "fabricEpoch">, planHash: string): void {
  const receipt = acceptedReceiptSchema.parse(value);
  if (receipt.recoveryId !== payload.recoveryId || receipt.generation !== payload.generation
    || receipt.fabricEpoch !== payload.fabricEpoch || receipt.planSha256 !== planHash) throw new Error("durable accepted receipt identity differs");
}

/** Approval rows bind this non-circular hash; signatures bind the complete row. */
export function dispositionApprovalBinding(payload: DispositionPayload): string {
  const { approvalSha256: _approval, ...binding } = payload;
  return digest(binding);
}
function window(payload: DispositionPayload, maximum: number): void {
  const now = Date.now(), a = Date.parse(payload.issuedAt), b = Date.parse(payload.expiresAt);
  if (!(a <= now && now < b && b - a > 0 && b - a <= maximum * 1000)) throw new Error("disposition authorization window refused");
}
function sameFile(file: string, original: Stats): void {
  const current = lstatSync(safeFile(file));
  if (current.dev !== original.dev || current.ino !== original.ino) throw new Error("selected authority file changed");
}
function sameAuthorityFile(file: string, original: Stats): void {
  sameFile(file, original);
  if (lstatSync(file).mode & 0o077) throw new Error("selected canonical authority privacy changed");
}
function jsonMetadata(row: Record<string, unknown>): Record<string, unknown> {
  if (typeof row.metadata_json !== "string" || row.metadata_json.length > 65_536) throw new Error("canonical metadata unavailable");
  const value: unknown = JSON.parse(row.metadata_json);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("canonical metadata unavailable");
  return value as Record<string, unknown>;
}
type Authority = { database: DatabaseSync; file: string; identity: Stats; work: Record<string, unknown>; approval: Record<string, unknown> };
function existingAuthorityDatabase(file: string): DatabaseSync {
  // Native SQLite URI mode=rw opens an existing file without SQLITE_OPEN_CREATE.
  // readOnly:true cannot retain the canonical WAL writer fence; no fallback.
  const uri = pathToFileURL(file);
  uri.searchParams.set("mode", "rw");
  const database = new DatabaseSync(uri.href, { readOnly: false });
  try {
    const files = database.prepare("PRAGMA database_list").all();
    if (files.length !== 1 || files[0]?.file !== file) throw new Error("existing-only selected authority API unavailable");
    return database;
  } catch (error) { database.close(); throw error; }
}
function qualifiedAuthoritySchema(database: DatabaseSync): void {
  const versions = database.prepare("SELECT version FROM schema_version ORDER BY version").all();
  if (canonical(versions.map((row) => row.version)) !== canonical([1, 2, 3, 4, 5])) throw new Error("selected canonical authority schema is unqualified");
  for (const table of ["events", "run_queue", "cursors", "work_items", "work_item_history", "approval_requests", "artifact_references"]) {
    const row = database.prepare("SELECT type FROM sqlite_schema WHERE name=?").get(table);
    if (row?.type !== "table") throw new Error("selected canonical authority table unavailable");
  }
}

/** The native actor owns this barrier until PostgreSQL commit/rollback finishes. */
function acquireAuthority(policy: z.infer<typeof coldPolicySchema>, payload: DispositionPayload): Authority {
  const selected = policy.selectiveDisposition;
  if (!selected?.enabled || !selected.authority) throw new Error("selective disposition authority unavailable");
  const file = safeFile(selected.authority.databasePath), identity = lstatSync(file);
  if (identity.mode & 0o077) throw new Error("selected canonical authority must be private");
  const database = existingAuthorityDatabase(file);
  try {
    // Existing schema only; opening a missing database/bootstrap is prohibited.
    database.exec("PRAGMA busy_timeout=5000; BEGIN IMMEDIATE");
    sameAuthorityFile(file, identity);
    qualifiedAuthoritySchema(database);
    const work = database.prepare("SELECT * FROM work_items WHERE id=?").get(payload.workItemId) as Record<string, unknown> | undefined;
    const approval = database.prepare("SELECT * FROM approval_requests WHERE id=?").get(payload.approvalId) as Record<string, unknown> | undefined;
    if (!work || !approval || digest(work) !== payload.workItemSha256 || digest(approval) !== payload.approvalSha256
      || work.domain !== selected.authority.domain || work.project !== selected.authority.project
      || work.owner !== payload.owner || work.blocked_reason || work.state === "blocked"
      || approval.status !== "approved" || approval.subject_type !== "execution_fabric_cold_disposition"
      || approval.subject_id !== payload.itemId || approval.requested_by !== payload.owner || approval.approver !== payload.operator
      || jsonMetadata(approval).requestSha256 !== dispositionApprovalBinding(payload)) throw new Error("current canonical owner or exact approval differs");
    return { database, file, identity, work, approval };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* BEGIN itself may have refused. */ }
    database.close();
    throw error;
  }
}

async function itemRows(client: pg.PoolClient, payload: Pick<DispositionPayload, "itemKind" | "itemId" | "recoveryId" | "clusterId">): Promise<{ item: Record<string, unknown>; task: Record<string, unknown>; history: unknown[]; dependencies: Record<string, unknown[]> }> {
  const table = payload.itemKind === "task" ? "fabric_tasks" : "fabric_effect_outbox";
  const result = await client.query(`SELECT row_to_json(t)::jsonb AS item FROM ${table} t WHERE id=$1 FOR UPDATE`, [payload.itemId]);
  const item = result.rows[0]?.item as Record<string, unknown> | undefined;
  if (!item) throw new Error("quarantined item missing");
  const taskResult = payload.itemKind === "task" ? result : await client.query("SELECT row_to_json(t)::jsonb AS item FROM fabric_tasks t WHERE id=$1 FOR UPDATE", [item.task_id]);
  const task = taskResult.rows[0]?.item as Record<string, unknown> | undefined;
  if (!task) throw new Error("quarantined item task missing");
  const column = payload.itemKind === "task" ? "task_id" : "effect_id";
  const historyResult = await client.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${payload.itemKind}_quarantine_history q JOIN fabric_cold_recoveries r USING(recovery_id) WHERE q.${column}=$1 ORDER BY r.generation LIMIT 1001 FOR UPDATE OF q`, [payload.itemId]);
  const history = historyResult.rows.map((row: { item: unknown }) => row.item);
  if (!history.length || history.length > 1000 || !(history[history.length - 1] as Record<string, unknown>).recovery_id
    || (history[history.length - 1] as Record<string, unknown>).recovery_id !== payload.recoveryId) throw new Error("current quarantine history differs");
  const dependencies: Record<string, unknown[]> = {};
  for (const [kind, sql] of [
    ["attempts", "SELECT row_to_json(a)::jsonb AS item FROM fabric_attempts a WHERE task_id=$1 ORDER BY id LIMIT 1001 FOR UPDATE"],
    ["runs", "SELECT row_to_json(r)::jsonb AS item FROM fabric_runs r WHERE task_id=$1 ORDER BY id LIMIT 1001 FOR UPDATE"],
    ["effects", "SELECT row_to_json(e)::jsonb AS item FROM fabric_effect_outbox e WHERE task_id=$1 ORDER BY id LIMIT 1001 FOR UPDATE"],
    ["artifacts", "SELECT row_to_json(a)::jsonb AS item FROM fabric_artifacts a WHERE task_id=$1 ORDER BY id LIMIT 1001 FOR UPDATE"],
    ["alarms", "SELECT row_to_json(a)::jsonb AS item FROM fabric_alarm_outbox a JOIN fabric_health_findings f ON f.id=a.finding_id WHERE f.scope_id IN ($1,$2,$3,$4) OR f.scope_id IN (SELECT id::text FROM fabric_attempts WHERE task_id=$1::uuid) OR f.scope_id IN (SELECT id::text FROM fabric_runs WHERE task_id=$1::uuid) OR f.scope_id IN (SELECT id::text FROM fabric_effect_outbox WHERE task_id=$1::uuid) ORDER BY a.id LIMIT 1001 FOR UPDATE OF a"],
  ] as const) {
    const rows = await client.query(sql, kind === "alarms" ? [task.id, task.queue_name, task.provider, payload.clusterId] : [task.id]);
    if (rows.rows.length > 1000) throw new Error("disposition dependency bound exceeded");
    dependencies[kind] = rows.rows.map((row: { item: unknown }) => row.item);
  }
  return { item, task, history, dependencies };
}

type ContextProof = { file: string; identity: Stats; sha256: string };
function contextBytes(proof: ContextProof): void {
  sameFile(proof.file, proof.identity);
  if (lstatSync(proof.file).size > 4_194_304 || fileHash(proof.file) !== proof.sha256) throw new Error("original immutable context receipt changed");
}
function verifyAssociation(authority: Pick<Authority, "work" | "database">, payload: Pick<DispositionPayload, "contextSha256" | "owner">, task: Record<string, unknown>, history: unknown[]): ContextProof {
  const bindingSchema = z.object({ schemaVersion: z.literal("execution-fabric-original-task-binding/v1"),
    taskId: uuid, contextSha256: hash, requestHash: hash, developmentPolicyFingerprint: hash,
    contextReceiptUri: z.string().min(1), contextReceiptSha256: hash,
    configFingerprint: hash, namespace: text, queue: text, taskType: text, provider: text }).strict();
  const binding = bindingSchema.parse(jsonMetadata(authority.work).executionFabricBinding);
  if (binding.taskId !== task.id || binding.contextSha256 !== payload.contextSha256
    || binding.requestHash !== task.request_hash || binding.configFingerprint !== task.config_fingerprint
    || binding.namespace !== task.namespace || binding.queue !== task.queue_name
    || binding.taskType !== task.task_type || binding.provider !== task.provider) throw new Error("original canonical task association unavailable");
  const firstHold = Date.parse(String((history[0] as Record<string, unknown>)?.created_at));
  const records = authority.database.prepare("SELECT actor,changed_at,receipt_ref,metadata_json FROM work_item_history WHERE work_item_id=? ORDER BY id LIMIT 1001").all(authority.work.id as string);
  if (!Number.isFinite(firstHold) || records.length > 1000 || !records.some((row) => {
    const captured = Date.parse(String(row.changed_at));
    return row.actor === payload.owner && row.receipt_ref === "fabric-task:" + task.id
      && Number.isFinite(captured) && captured < firstHold
      && digest(jsonMetadata(row as Record<string, unknown>).executionFabricBinding) === digest(binding);
  })) throw new Error("original pre-recovery owner association history unavailable");
  const uri = new URL(binding.contextReceiptUri);
  if (uri.protocol !== "file:" || uri.hostname) throw new Error("original context receipt authority unavailable");
  const file = safeFile(fileURLToPath(uri));
  if (pathToFileURL(file).href !== binding.contextReceiptUri) throw new Error("original context URI is not canonical");
  const proof = { file, identity: lstatSync(file), sha256: binding.contextReceiptSha256 };
  contextBytes(proof);
  const reference = authority.database.prepare("SELECT * FROM artifact_references WHERE uri=? AND content_sha256=?").get(binding.contextReceiptUri, binding.contextReceiptSha256);
  const registered = Date.parse(String(reference?.created_at));
  if (!reference || reference.source_ref !== authority.work.id || reference.classification !== "internal"
    || !Number.isFinite(registered) || registered >= firstHold) throw new Error("actual registered original context reference unavailable");
  const receipt = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
  if (receipt.schema !== "development-effective-policies/v1" || receipt.domain !== authority.work.domain
    || receipt.project !== authority.work.project || receipt.fingerprint !== binding.developmentPolicyFingerprint) throw new Error("original policy/context receipt identity differs");
  const selectionSchema = z.object({ schema: z.literal("development-context-selection/v1"),
    trigger: z.literal("ticket-comment"), output_type: z.literal("planning-evidence"),
    policy_fingerprint: hash, selection: z.record(z.unknown()), context_documents: z.array(z.record(z.unknown())),
    rules_engine_context: z.record(z.unknown()).optional(), content_sha256: hash }).strict();
  const selection = selectionSchema.parse(receipt.context_selection);
  const inputs = selection.selection;
  for (const field of ["touched_paths", "subjects", "rulebook_ids"] as const) {
    const entries = inputs[field];
    if (!Array.isArray(entries) || entries.some((entry) => typeof entry !== "string" || !entry)
      || canonical(entries) !== canonical([...new Set(entries)].sort())) throw new Error("original frozen selection inputs differ");
  }
  if (!Array.isArray(inputs.selected_documents)) throw new Error("original frozen document provenance unavailable");
  const refs = new Set<string>();
  for (const document of inputs.selected_documents) {
    const parsed = z.object({ source_ref: z.string(), sha256: hash, selectors: z.record(z.unknown()) }).passthrough().parse(document);
    refs.add(parsed.source_ref);
  }
  for (const document of selection.context_documents) {
    if (typeof document.id !== "string" || !Array.isArray(document.source_refs)
      || !document.source_refs.some((ref) => refs.has(String(ref)))) throw new Error("original frozen context document provenance unavailable");
  }
  // Specialized Rules Engine kits require their existing qualified validator;
  // this bounded actor cannot substitute a generic mapping as that authority.
  if (selection.rules_engine_context !== undefined) throw new Error("specialized original context verifier unavailable");
  const { content_sha256: contextHash, ...body } = selection;
  // The existing context assembler uses Python json.dumps(ensure_ascii=True).
  // Preserve that historical content hash rather than relabel it with cold JSON.
  const serialized = canonical(body).replace(/[\u007f-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  if (contextHash !== payload.contextSha256 || createHash("sha256").update(serialized).digest("hex") !== contextHash) throw new Error("original frozen context hash differs");
  return proof;
}

function currentExecutionPolicy(policy: z.infer<typeof coldPolicySchema>, payload: Pick<DispositionPayload, "executionPolicySha256" | "configFingerprint">): PolicyManager {
  const file = safeFile(policy.selectiveDisposition!.executionPolicyFile!);
  if (fileHash(file) !== payload.executionPolicySha256) throw new Error("execution policy loaded bytes differ");
  const manager = new PolicyManager(file, "canonical-policy-schema-in-source");
  manager.assertOperational();
  if (manager.snapshot().appliedFingerprint !== payload.configFingerprint || fileHash(file) !== payload.executionPolicySha256) throw new Error("applied execution policy differs");
  return manager;
}
async function decisionHistory(client: pg.PoolClient, payload: Pick<DispositionPayload, "itemKind" | "itemId">): Promise<Record<string, unknown>[]> {
  const decisions = await client.query("SELECT d.*,e.data AS event_data FROM fabric_cold_dispositions d LEFT JOIN fabric_events e ON e.event_id=(d.receipt->>'eventId')::uuid AND e.aggregate_type='cold_disposition' AND e.aggregate_id=d.item_id::text AND e.event_type='cold_disposition.applied' WHERE d.item_kind=$1 AND d.item_id=$2 ORDER BY d.sequence LIMIT 1001", [payload.itemKind, payload.itemId]);
  if (decisions.rows.length > 1000) throw new Error("disposition history bound exceeded");
  const predecessors = new Map<string, string>();
  return decisions.rows.map((row) => {
    const receipt = row.receipt as DispositionReceipt;
    if (digest(receipt) !== row.receipt_sha256 || digest(row.event_data) !== row.receipt_sha256
      || receipt.recoveryId !== row.recovery_id || receipt.itemId !== payload.itemId || receipt.itemKind !== payload.itemKind
      || receipt.generation !== Number(row.generation) || receipt.fabricEpoch !== Number(row.fabric_epoch)
      || receipt.disposition !== row.disposition
      || receipt.released !== false || row.releases_quarantine !== false
      || receipt.predecessorSha256 !== (predecessors.get(String(row.recovery_id)) ?? null)) throw new Error("immutable disposition history proof differs");
    const entry = z.object({ sequence: counter, recoveryId: uuid, generation: counter, fabricEpoch: counter,
      disposition: z.enum(["hold", "task_cancel"]), receiptSha256: hash, predecessorSha256: hash.nullable(), eventId: uuid }).strict().parse({
      sequence: Number(row.sequence), recoveryId: row.recovery_id, generation: Number(row.generation), fabricEpoch: Number(row.fabric_epoch),
      disposition: row.disposition, receiptSha256: row.receipt_sha256, predecessorSha256: receipt.predecessorSha256, eventId: receipt.eventId });
    predecessors.set(entry.recoveryId, entry.receiptSha256);
    return entry;
  });
}

export async function runColdDisposition(pool: pg.Pool, value: unknown, policyValue: unknown, anchorValue: unknown): Promise<{ receipt: DispositionReceipt; replayed: boolean; held: boolean; inspected: false }> {
  const request = dispositionRequestSchema.parse(value), payload = request.payload;
  const policy = coldPolicySchema.parse(policyValue), selected = policy.selectiveDisposition;
  const anchor = coldAnchorSchema.parse(anchorValue), requestHash = digest(payload);
  if (!policy.enabled || !selected?.enabled || !selected.authority || !selected.acceptedPolicySha256
    || !selected.sourceRelease || payload.policySha256 !== digest(policy)
    || payload.acceptedPolicySha256 !== selected.acceptedPolicySha256 || payload.sourceRelease !== selected.sourceRelease
    || payload.clusterId !== policy.clusterId || !policy.allowedHosts.includes(payload.targetHost)
    || anchor.pending !== null || anchor.clusterId !== payload.clusterId || anchor.leader !== payload.targetHost
    || anchor.generation !== payload.generation || anchor.highestEpoch !== payload.fabricEpoch) throw new Error("current accepted disposition policy or anchor differs");
  const key = createPublicKey(policy.recoveryPublicKeyPem), signature = Buffer.from(request.signature, "base64");
  if (key.asymmetricKeyType !== "ed25519" || signature.length !== 64 || !verify(null, Buffer.from(canonical(payload)), key, signature)) throw new Error("disposition signature refused");
  if ((payload.itemKind === "effect" && payload.disposition !== "hold") || (payload.itemKind === "task" && !["hold", "task_cancel", "task_requeue"].includes(payload.disposition))) throw new Error("qualified provider outcome verifier unavailable");
  // The only qualified local handler is the single max_attempts=1 cold canary.
  // Its producer refuses generic admission and acceptance requires its success.
  // Do not manufacture an eligible extra row to claim a requeue capability.
  if (payload.disposition === "task_requeue") throw new Error("genuine supported positive requeue admission unavailable");
  const authority = acquireAuthority(policy, payload);
  let client: pg.PoolClient | undefined;
  try {
    client = await pool.connect();
    await client.query("BEGIN");
    await client.query("SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='5s'");
    await client.query("SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-cold-recovery'))");
    const identity = await client.query("SELECT system_identifier::text AS system_id FROM pg_control_system()");
    const durability = await client.query("SELECT pg_is_in_recovery() AS in_recovery,current_setting('fsync') AS fsync,current_setting('full_page_writes') AS full_page_writes,current_setting('archive_mode') AS archive_mode,current_setting('synchronous_commit') AS synchronous_commit,current_setting('synchronous_standby_names') AS synchronous_standby_names");
    const durable = durability.rows[0];
    if (identity.rows[0]?.system_id !== payload.pgSystemId || !durable || durable.in_recovery !== false || durable.fsync !== "on"
      || durable.full_page_writes !== "on" || durable.archive_mode !== "on" || !["on", "local"].includes(durable.synchronous_commit)
      || durable.synchronous_standby_names !== "") throw new Error("target PostgreSQL durability or identity unqualified");
    const state = (await client.query("SELECT * FROM fabric_state WHERE singleton=true FOR UPDATE")).rows[0];
    const recovery = (await client.query("SELECT * FROM fabric_cold_recoveries WHERE recovery_id=$1 FOR UPDATE", [payload.recoveryId])).rows[0];
    if (!state || !recovery || state.cold_recovery_phase !== "ACCEPTED" || recovery.phase !== "ACCEPTED"
      || state.cold_recovery_id !== payload.recoveryId || Number(state.cold_recovery_generation) !== payload.generation
      || Number(state.current_epoch) !== payload.fabricEpoch || state.leader_host_id !== payload.targetHost
      || state.leadership_cluster_id !== payload.clusterId || state.policy_fingerprint !== payload.configFingerprint
      || recovery.plan_sha256 !== payload.planSha256 || digest(recovery.plan) !== payload.planSha256
      || digest(recovery.receipts?.accept) !== payload.acceptedReceiptSha256
      || anchor.lastReceiptSha256 !== payload.acceptedReceiptSha256) throw new Error("actual accepted recovery or current authority differs");
    acceptedReceipt(recovery.receipts.accept, payload, payload.planSha256);
    const plan = coldPlanSchema.parse(recovery.plan);
    if (plan.policySha256 !== payload.acceptedPolicySha256 || plan.generation !== payload.generation || plan.nextEpoch !== payload.fabricEpoch
      || Number(recovery.generation) !== plan.generation || Number(recovery.next_epoch) !== plan.nextEpoch
      || recovery.target_host !== plan.targetHost || recovery.source_host !== plan.sourceHost
      || plan.newPgSystemId !== payload.pgSystemId || plan.clusterId !== payload.clusterId || plan.targetHost !== payload.targetHost
      || anchor.publicKeySha256 !== plan.newPublicKeySha256) throw new Error("accepted plan identity differs");
    const operationKey = "cold-disposition:" + payload.idempotencyKey;
    const existing = (await client.query("SELECT * FROM fabric_cold_dispositions WHERE idempotency_key=$1", [operationKey])).rows[0];
    if (existing) {
      if (existing.request_sha256 !== requestHash || existing.recovery_id !== payload.recoveryId
        || existing.item_kind !== payload.itemKind || existing.item_id !== payload.itemId
        || digest(existing.receipt) !== existing.receipt_sha256) throw new Error("disposition idempotency conflicts");
      const events = await client.query("SELECT data FROM fabric_events WHERE event_id=$1 AND aggregate_type='cold_disposition' AND aggregate_id=$2 AND event_type='cold_disposition.applied'", [existing.receipt.eventId, payload.itemId]);
      if (events.rows.length !== 1 || digest(events.rows[0].data) !== existing.receipt_sha256) throw new Error("committed disposition event unavailable");
      const rows = await itemRows(client, payload);
      const context = verifyAssociation(authority, payload, rows.task, rows.history);
      const executionPolicy = currentExecutionPolicy(policy, payload);
      const latest = (await client.query("SELECT receipt_sha256 FROM fabric_cold_dispositions WHERE recovery_id=$1 AND item_kind=$2 AND item_id=$3 ORDER BY sequence DESC LIMIT 1", [payload.recoveryId, payload.itemKind, payload.itemId])).rows[0];
      if (latest?.receipt_sha256 !== existing.receipt_sha256 || digest(rows.item) !== existing.receipt.afterSha256
        || digest(rows.history) !== payload.historySha256 || digest(rows.dependencies) !== payload.dependencySha256) throw new Error("committed disposition current readback differs");
      await decisionHistory(client, payload);
      const held = await client.query(`SELECT 1 FROM fabric_cold_${payload.itemKind}_quarantine WHERE ${payload.itemKind}_id=$1`, [payload.itemId]);
      if (!held.rowCount || existing.receipt.released !== false) throw new Error("committed disposition quarantine differs");
      sameAuthorityFile(authority.file, authority.identity);
      contextBytes(context);
      executionPolicy.assertOperational();
      if (fileHash(executionPolicy.source) !== payload.executionPolicySha256) throw new Error("execution policy bytes changed during replay");
      await client.query("COMMIT");
      return { receipt: existing.receipt, replayed: true, held: true, inspected: false };
    }
    window(payload, policy.maxApprovalSeconds);
    const approvalExpiry = Date.parse(String(authority.approval.expires_at));
    const decided = Date.parse(String(authority.approval.decided_at)), requested = Date.parse(String(authority.approval.requested_at));
    if (![approvalExpiry, decided, requested].every(Number.isFinite) || Date.now() >= approvalExpiry
      || requested > decided || decided > Date.now()) throw new Error("canonical approval expired or undecided");
    const rows = await itemRows(client, payload);
    const context = verifyAssociation(authority, payload, rows.task, rows.history);
    if (digest(rows.item) !== payload.itemSha256 || digest(rows.history) !== payload.historySha256
      || digest(rows.dependencies) !== payload.dependencySha256) throw new Error("quarantine item or dependency bytes changed");
    const latestHold = rows.history[rows.history.length - 1] as Record<string, unknown>;
    if (latestHold.reason !== (payload.itemKind === "task" ? "post_snapshot_delivery_unknown" : "post_snapshot_provider_delivery_unknown")) throw new Error("unrelated quarantine reason remains held");
    const activeHold = await client.query(`SELECT 1 FROM fabric_cold_${payload.itemKind}_quarantine WHERE ${payload.itemKind}_id=$1`, [payload.itemId]);
    if (payload.disposition !== "hold" && !activeHold.rowCount) throw new Error("item is already released; fresh disposition refuses");
    const liveAttempt = rows.dependencies.attempts!.some((row) => (row as Record<string, unknown>).status === "running");
    if (liveAttempt || rows.dependencies.runs!.some((row) => (row as Record<string, unknown>).status === "running")
      || (rows.item.claim_expires_at && Date.parse(String(rows.item.claim_expires_at)) > Date.now())) throw new Error("item has active execution or claim");
    const prior = (await client.query("SELECT receipt_sha256 FROM fabric_cold_dispositions WHERE recovery_id=$1 AND item_kind=$2 AND item_id=$3 ORDER BY sequence DESC LIMIT 1", [payload.recoveryId, payload.itemKind, payload.itemId])).rows[0];
    await decisionHistory(client, payload);
    if ((prior?.receipt_sha256 ?? null) !== payload.priorDispositionSha256) throw new Error("disposition predecessor conflicts");
    const released = false;
    const executionPolicy = currentExecutionPolicy(policy, payload);
    if (payload.disposition === "task_cancel") {
      if (!["finished", "documented", "archived"].includes(String(authority.work.state))
        || !["queued", "running", "cancelled"].includes(String(rows.task.status))) throw new Error("owner terminal cancellation unavailable");
      if (payload.reason !== "owner_cancelled") throw new Error("disposition reason differs");
    } else if (payload.reason !== "outcome_unknown") throw new Error("held disposition reason differs");
    sameAuthorityFile(authority.file, authority.identity);
    contextBytes(context);
    executionPolicy.assertOperational();
    if (fileHash(executionPolicy.source) !== payload.executionPolicySha256) throw new Error("execution policy bytes changed before commit");
    let after = rows.item;
    if (payload.disposition === "task_cancel") {
      const update = "UPDATE fabric_tasks t SET status='cancelled',completed_at=COALESCE(completed_at,now()),delivery_published_at=NULL,updated_at=now() WHERE id=$1 RETURNING row_to_json(t)::jsonb AS item";
      after = (await client.query(update, [payload.itemId])).rows[0]?.item;
      if (!after || after.id !== payload.itemId || after.attempt_count !== rows.item.attempt_count) throw new Error("task disposition readback differs");
    }
    const receipt: DispositionReceipt = { schemaVersion: "execution-fabric-cold-disposition-receipt/v1",
      requestSha256: requestHash, recoveryId: payload.recoveryId, generation: payload.generation, fabricEpoch: payload.fabricEpoch,
      clusterId: payload.clusterId, targetHost: payload.targetHost, pgSystemId: payload.pgSystemId,
      planSha256: payload.planSha256, configFingerprint: payload.configFingerprint,
      acceptedReceiptSha256: payload.acceptedReceiptSha256, executionPolicySha256: payload.executionPolicySha256,
      itemKind: payload.itemKind, itemId: payload.itemId, disposition: payload.disposition, released,
      beforeSha256: payload.itemSha256, afterSha256: digest(after), historySha256: payload.historySha256,
      dependencySha256: payload.dependencySha256, owner: payload.owner, operator: payload.operator,
      contextSha256: payload.contextSha256, workItemSha256: payload.workItemSha256,
      approvalSha256: payload.approvalSha256, policySha256: payload.policySha256,
      predecessorSha256: payload.priorDispositionSha256, eventId: randomUUID() };
    await client.query("INSERT INTO fabric_cold_dispositions(recovery_id,generation,fabric_epoch,cluster_id,target_host,pg_system_id,plan_sha256,config_fingerprint,accepted_receipt,item_kind,item_id,idempotency_key,request_sha256,predecessor_sha256,disposition,releases_quarantine,receipt_sha256,receipt) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb)",
      [payload.recoveryId, payload.generation, payload.fabricEpoch, payload.clusterId, payload.targetHost, payload.pgSystemId,
        payload.planSha256, payload.configFingerprint, JSON.stringify(recovery.receipts.accept), payload.itemKind, payload.itemId,
        operationKey, requestHash, payload.priorDispositionSha256, payload.disposition, released, digest(receipt), JSON.stringify(receipt)]);
    await client.query("INSERT INTO fabric_events(event_id,aggregate_type,aggregate_id,event_type,fabric_epoch,data) VALUES($1,'cold_disposition',$2,'cold_disposition.applied',$3,$4::jsonb)", [receipt.eventId, payload.itemId, payload.fabricEpoch, JSON.stringify(receipt)]);
    const committedRows = await itemRows(client, payload);
    const emitted = await client.query("SELECT data FROM fabric_events WHERE event_id=$1 AND aggregate_type='cold_disposition' AND aggregate_id=$2 AND event_type='cold_disposition.applied'", [receipt.eventId, payload.itemId]);
    if (digest(committedRows.item) !== receipt.afterSha256 || digest(committedRows.history) !== payload.historySha256
      || digest(committedRows.dependencies) !== payload.dependencySha256 || emitted.rows.length !== 1
      || digest(emitted.rows[0].data) !== digest(receipt)) throw new Error("disposition immutable dependency or event readback differs");
    const held = await client.query(`SELECT 1 FROM fabric_cold_${payload.itemKind}_quarantine WHERE ${payload.itemKind}_id=$1`, [payload.itemId]);
    if (Boolean(held.rowCount) === released) throw new Error("disposition eligibility readback differs");
    sameAuthorityFile(authority.file, authority.identity);
    // A slow PG transaction cannot carry an expired authority across commit.
    contextBytes(context);
    executionPolicy.assertOperational();
    if (fileHash(executionPolicy.source) !== payload.executionPolicySha256) throw new Error("execution policy bytes changed before commit");
    window(payload, policy.maxApprovalSeconds);
    if (Date.now() >= approvalExpiry) throw new Error("canonical approval expired before commit");
    await client.query("COMMIT");
    return { receipt, replayed: false, held: !released, inspected: false };
  } catch (error) {
    if (client) await client.query("ROLLBACK");
    throw error;
  } finally {
    client?.release();
    try { authority.database.exec("ROLLBACK"); } finally { authority.database.close(); }
  }
}

const inspectionPayloadSchema = dispositionPayloadSchema.pick({ recoveryId: true, generation: true, fabricEpoch: true,
  clusterId: true, targetHost: true, itemKind: true, itemId: true, workItemId: true, owner: true,
  operator: true, contextSha256: true, policySha256: true, issuedAt: true, expiresAt: true }).extend({
  schemaVersion: z.literal("execution-fabric-cold-disposition-inspection/v1"),
}).strict();
export const dispositionInspectionSchema = z.object({ payload: inspectionPayloadSchema,
  signature: z.string().length(88).regex(/^[A-Za-z0-9+/]{86}==$/) }).strict();

/** Actual snapshot references for constructing an approval. No item/event write. */
export async function inspectColdDisposition(pool: pg.Pool, value: unknown, policyValue: unknown, anchorValue: unknown): Promise<Record<string, unknown>> {
  const request = dispositionInspectionSchema.parse(value), payload = request.payload;
  const policy = coldPolicySchema.parse(policyValue), selected = policy.selectiveDisposition;
  const anchor = coldAnchorSchema.parse(anchorValue);
  if (!policy.enabled || !selected?.enabled || !selected.authority || !selected.acceptedPolicySha256
    || payload.policySha256 !== digest(policy) || payload.clusterId !== policy.clusterId
    || !policy.allowedHosts.includes(payload.targetHost) || anchor.pending !== null
    || anchor.clusterId !== payload.clusterId || anchor.leader !== payload.targetHost
    || anchor.generation !== payload.generation || anchor.highestEpoch !== payload.fabricEpoch) throw new Error("inspection current authority differs");
  const publicKey = createPublicKey(policy.recoveryPublicKeyPem), signature = Buffer.from(request.signature, "base64");
  if (publicKey.asymmetricKeyType !== "ed25519" || signature.length !== 64 || !verify(null, Buffer.from(canonical(payload)), publicKey, signature)) throw new Error("inspection signature refused");
  const now = Date.now(), start = Date.parse(payload.issuedAt), end = Date.parse(payload.expiresAt);
  if (!(start <= now && now < end && end - start > 0 && end - start <= policy.maxApprovalSeconds * 1000)) throw new Error("inspection window refused");
  const file = safeFile(selected.authority.databasePath), identity = lstatSync(file);
  if (identity.mode & 0o077) throw new Error("canonical inspection authority must be private");
  const database = existingAuthorityDatabase(file);
  let client: pg.PoolClient | undefined;
  try {
    database.exec("PRAGMA busy_timeout=5000; BEGIN IMMEDIATE");
    sameAuthorityFile(file, identity);
    qualifiedAuthoritySchema(database);
    const work = database.prepare("SELECT * FROM work_items WHERE id=?").get(payload.workItemId) as Record<string, unknown> | undefined;
    if (!work || work.owner !== payload.owner || work.domain !== selected.authority.domain || work.project !== selected.authority.project) throw new Error("inspection actual owner differs");
    client = await pool.connect();
    await client.query("BEGIN");
    await client.query("SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='5s'");
    await client.query("SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-cold-recovery'))");
    const state = (await client.query("SELECT * FROM fabric_state WHERE singleton=true FOR UPDATE")).rows[0];
    const recovery = (await client.query("SELECT * FROM fabric_cold_recoveries WHERE recovery_id=$1 FOR UPDATE", [payload.recoveryId])).rows[0];
    if (!state || !recovery || state.cold_recovery_phase !== "ACCEPTED" || recovery.phase !== "ACCEPTED"
      || state.cold_recovery_id !== payload.recoveryId || Number(state.cold_recovery_generation) !== payload.generation
      || Number(state.current_epoch) !== payload.fabricEpoch || state.leader_host_id !== payload.targetHost
      || state.leadership_cluster_id !== payload.clusterId || digest(recovery.plan) !== recovery.plan_sha256
      || digest(recovery.receipts?.accept) !== anchor.lastReceiptSha256) throw new Error("inspection accepted recovery differs");
    const plan = coldPlanSchema.parse(recovery.plan);
    acceptedReceipt(recovery.receipts.accept, payload, recovery.plan_sha256);
    const pgIdentity = (await client.query("SELECT system_identifier::text AS system_id FROM pg_control_system()")).rows[0]?.system_id;
    if (plan.policySha256 !== selected.acceptedPolicySha256 || plan.clusterId !== payload.clusterId
      || plan.targetHost !== payload.targetHost || plan.generation !== payload.generation || plan.nextEpoch !== payload.fabricEpoch
      || Number(recovery.generation) !== plan.generation || Number(recovery.next_epoch) !== plan.nextEpoch
      || recovery.target_host !== plan.targetHost || recovery.source_host !== plan.sourceHost
      || pgIdentity !== plan.newPgSystemId || anchor.publicKeySha256 !== plan.newPublicKeySha256) throw new Error("inspection plan identity differs");
    // itemRows only consumes these identity selectors; no approval boolean or
    // supplied digest is used to certify an inspection result.
    const rows = await itemRows(client, payload);
    const context = verifyAssociation({ work, database }, payload, rows.task, rows.history);
    const prior = (await client.query("SELECT receipt_sha256 FROM fabric_cold_dispositions WHERE recovery_id=$1 AND item_kind=$2 AND item_id=$3 ORDER BY sequence DESC LIMIT 1", [payload.recoveryId, payload.itemKind, payload.itemId])).rows[0];
    const executionFile = safeFile(selected.executionPolicyFile!);
    const decisions = await decisionHistory(client, payload);
    const executionIdentity = lstatSync(executionFile);
    const executionPolicySha256 = fileHash(executionFile);
    // The single successful canary was created after the first hold. It cannot
    // have this required pre-hold original association and quarantine history.
    // No genuine held item has a qualified positive local requeue contract.
    sameAuthorityFile(file, identity);
    contextBytes(context);
    sameFile(executionFile, executionIdentity);
    if (fileHash(executionFile) !== executionPolicySha256) throw new Error("inspection execution policy changed during readback");
    if (Date.now() >= end) throw new Error("inspection authority expired during readback");
    await client.query("ROLLBACK");
    return { schemaVersion: "execution-fabric-cold-disposition-inspection-receipt/v1",
      recoveryId: payload.recoveryId, generation: payload.generation, fabricEpoch: payload.fabricEpoch,
      clusterId: payload.clusterId, targetHost: payload.targetHost, pgSystemId: pgIdentity,
      planSha256: recovery.plan_sha256, acceptedReceiptSha256: anchor.lastReceiptSha256,
      acceptedPolicySha256: plan.policySha256, policySha256: payload.policySha256,
      configFingerprint: state.policy_fingerprint, executionPolicySha256, sourceRelease: selected.sourceRelease,
      itemKind: payload.itemKind, itemId: payload.itemId, itemSha256: digest(rows.item),
      historySha256: digest(rows.history), dependencySha256: digest(rows.dependencies),
      workItemId: payload.workItemId, workItemSha256: digest(work), owner: payload.owner,
      operator: payload.operator, contextSha256: payload.contextSha256,
      priorDispositionSha256: prior?.receipt_sha256 ?? null, routeQualified: false,
      decisionHistory: decisions,
      ownerBlocked: Boolean(work.blocked_reason) || work.state === "blocked",
      dependencyCounts: Object.fromEntries(Object.entries(rows.dependencies).map(([kind, entries]) => [kind, entries.length])),
      providerOutcomeVerifier: "unavailable", requeueAvailable: false, mutationCount: 0 };
  } catch (error) {
    if (client) await client.query("ROLLBACK");
    throw error;
  } finally {
    client?.release();
    try { database.exec("ROLLBACK"); } catch { /* A refused BEGIN may have no transaction. */ }
    database.close();
  }
}
