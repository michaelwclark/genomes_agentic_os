import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { reliabilityObservationSchema } from "../src/contracts.js";

const fixture = JSON.parse(
  readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../tests/fixtures/execution_fabric_reliability_observation.json",
    ),
    "utf8",
  ),
) as {
  schema_version: string;
  endpoint: string;
  request: {
    additional_properties: boolean;
    required: string[];
    example: Record<string, unknown>;
    recovery_example: Record<string, unknown>;
  };
  forbidden_request_fields: string[];
};

describe("cross-language external reliability observation contract", () => {
  it("parses the frozen example and rejects producer-controlled actions", () => {
    expect(fixture.schema_version).toBe(
      "execution-fabric-reliability-observation-contract/v1",
    );
    expect(fixture.endpoint).toBe("POST /api/v1/reliability/observations");
    expect(Object.keys(fixture.request.example).sort()).toEqual(
      [...fixture.request.required].sort(),
    );
    expect(
      reliabilityObservationSchema.parse(fixture.request.example),
    ).toEqual(fixture.request.example);
    expect(fixture.request.additional_properties).toBe(false);
    expect(
      reliabilityObservationSchema.parse(fixture.request.recovery_example),
    ).toEqual(fixture.request.recovery_example);
    expect(() =>
      reliabilityObservationSchema.parse({
        ...fixture.request.recovery_example,
        severity: "info",
      }),
    ).toThrow(/recovery observations retain/);

    for (const field of fixture.forbidden_request_fields) {
      expect(() =>
        reliabilityObservationSchema.parse({
          ...fixture.request.example,
          [field]: "producer-controlled",
        }),
      ).toThrow();
    }
  });
});
