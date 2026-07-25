import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const fixture = JSON.parse(
  readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../tests/fixtures/execution_fabric_auth_contract.json",
    ),
    "utf8",
  ),
) as {
  schema_version: string;
  static_credentials: Record<
    string,
    { endpoints: string[]; bound_fields?: string[] }
  >;
  session_credentials: Record<
    string,
    {
      endpoints: string[];
      bearer_and_body_must_match: boolean;
      bound_fields?: string[];
    }
  >;
  source_credentials: {
    reliability_observation: {
      source_token_map_file_environment: string;
      endpoint: string;
      body_source_must_match_token_scope: boolean;
    };
  };
};

describe("cross-language authentication contract", () => {
  it("freezes distinct bootstrap, observer, admin, and session scopes", () => {
    expect(fixture.schema_version).toBe("execution-fabric-auth-contract/v2");
    expect(Object.keys(fixture.static_credentials).sort()).toEqual([
      "admin",
      "alarm_dispatcher",
      "effect_consumer",
      "observer",
      "submit",
      "worker_bootstrap",
    ]);
    expect(
      fixture.static_credentials.observer!.endpoints.every((endpoint) =>
        endpoint.startsWith("GET "),
      ),
    ).toBe(true);
    expect(fixture.static_credentials.worker_bootstrap!.bound_fields).toEqual([
      "bootstrapId",
      "workerId",
      "hostId",
      "queues",
      "capabilities",
      "maxConcurrency",
    ]);
    expect(fixture.static_credentials.effect_consumer!.bound_fields).toEqual([
      "consumerId",
      "source",
      "effectTypes",
    ]);
    expect(fixture.static_credentials.alarm_dispatcher!.bound_fields).toEqual([
      "consumerId",
      "source",
    ]);
    expect(
      fixture.session_credentials.registration_token!.endpoints,
    ).toContain("POST /api/v1/assignments/claim");
    expect(fixture.session_credentials.lease_token!.bound_fields).toEqual([
      "attemptId",
      "workerId",
      "fabricEpoch",
    ]);
    for (const credential of Object.values(
      fixture.session_credentials,
    )) {
      expect(credential.bearer_and_body_must_match).toBe(true);
    }
    expect(fixture.source_credentials.reliability_observation).toEqual({
      source_token_map_file_environment:
        "FABRIC_RELIABILITY_SOURCE_TOKENS_FILE",
      endpoint: "POST /api/v1/reliability/observations",
      body_source_must_match_token_scope: true,
    });
  });
});
