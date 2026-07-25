import "dotenv/config";
import { readFileSync } from "node:fs";
import { z } from "zod";
import { buildGateway } from "./gateway.js";

const environment = z.object({
  FABRIC_GATEWAY_HOST: z.string().default("127.0.0.1"),
  FABRIC_GATEWAY_PORT: z.coerce.number().int().min(1).max(65535).default(3181),
  FABRIC_CLUSTER_ID: z.string().min(1),
  FABRIC_LEADERSHIP_API_BASE: z.string().url(),
  FABRIC_LEADERSHIP_TOKEN_FILE: z.string().min(1),
  FABRIC_LEADERSHIP_PUBLIC_KEY_FILE: z.string().min(1),
  FABRIC_GATEWAY_LEADER_ENDPOINTS: z.string().min(1),
}).parse(process.env);

const endpoints = z.record(z.string().url()).parse(
  JSON.parse(environment.FABRIC_GATEWAY_LEADER_ENDPOINTS),
);
const server = buildGateway({
  host: environment.FABRIC_GATEWAY_HOST,
  port: environment.FABRIC_GATEWAY_PORT,
  clusterId: environment.FABRIC_CLUSTER_ID,
  witnessBaseUrl: environment.FABRIC_LEADERSHIP_API_BASE,
  witnessToken: readFileSync(
    environment.FABRIC_LEADERSHIP_TOKEN_FILE,
    "utf8",
  ).trim(),
  witnessPublicKey: readFileSync(
    environment.FABRIC_LEADERSHIP_PUBLIC_KEY_FILE,
    "utf8",
  ),
  leaderEndpoints: endpoints,
});

server.listen(
  environment.FABRIC_GATEWAY_PORT,
  environment.FABRIC_GATEWAY_HOST,
);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    server.close(() => process.exit(0));
  });
}
