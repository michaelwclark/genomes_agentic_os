import { describe, expect, it, vi } from "vitest";
import type pg from "pg";
import {
  measurePostgresMutationDurability,
  measurePostgresReplication,
} from "../src/postgres-replication.js";

describe("PostgreSQL replication measurement", () => {
  it("returns recovery, timeline, LSN, and lag values from one database sample", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          in_recovery: true,
          timeline_id: 7,
          receive_lsn: "A/120",
          replay_lsn: "A/100",
          receive_wal_position: "66080",
          replay_wal_position: "66048",
          lag_bytes: "32",
          upstream_system_id: "7600000000000000000",
          receiver_state: "streaming",
          last_message_at: new Date("2026-07-24T20:00:00.000Z"),
          measured_at: new Date("2026-07-24T20:00:00.000Z"),
        },
      ],
    });
    const snapshot = await measurePostgresReplication({
      query,
    } as unknown as pg.Pool);
    expect(snapshot).toEqual({
      inRecovery: true,
      timelineId: 7,
      receiveLsn: "A/120",
      replayLsn: "A/100",
      receiveWalPosition: 66080,
      replayWalPosition: 66048,
      replicaLagBytes: 32,
      upstreamSystemId: "7600000000000000000",
      receiverState: "streaming",
      lastMessageAt: "2026-07-24T20:00:00.000Z",
      lagMeasuredAt: "2026-07-24T20:00:00.000Z",
    });
    expect(query).toHaveBeenCalledOnce();
  });

  it("fails closed on invalid timeline or lag results", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          in_recovery: true,
          timeline_id: 0,
          receive_lsn: "A/120",
          replay_lsn: "A/100",
          receive_wal_position: "-1",
          replay_wal_position: "-1",
          lag_bytes: "-1",
          upstream_system_id: "7600000000000000000",
          receiver_state: "disconnected",
          last_message_at: new Date(0),
          measured_at: new Date(),
        },
      ],
    });
    await expect(
      measurePostgresReplication({ query } as unknown as pg.Pool),
    ).rejects.toThrow(/invalid values/);
  });

  it("admits mutations only with remote_apply and a streaming sync standby", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [
        {
          in_recovery: false,
          synchronous_commit: "remote_apply",
          synchronous_standby_names: "FIRST 1 (fabric_standby)",
          synchronous_standby_count: "1",
          measured_at: new Date("2026-07-24T20:00:00.000Z"),
        },
      ],
    });
    await expect(
      measurePostgresMutationDurability({ query } as unknown as pg.Pool),
    ).resolves.toMatchObject({
      inRecovery: false,
      synchronousCommit: "remote_apply",
      synchronousStandbyCount: 1,
      mutationDurabilityReady: true,
    });
  });

  it.each([
    ["recovery", true, "remote_apply", "FIRST 1 (fabric_standby)", 1],
    ["local commit", false, "local", "FIRST 1 (fabric_standby)", 1],
    ["no configured standby", false, "remote_apply", "", 1],
    ["no streaming sync standby", false, "remote_apply", "FIRST 1 (fabric_standby)", 0],
  ])(
    "fences mutations for %s",
    async (
      _caseName,
      inRecovery,
      synchronousCommit,
      synchronousStandbyNames,
      synchronousStandbyCount,
    ) => {
      const query = vi.fn().mockResolvedValue({
        rows: [
          {
            in_recovery: inRecovery,
            synchronous_commit: synchronousCommit,
            synchronous_standby_names: synchronousStandbyNames,
            synchronous_standby_count: synchronousStandbyCount,
            measured_at: "2026-07-24T20:00:00.000Z",
          },
        ],
      });
      await expect(
        measurePostgresMutationDurability({ query } as unknown as pg.Pool),
      ).resolves.toMatchObject({ mutationDurabilityReady: false });
    },
  );
});
