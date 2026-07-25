import {
  DynamoDBClient,
  type DynamoDBClientConfig,
} from "@aws-sdk/client-dynamodb";
import {
  DynamoDBDocumentClient,
  GetCommand,
  PutCommand,
  QueryCommand,
  TransactWriteCommand,
} from "@aws-sdk/lib-dynamodb";
import type {
  AuditRecord,
  CandidateRecord,
  ConfigDigestRotationAbortMutation,
  ConfigDigestRotationAbortReceipt,
  ConfigDigestRotationCommitMutation,
  ConfigDigestRotationPreparation,
  ConfigDigestRotationPreparationMutation,
  ConfigDigestRotationReceipt,
  FailbackCommitMutation,
  FailbackPlan,
  LeadershipState,
  PromotionMutation,
} from "./contracts.js";
import {
  ConditionalWriteError,
  type LeaderBaselineUpdate,
  type WitnessStore,
} from "./store.js";

type Item = Record<string, unknown>;

export class DynamoWitnessStore implements WitnessStore {
  private readonly client: DynamoDBDocumentClient;
  private readonly partitionKey: string;

  constructor(
    private readonly tableName: string,
    clusterId: string,
    config: DynamoDBClientConfig,
  ) {
    this.partitionKey = `CLUSTER#${clusterId}`;
    this.client = DynamoDBDocumentClient.from(new DynamoDBClient(config), {
      marshallOptions: { removeUndefinedValues: true },
    });
  }

  private stateKey(): Item {
    return { pk: this.partitionKey, sk: "STATE" };
  }

  private candidateKey(candidate: string): Item {
    return { pk: this.partitionKey, sk: `CANDIDATE#${candidate}` };
  }

  private planKey(tokenHash: string): Item {
    return { pk: this.partitionKey, sk: `PLAN#${tokenHash}` };
  }

  private configRotationKey(rotationId: string): Item {
    return { pk: this.partitionKey, sk: `CONFIG_ROTATION#${rotationId}` };
  }

  private configRotationPreparationKey(rotationId: string): Item {
    return {
      pk: this.partitionKey,
      sk: `CONFIG_ROTATION_PREP#${rotationId}`,
    };
  }

  private configRotationActiveKey(): Item {
    return { pk: this.partitionKey, sk: "CONFIG_ROTATION_ACTIVE" };
  }

  private configRotationAbortKey(rotationId: string): Item {
    return {
      pk: this.partitionKey,
      sk: `CONFIG_ROTATION_ABORT#${rotationId}`,
    };
  }

  private auditItem(audit: AuditRecord): Item {
    return {
      pk: this.partitionKey,
      sk: `AUDIT#${audit.occurredAt}#${audit.auditId}`,
      entity: "audit",
      ...audit,
    };
  }

  private stateItem(state: LeadershipState): Item {
    return {
      ...this.stateKey(),
      entity: "state",
      ...state,
    };
  }

  private candidateItem(candidate: CandidateRecord): Item {
    return {
      ...this.candidateKey(candidate.candidate),
      entity: "candidate",
      ...candidate,
    };
  }

  private planItem(plan: FailbackPlan): Item {
    return {
      ...this.planKey(plan.tokenHash),
      entity: "failback_plan",
      ...plan,
      ttl: plan.expiresAtEpoch,
    };
  }

  private configRotationItem(receipt: ConfigDigestRotationReceipt): Item {
    return {
      ...this.configRotationKey(receipt.rotationId),
      entity: "config_digest_rotation",
      ...receipt,
    };
  }

  private configRotationPreparationItem(
    preparation: ConfigDigestRotationPreparation,
  ): Item {
    return {
      ...this.configRotationPreparationKey(preparation.rotationId),
      entity: "config_digest_rotation_preparation",
      ...preparation,
    };
  }

  private configRotationAbortItem(
    receipt: ConfigDigestRotationAbortReceipt,
  ): Item {
    return {
      ...this.configRotationAbortKey(receipt.rotationId),
      entity: "config_digest_rotation_abort",
      ...receipt,
    };
  }

  private configRotationPreparationFromItem(
    item: Item,
  ): ConfigDigestRotationPreparation {
    return {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotation_prepared",
      rotationId: String(item.rotationId),
      requestDigest: String(item.requestDigest),
      expectedLeader: String(item.expectedLeader),
      expectedEpoch: Number(item.expectedEpoch),
      expectedCurrentDigest: String(item.expectedCurrentDigest),
      candidateDigest: String(item.candidateDigest),
      candidateHosts: Array.isArray(item.candidateHosts)
        ? item.candidateHosts.map(String)
        : [],
      expectedTimelineId: Number(item.expectedTimelineId),
      expectedLeaderWalPosition: Number(item.expectedLeaderWalPosition),
      expectedUpstreamSystemId: String(item.expectedUpstreamSystemId),
      minimumStandbyReplayWalPosition: Number(
        item.minimumStandbyReplayWalPosition,
      ),
      maxReplicaLagBytes: Number(item.maxReplicaLagBytes),
      preparationToken: String(item.preparationToken),
      preparationTokenHash: String(item.preparationTokenHash),
      issuedAt: String(item.issuedAt),
      expiresAt: String(item.expiresAt),
      expiresAtEpoch: Number(item.expiresAtEpoch),
    };
  }

  private conditional(error: unknown, message: string): never {
    if (
      error instanceof Error &&
      (error.name === "TransactionCanceledException" ||
        error.name === "ConditionalCheckFailedException")
    ) {
      throw new ConditionalWriteError(message);
    }
    throw error;
  }

  async initialize(
    state: LeadershipState,
    audit: AuditRecord,
  ): Promise<LeadershipState> {
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              Put: {
                TableName: this.tableName,
                Item: this.stateItem(state),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(audit),
              },
            },
          ],
        }),
      );
      return state;
    } catch (error) {
      if (
        error instanceof Error &&
        (error.name === "TransactionCanceledException" ||
          error.name === "ConditionalCheckFailedException")
      ) {
        return this.getState();
      }
      throw error;
    }
  }

  async ready(): Promise<void> {
    await this.getState();
  }

  async getState(): Promise<LeadershipState> {
    const response = await this.client.send(
      new GetCommand({
        TableName: this.tableName,
        Key: this.stateKey(),
        ConsistentRead: true,
      }),
    );
    if (!response.Item) throw new Error("leadership state is not initialized");
    return {
      currentLeader: String(response.Item.currentLeader),
      fabricEpoch: Number(response.Item.fabricEpoch),
      timelineId: Number(response.Item.timelineId),
      configDigest: String(response.Item.configDigest),
      leaderWalPosition:
        response.Item.leaderWalPosition == null
          ? null
          : Number(response.Item.leaderWalPosition),
      leaderBaselineAt:
        response.Item.leaderBaselineAt == null
          ? null
          : String(response.Item.leaderBaselineAt),
      upstreamSystemId:
        response.Item.upstreamSystemId == null
          ? null
          : String(response.Item.upstreamSystemId),
      updatedAt: String(response.Item.updatedAt),
      fenceDigest: String(response.Item.fenceDigest),
      authorityMode:
        response.Item.authorityMode === "degraded_primary"
          ? "degraded_primary"
          : "synchronous",
      degradedUntil:
        response.Item.degradedUntil == null
          ? null
          : String(response.Item.degradedUntil),
      degradedIncidentDigest:
        response.Item.degradedIncidentDigest == null
          ? null
          : String(response.Item.degradedIncidentDigest),
    };
  }

  async listCandidates(): Promise<CandidateRecord[]> {
    const response = await this.client.send(
      new QueryCommand({
        TableName: this.tableName,
        KeyConditionExpression: "pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues: {
          ":pk": this.partitionKey,
          ":prefix": "CANDIDATE#",
        },
        ConsistentRead: true,
      }),
    );
    return (response.Items ?? []).map((item) => ({
      candidate: String(item.candidate),
      healthy: Boolean(item.healthy),
      inRecovery: Boolean(item.inRecovery),
      timelineId: Number(item.timelineId),
      receiveLsn: String(item.receiveLsn),
      replayLsn: String(item.replayLsn),
      receiveWalPosition: Number(item.receiveWalPosition),
      replayWalPosition: Number(item.replayWalPosition),
      replicaLagBytes: Number(item.replicaLagBytes),
      lagMeasuredAt: String(item.lagMeasuredAt),
      upstreamSystemId: String(item.upstreamSystemId),
      receiverState: item.receiverState as CandidateRecord["receiverState"],
      lastMessageAt: String(item.lastMessageAt),
      configDigest: String(item.configDigest),
      ...(item.policyCandidateDigest == null
        ? {}
        : { policyCandidateDigest: String(item.policyCandidateDigest) }),
      ...(item.policyCandidateObservedAt == null
        ? {}
        : {
            policyCandidateObservedAt: String(
              item.policyCandidateObservedAt,
            ),
          }),
      observedAt: String(item.observedAt),
      observedAtEpoch: Number(item.observedAtEpoch),
    }));
  }

  async putCandidate(
    candidate: CandidateRecord,
    audit: AuditRecord,
    leaderBaseline?: LeaderBaselineUpdate,
  ): Promise<void> {
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
          {
            Put: {
              TableName: this.tableName,
              Item: this.candidateItem(candidate),
            },
          },
          {
            Put: {
              TableName: this.tableName,
              Item: this.auditItem(audit),
            },
          },
          ...(leaderBaseline
            ? [
                {
                  Update: {
                    TableName: this.tableName,
                    Key: this.stateKey(),
                    UpdateExpression:
                      "SET leaderWalPosition=:wal, leaderBaselineAt=:baselineAt, upstreamSystemId=:systemId",
                    ConditionExpression:
                      "currentLeader=:leader AND timelineId=:timeline AND configDigest=:configDigest AND (attribute_not_exists(upstreamSystemId) OR attribute_type(upstreamSystemId,:nullType) OR upstreamSystemId=:systemId) AND (attribute_not_exists(leaderWalPosition) OR attribute_type(leaderWalPosition,:nullType) OR leaderWalPosition <= :wal)",
                    ExpressionAttributeValues: {
                      ":wal": candidate.replayWalPosition,
                      ":baselineAt": candidate.lagMeasuredAt,
                      ":systemId": candidate.upstreamSystemId,
                      ":leader": leaderBaseline.expectedLeader,
                      ":timeline": leaderBaseline.expectedTimelineId,
                      ":configDigest": leaderBaseline.expectedConfigDigest,
                      ":nullType": "NULL",
                    },
                  },
                },
              ]
            : []),
          ],
        }),
      );
    } catch (error) {
      this.conditional(error, "candidate or leader WAL baseline was rejected");
    }
  }

  async getConfigDigestRotation(
    rotationId: string,
  ): Promise<ConfigDigestRotationReceipt | null> {
    const response = await this.client.send(
      new GetCommand({
        TableName: this.tableName,
        Key: this.configRotationKey(rotationId),
        ConsistentRead: true,
      }),
    );
    const item = response.Item;
    if (!item) return null;
    return {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotated",
      rotationId: String(item.rotationId),
      requestDigest: String(item.requestDigest),
      currentLeader: String(item.currentLeader),
      fabricEpoch: Number(item.fabricEpoch),
      previousConfigDigest: String(item.previousConfigDigest),
      configDigest: String(item.configDigest),
      candidateHosts: Array.isArray(item.candidateHosts)
        ? item.candidateHosts.map(String)
        : [],
      preparationTokenHash: String(item.preparationTokenHash),
      committedAt: String(item.committedAt),
    };
  }

  async getConfigDigestRotationAbort(
    rotationId: string,
  ): Promise<ConfigDigestRotationAbortReceipt | null> {
    const response = await this.client.send(
      new GetCommand({
        TableName: this.tableName,
        Key: this.configRotationAbortKey(rotationId),
        ConsistentRead: true,
      }),
    );
    const item = response.Item;
    if (!item) return null;
    return {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotation_aborted",
      rotationId: String(item.rotationId),
      requestDigest: String(item.requestDigest),
      currentLeader: String(item.currentLeader),
      fabricEpoch: Number(item.fabricEpoch),
      configDigest: String(item.configDigest),
      candidateDigest: String(item.candidateDigest),
      evidenceHost: String(item.evidenceHost),
      preparationTokenHash: String(item.preparationTokenHash),
      expiredAt: String(item.expiredAt),
      abortedAt: String(item.abortedAt),
    };
  }

  async getConfigDigestRotationPreparation(
    rotationId: string,
  ): Promise<ConfigDigestRotationPreparation | null> {
    const response = await this.client.send(
      new GetCommand({
        TableName: this.tableName,
        Key: this.configRotationPreparationKey(rotationId),
        ConsistentRead: true,
      }),
    );
    return response.Item
      ? this.configRotationPreparationFromItem(response.Item)
      : null;
  }

  async listConfigDigestRotationPreparations(): Promise<
    ConfigDigestRotationPreparation[]
  > {
    const response = await this.client.send(
      new QueryCommand({
        TableName: this.tableName,
        KeyConditionExpression: "pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues: {
          ":pk": this.partitionKey,
          ":prefix": "CONFIG_ROTATION_PREP#",
        },
        ConsistentRead: true,
      }),
    );
    return (response.Items ?? []).map((item) =>
      this.configRotationPreparationFromItem(item),
    );
  }

  async prepareConfigDigestRotation(
    mutation: ConfigDigestRotationPreparationMutation,
  ): Promise<ConfigDigestRotationPreparation> {
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.stateKey(),
                ConditionExpression:
                  "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND configDigest = :expectedCurrentDigest AND timelineId = :expectedTimelineId AND leaderWalPosition = :expectedLeaderWal AND upstreamSystemId = :expectedSystemId AND leaderBaselineAt >= :baselineFreshAfter",
                ExpressionAttributeValues: {
                  ":expectedLeader": mutation.expectedLeader,
                  ":expectedEpoch": mutation.expectedEpoch,
                  ":expectedCurrentDigest": mutation.expectedCurrentDigest,
                  ":expectedTimelineId": mutation.expectedTimelineId,
                  ":expectedLeaderWal": mutation.expectedLeaderWalPosition,
                  ":expectedSystemId": mutation.expectedUpstreamSystemId,
                  ":baselineFreshAfter": new Date(
                    mutation.leaderBaselineFreshAfterEpoch * 1000,
                  ).toISOString(),
                },
              },
            },
            ...mutation.candidates.map((candidate) => {
              const standbyLagCondition = candidate.inRecovery
                ? " AND replicaLagBytes <= :maxLag"
                : "";
              return {
                ConditionCheck: {
                  TableName: this.tableName,
                  Key: this.candidateKey(candidate.candidate),
                  ConditionExpression:
                    "attribute_exists(candidate) AND healthy = :healthy AND inRecovery = :inRecovery AND receiverState = :receiverState AND observedAtEpoch >= :freshAfter AND lagMeasuredAt >= :freshAfterIso AND lastMessageAt >= :receiverFreshAfterIso AND configDigest = :expectedCurrentDigest AND policyCandidateDigest = :candidateDigest AND policyCandidateObservedAt >= :policyFreshAfterIso AND timelineId = :expectedTimelineId AND upstreamSystemId = :expectedSystemId AND replayWalPosition >= :minimumReplayWal" +
                    standbyLagCondition,
                  ExpressionAttributeValues: {
                    ":healthy": true,
                    ":inRecovery": candidate.inRecovery,
                    ":receiverState": candidate.receiverState,
                    ":freshAfter": mutation.candidateFreshAfterEpoch,
                    ":freshAfterIso": new Date(
                      mutation.candidateFreshAfterEpoch * 1000,
                    ).toISOString(),
                    ":receiverFreshAfterIso": new Date(
                      mutation.receiverFreshAfterEpoch * 1000,
                    ).toISOString(),
                    ":candidateDigest": mutation.candidateDigest,
                    ":expectedCurrentDigest": mutation.expectedCurrentDigest,
                    ":policyFreshAfterIso": new Date(
                      mutation.policyCandidateFreshAfterEpoch * 1000,
                    ).toISOString(),
                    ":expectedTimelineId": mutation.expectedTimelineId,
                    ":expectedSystemId": mutation.expectedUpstreamSystemId,
                    ":minimumReplayWal": candidate.minimumReplayWalPosition,
                    ...(candidate.inRecovery
                      ? { ":maxLag": mutation.maxReplicaLagBytes }
                      : {}),
                  },
                },
              };
            }),
            {
              Put: {
                TableName: this.tableName,
                Item: {
                  ...this.configRotationActiveKey(),
                  entity: "config_digest_rotation_active",
                  rotationId: mutation.preparation.rotationId,
                  requestDigest: mutation.preparation.requestDigest,
                  createdAt: mutation.preparation.issuedAt,
                },
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.configRotationPreparationItem(
                  mutation.preparation,
                ),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(mutation.audit),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
          ],
        }),
      );
      return mutation.preparation;
    } catch (error) {
      this.conditional(
        error,
        "configuration digest rotation preparation conditions failed",
      );
    }
  }

  async commitConfigDigestRotation(
    mutation: ConfigDigestRotationCommitMutation,
  ): Promise<ConfigDigestRotationReceipt> {
    if (
      mutation.commitCandidate.candidate ===
        mutation.preparation.expectedLeader ||
      !mutation.preparation.candidateHosts.includes(
        mutation.commitCandidate.candidate,
      )
    ) {
      throw new ConditionalWriteError(
        "configuration digest rotation commit requires a configured non-leader candidate",
      );
    }
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              Update: {
                TableName: this.tableName,
                Key: this.stateKey(),
                UpdateExpression:
                  "SET configDigest = :candidateDigest, updatedAt = :updatedAt",
                ConditionExpression:
                  "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND configDigest = :expectedCurrentDigest",
                ExpressionAttributeValues: {
                  ":candidateDigest": mutation.preparation.candidateDigest,
                  ":updatedAt": mutation.nextState.updatedAt,
                  ":expectedLeader": mutation.preparation.expectedLeader,
                  ":expectedEpoch": mutation.preparation.expectedEpoch,
                  ":expectedCurrentDigest":
                    mutation.preparation.expectedCurrentDigest,
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(
                  mutation.commitCandidate.candidate,
                ),
                ConditionExpression:
                  "attribute_exists(candidate) AND healthy = :healthy AND inRecovery = :inRecovery AND receiverState = :streaming AND observedAtEpoch >= :freshAfter AND lagMeasuredAt >= :freshAfterIso AND lastMessageAt >= :receiverFreshAfterIso AND configDigest = :candidateDigest AND timelineId = :expectedTimelineId AND upstreamSystemId = :expectedSystemId AND replayWalPosition >= :minimumReplayWal AND replicaLagBytes <= :maxLag",
                ExpressionAttributeValues: {
                  ":healthy": true,
                  ":inRecovery": true,
                  ":streaming": "streaming",
                  ":freshAfter": mutation.candidateFreshAfterEpoch,
                  ":freshAfterIso": new Date(
                    mutation.candidateFreshAfterEpoch * 1000,
                  ).toISOString(),
                  ":receiverFreshAfterIso": new Date(
                    mutation.receiverFreshAfterEpoch * 1000,
                  ).toISOString(),
                  ":candidateDigest": mutation.preparation.candidateDigest,
                  ":expectedTimelineId":
                    mutation.preparation.expectedTimelineId,
                  ":expectedSystemId":
                    mutation.preparation.expectedUpstreamSystemId,
                  ":minimumReplayWal":
                    mutation.commitCandidate.minimumReplayWalPosition,
                  ":maxLag": mutation.preparation.maxReplicaLagBytes,
                },
              },
            },
            {
              Delete: {
                TableName: this.tableName,
                Key: this.configRotationPreparationKey(
                  mutation.preparation.rotationId,
                ),
                ConditionExpression:
                  "requestDigest = :requestDigest AND preparationTokenHash = :tokenHash",
                ExpressionAttributeValues: {
                  ":requestDigest": mutation.preparation.requestDigest,
                  ":tokenHash": mutation.preparationTokenHash,
                },
              },
            },
            {
              Delete: {
                TableName: this.tableName,
                Key: this.configRotationActiveKey(),
                ConditionExpression:
                  "rotationId = :rotationId AND requestDigest = :requestDigest",
                ExpressionAttributeValues: {
                  ":rotationId": mutation.preparation.rotationId,
                  ":requestDigest": mutation.preparation.requestDigest,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.configRotationItem(mutation.receipt),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(mutation.audit),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
          ],
        }),
      );
      return mutation.receipt;
    } catch (error) {
      this.conditional(
        error,
        "configuration digest rotation commit conditions failed",
      );
    }
  }

  async abortConfigDigestRotation(
    mutation: ConfigDigestRotationAbortMutation,
  ): Promise<ConfigDigestRotationAbortReceipt> {
    if (
      mutation.evidenceCandidate.candidate ===
        mutation.preparation.expectedLeader ||
      !mutation.preparation.candidateHosts.includes(
        mutation.evidenceCandidate.candidate,
      ) ||
      mutation.candidateDigestGuardHosts.some(
        (host) =>
          host === mutation.preparation.expectedLeader ||
          host === mutation.evidenceCandidate.candidate ||
          !mutation.preparation.candidateHosts.includes(host),
      )
    ) {
      throw new ConditionalWriteError(
        "configuration digest rotation abort requires a configured non-leader candidate",
      );
    }
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.stateKey(),
                ConditionExpression:
                  "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND configDigest = :expectedCurrentDigest",
                ExpressionAttributeValues: {
                  ":expectedLeader": mutation.preparation.expectedLeader,
                  ":expectedEpoch": mutation.preparation.expectedEpoch,
                  ":expectedCurrentDigest":
                    mutation.preparation.expectedCurrentDigest,
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(
                  mutation.evidenceCandidate.candidate,
                ),
                ConditionExpression:
                  "attribute_exists(candidate) AND healthy = :healthy AND inRecovery = :inRecovery AND receiverState = :streaming AND observedAtEpoch > :evidenceAfter AND lagMeasuredAt > :evidenceAfterIso AND lastMessageAt > :evidenceAfterIso AND configDigest = :expectedCurrentDigest AND timelineId = :expectedTimelineId AND upstreamSystemId = :expectedSystemId AND replayWalPosition >= :minimumReplayWal AND replicaLagBytes <= :maxLag",
                ExpressionAttributeValues: {
                  ":healthy": true,
                  ":inRecovery": true,
                  ":streaming": "streaming",
                  ":evidenceAfter": mutation.evidenceAfterEpoch,
                  ":evidenceAfterIso": new Date(
                    mutation.evidenceAfterEpoch * 1000,
                  ).toISOString(),
                  ":expectedCurrentDigest":
                    mutation.preparation.expectedCurrentDigest,
                  ":expectedTimelineId":
                    mutation.preparation.expectedTimelineId,
                  ":expectedSystemId":
                    mutation.preparation.expectedUpstreamSystemId,
                  ":minimumReplayWal":
                    mutation.evidenceCandidate.minimumReplayWalPosition,
                  ":maxLag": mutation.preparation.maxReplicaLagBytes,
                },
              },
            },
            ...mutation.candidateDigestGuardHosts.map((host) => ({
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(host),
                ConditionExpression:
                  "attribute_not_exists(configDigest) OR configDigest <> :candidateDigest",
                ExpressionAttributeValues: {
                  ":candidateDigest": mutation.preparation.candidateDigest,
                },
              },
            })),
            {
              Delete: {
                TableName: this.tableName,
                Key: this.configRotationPreparationKey(
                  mutation.preparation.rotationId,
                ),
                ConditionExpression:
                  "requestDigest = :requestDigest AND preparationTokenHash = :tokenHash AND expiresAtEpoch < :nowEpoch",
                ExpressionAttributeValues: {
                  ":requestDigest": mutation.preparation.requestDigest,
                  ":tokenHash": mutation.preparationTokenHash,
                  ":nowEpoch": mutation.nowEpoch,
                },
              },
            },
            {
              Delete: {
                TableName: this.tableName,
                Key: this.configRotationActiveKey(),
                ConditionExpression:
                  "rotationId = :rotationId AND requestDigest = :requestDigest",
                ExpressionAttributeValues: {
                  ":rotationId": mutation.preparation.rotationId,
                  ":requestDigest": mutation.preparation.requestDigest,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.configRotationAbortItem(mutation.receipt),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(mutation.audit),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
          ],
        }),
      );
      return mutation.receipt;
    } catch (error) {
      this.conditional(
        error,
        "configuration digest rotation abort conditions failed",
      );
    }
  }

  async promote(mutation: PromotionMutation): Promise<LeadershipState> {
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              Update: {
                TableName: this.tableName,
                Key: this.stateKey(),
                UpdateExpression:
                  "SET currentLeader = :candidate, fabricEpoch = :nextEpoch, timelineId = :nextTimelineId, leaderWalPosition = :nextLeaderWal, leaderBaselineAt = :nextBaselineAt, updatedAt = :updatedAt, fenceDigest = :fenceDigest, authorityMode = :authorityMode, degradedUntil = :degradedUntil, degradedIncidentDigest = :degradedIncidentDigest",
                ConditionExpression:
                  "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND timelineId = :expectedTimelineId AND configDigest = :configDigest AND leaderWalPosition = :expectedLeaderWal AND upstreamSystemId = :expectedSystemId AND leaderBaselineAt >= :baselineFreshAfter",
                ExpressionAttributeValues: {
                  ":candidate": mutation.candidate,
                  ":nextEpoch": mutation.nextState.fabricEpoch,
                  ":nextTimelineId": mutation.nextState.timelineId,
                  ":updatedAt": mutation.nextState.updatedAt,
                  ":fenceDigest": mutation.nextState.fenceDigest,
                  ":authorityMode": mutation.nextState.authorityMode,
                  ":degradedUntil": mutation.nextState.degradedUntil,
                  ":degradedIncidentDigest":
                    mutation.nextState.degradedIncidentDigest,
                  ":nextLeaderWal": mutation.nextState.leaderWalPosition,
                  ":nextBaselineAt": mutation.nextState.leaderBaselineAt,
                  ":expectedLeader": mutation.expectedLeader,
                  ":expectedEpoch": mutation.expectedEpoch,
                  ":expectedTimelineId": mutation.expectedTimelineId,
                  ":configDigest": mutation.configDigest,
                  ":expectedLeaderWal": mutation.expectedLeaderWalPosition,
                  ":expectedSystemId": mutation.expectedUpstreamSystemId,
                  ":baselineFreshAfter": new Date(
                    mutation.leaderBaselineFreshAfterEpoch * 1000,
                  ).toISOString(),
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(mutation.expectedLeader),
                ConditionExpression:
                  "attribute_exists(candidate) AND observedAtEpoch < :freshAfter",
                ExpressionAttributeValues: {
                  ":freshAfter": mutation.freshAfterEpoch,
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(mutation.candidate),
                ConditionExpression:
                  "healthy = :healthy AND inRecovery = :inRecovery AND observedAtEpoch >= :freshAfter AND lagMeasuredAt >= :freshAfterIso AND lastMessageAt >= :receiverFreshAfterIso AND receiverState = :streaming AND replicaLagBytes <= :maxLag AND replayWalPosition >= :minimumReplayWal AND upstreamSystemId = :expectedSystemId AND timelineId = :expectedTimelineId AND configDigest = :configDigest",
                ExpressionAttributeValues: {
                  ":healthy": true,
                  ":inRecovery": true,
                  ":freshAfter": mutation.freshAfterEpoch,
                  ":freshAfterIso": new Date(
                    mutation.freshAfterEpoch * 1000,
                  ).toISOString(),
                  ":maxLag": mutation.maxReplicaLagBytes,
                  ":minimumReplayWal": mutation.minimumReplayWalPosition,
                  ":expectedSystemId": mutation.expectedUpstreamSystemId,
                  ":streaming": "streaming",
                  ":receiverFreshAfterIso": new Date(
                    mutation.receiverFreshAfterEpoch * 1000,
                  ).toISOString(),
                  ":expectedTimelineId": mutation.expectedTimelineId,
                  ":configDigest": mutation.configDigest,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(mutation.audit),
              },
            },
          ],
        }),
      );
      return mutation.nextState;
    } catch (error) {
      this.conditional(error, "promotion conditions were not satisfied");
    }
  }

  async putFailbackPlan(
    plan: FailbackPlan,
    audit: AuditRecord,
  ): Promise<void> {
    if (plan.phase !== "transfer") {
      throw new ConditionalWriteError(
        "only an eligibility-verified transfer plan may use failback planning",
      );
    }
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.stateKey(),
                ConditionExpression:
                  "currentLeader = :leader AND fabricEpoch = :epoch AND timelineId = :expectedTimelineId AND configDigest = :configDigest AND leaderWalPosition = :expectedLeaderWal AND upstreamSystemId = :expectedSystemId AND leaderBaselineAt >= :baselineFreshAfter",
                ExpressionAttributeValues: {
                  ":leader": plan.expectedLeader,
                  ":epoch": plan.expectedEpoch,
                  ":expectedTimelineId": plan.expectedTimelineId,
                  ":configDigest": plan.configDigest,
                  ":expectedLeaderWal": plan.expectedLeaderWalPosition,
                  ":expectedSystemId": plan.expectedUpstreamSystemId,
                  ":baselineFreshAfter": new Date(
                    plan.leaderBaselineFreshAfterEpoch * 1000,
                  ).toISOString(),
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(plan.to),
                ConditionExpression:
                  "healthy = :healthy AND inRecovery = :inRecovery AND observedAtEpoch >= :freshAfter AND lagMeasuredAt >= :freshAfterIso AND lastMessageAt >= :receiverFreshAfterIso AND receiverState = :streaming AND replicaLagBytes <= :maxLag AND replayWalPosition >= :minimumReplayWal AND upstreamSystemId = :expectedSystemId AND timelineId = :expectedTimelineId AND configDigest = :configDigest",
                ExpressionAttributeValues: {
                  ":healthy": true,
                  ":inRecovery": true,
                  ":freshAfter": plan.freshAfterEpoch,
                  ":freshAfterIso": new Date(
                    plan.freshAfterEpoch * 1000,
                  ).toISOString(),
                  ":maxLag": plan.maxReplicaLagBytes,
                  ":minimumReplayWal": plan.minimumReplayWalPosition,
                  ":expectedSystemId": plan.expectedUpstreamSystemId,
                  ":streaming": "streaming",
                  ":receiverFreshAfterIso": new Date(
                    plan.receiverFreshAfterEpoch * 1000,
                  ).toISOString(),
                  ":expectedTimelineId": plan.expectedTimelineId,
                  ":configDigest": plan.configDigest,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.planItem(plan),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(audit),
              },
            },
          ],
        }),
      );
    } catch (error) {
      this.conditional(error, "failback planning conditions were not satisfied");
    }
  }

  async putFailbackPreparation(
    plan: FailbackPlan,
    audit: AuditRecord,
  ): Promise<void> {
    if (plan.phase !== "reseed") {
      throw new ConditionalWriteError(
        "only a reseed-phase authorization may use failback preparation",
      );
    }
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.stateKey(),
                ConditionExpression:
                  "currentLeader = :leader AND fabricEpoch = :epoch AND timelineId = :expectedTimelineId AND configDigest = :configDigest AND leaderWalPosition = :expectedLeaderWal AND upstreamSystemId = :expectedSystemId",
                ExpressionAttributeValues: {
                  ":leader": plan.expectedLeader,
                  ":epoch": plan.expectedEpoch,
                  ":expectedTimelineId": plan.expectedTimelineId,
                  ":configDigest": plan.configDigest,
                  ":expectedLeaderWal": plan.expectedLeaderWalPosition,
                  ":expectedSystemId": plan.expectedUpstreamSystemId,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.planItem(plan),
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(audit),
              },
            },
          ],
        }),
      );
    } catch (error) {
      this.conditional(
        error,
        "standby reseed authorization conditions were not satisfied",
      );
    }
  }

  async getFailbackPlan(tokenHash: string): Promise<FailbackPlan | null> {
    const response = await this.client.send(
      new GetCommand({
        TableName: this.tableName,
        Key: this.planKey(tokenHash),
        ConsistentRead: true,
      }),
    );
    const item = response.Item;
    if (!item) return null;
    return {
      phase: item.phase === "reseed" ? "reseed" : "transfer",
      tokenHash: String(item.tokenHash),
      from: String(item.from),
      to: String(item.to),
      expectedLeader: String(item.expectedLeader),
      expectedEpoch: Number(item.expectedEpoch),
      configDigest: String(item.configDigest),
      createdAt: String(item.createdAt),
      expiresAt: String(item.expiresAt),
      expiresAtEpoch: Number(item.expiresAtEpoch),
      freshAfterEpoch: Number(item.freshAfterEpoch),
      maxReplicaLagBytes: Number(item.maxReplicaLagBytes),
      expectedTimelineId: Number(item.expectedTimelineId),
      expectedLeaderWalPosition: Number(item.expectedLeaderWalPosition),
      minimumReplayWalPosition: Number(item.minimumReplayWalPosition),
      expectedUpstreamSystemId: String(item.expectedUpstreamSystemId),
      leaderBaselineFreshAfterEpoch: Number(item.leaderBaselineFreshAfterEpoch),
      receiverFreshAfterEpoch: Number(item.receiverFreshAfterEpoch),
    };
  }

  async commitFailback(
    mutation: FailbackCommitMutation,
  ): Promise<LeadershipState> {
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            {
              Update: {
                TableName: this.tableName,
                Key: this.stateKey(),
                UpdateExpression:
                  "SET currentLeader = :candidate, fabricEpoch = :nextEpoch, timelineId = :nextTimelineId, leaderWalPosition = :nextLeaderWal, leaderBaselineAt = :nextBaselineAt, updatedAt = :updatedAt, fenceDigest = :fenceDigest, authorityMode = :authorityMode, degradedUntil = :degradedUntil, degradedIncidentDigest = :degradedIncidentDigest",
                ConditionExpression:
                  "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND timelineId = :expectedTimelineId AND configDigest = :configDigest AND leaderWalPosition = :expectedLeaderWal AND upstreamSystemId = :expectedSystemId AND leaderBaselineAt >= :baselineFreshAfter",
                ExpressionAttributeValues: {
                  ":candidate": mutation.candidate,
                  ":nextEpoch": mutation.nextState.fabricEpoch,
                  ":nextTimelineId": mutation.nextState.timelineId,
                  ":updatedAt": mutation.nextState.updatedAt,
                  ":fenceDigest": mutation.nextState.fenceDigest,
                  ":authorityMode": mutation.nextState.authorityMode,
                  ":degradedUntil": mutation.nextState.degradedUntil,
                  ":degradedIncidentDigest":
                    mutation.nextState.degradedIncidentDigest,
                  ":nextLeaderWal": mutation.nextState.leaderWalPosition,
                  ":nextBaselineAt": mutation.nextState.leaderBaselineAt,
                  ":expectedLeader": mutation.expectedLeader,
                  ":expectedEpoch": mutation.expectedEpoch,
                  ":expectedTimelineId": mutation.expectedTimelineId,
                  ":configDigest": mutation.configDigest,
                  ":expectedLeaderWal": mutation.expectedLeaderWalPosition,
                  ":expectedSystemId": mutation.expectedUpstreamSystemId,
                  ":baselineFreshAfter": new Date(
                    mutation.leaderBaselineFreshAfterEpoch * 1000,
                  ).toISOString(),
                },
              },
            },
            {
              ConditionCheck: {
                TableName: this.tableName,
                Key: this.candidateKey(mutation.candidate),
                ConditionExpression:
                  "healthy = :healthy AND inRecovery = :inRecovery AND observedAtEpoch >= :freshAfter AND lagMeasuredAt >= :freshAfterIso AND lastMessageAt >= :receiverFreshAfterIso AND receiverState = :streaming AND replicaLagBytes <= :maxLag AND replayWalPosition >= :minimumReplayWal AND upstreamSystemId = :expectedSystemId AND timelineId = :expectedTimelineId AND configDigest = :configDigest",
                ExpressionAttributeValues: {
                  ":healthy": true,
                  ":inRecovery": true,
                  ":freshAfter": mutation.freshAfterEpoch,
                  ":freshAfterIso": new Date(
                    mutation.freshAfterEpoch * 1000,
                  ).toISOString(),
                  ":maxLag": mutation.maxReplicaLagBytes,
                  ":minimumReplayWal": mutation.minimumReplayWalPosition,
                  ":expectedSystemId": mutation.expectedUpstreamSystemId,
                  ":streaming": "streaming",
                  ":receiverFreshAfterIso": new Date(
                    mutation.receiverFreshAfterEpoch * 1000,
                  ).toISOString(),
                  ":expectedTimelineId": mutation.expectedTimelineId,
                  ":configDigest": mutation.configDigest,
                },
              },
            },
            {
              Delete: {
                TableName: this.tableName,
                Key: this.planKey(mutation.planTokenHash),
                ConditionExpression:
                  "tokenHash = :tokenHash AND expiresAtEpoch >= :nowEpoch",
                ExpressionAttributeValues: {
                  ":tokenHash": mutation.planTokenHash,
                  ":nowEpoch": mutation.nowEpoch,
                },
              },
            },
            {
              Put: {
                TableName: this.tableName,
                Item: this.auditItem(mutation.audit),
              },
            },
          ],
        }),
      );
      return mutation.nextState;
    } catch (error) {
      this.conditional(error, "failback commit conditions were not satisfied");
    }
  }

  async appendAudit(audit: AuditRecord): Promise<void> {
    await this.client.send(
      new PutCommand({
        TableName: this.tableName,
        Item: this.auditItem(audit),
        ConditionExpression: "attribute_not_exists(pk)",
      }),
    );
  }

  async listAudit(limit: number): Promise<AuditRecord[]> {
    const response = await this.client.send(
      new QueryCommand({
        TableName: this.tableName,
        KeyConditionExpression: "pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues: {
          ":pk": this.partitionKey,
          ":prefix": "AUDIT#",
        },
        ScanIndexForward: false,
        Limit: limit,
        ConsistentRead: true,
      }),
    );
    return (response.Items ?? []).map((item) => ({
      auditId: String(item.auditId),
      eventType: item.eventType as AuditRecord["eventType"],
      actor: String(item.actor),
      occurredAt: String(item.occurredAt),
      ...(item.previousLeader
        ? { previousLeader: String(item.previousLeader) }
        : {}),
      ...(item.newLeader ? { newLeader: String(item.newLeader) } : {}),
      ...(item.previousEpoch !== undefined
        ? { previousEpoch: Number(item.previousEpoch) }
        : {}),
      ...(item.newEpoch !== undefined
        ? { newEpoch: Number(item.newEpoch) }
        : {}),
      ...(item.requestDigest
        ? { requestDigest: String(item.requestDigest) }
        : {}),
      detail: (item.detail ?? {}) as Record<string, unknown>,
    }));
  }
}
