import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { pipeline } from "node:stream/promises";
import { z } from "zod";
import { LeadershipFencedError, verifyLeadershipToken } from "./leadership.js";

const statusSchema = z.object({
  clusterId: z.string().min(1),
  currentLeader: z.string().min(1),
  fabricEpoch: z.number().int().min(1),
  leadershipToken: z.string().min(1),
});

export type GatewayConfig = {
  host: string;
  port: number;
  clusterId: string;
  witnessBaseUrl: string;
  witnessToken: string;
  witnessPublicKey: string;
  leaderEndpoints: Record<string, string>;
};

export class LeaderResolver {
  private cached:
    | {
        leader: string;
        endpoint: string;
        epoch: number;
        expiresAt: string;
        verifiedAt: string;
      }
    | undefined;

  constructor(
    readonly config: GatewayConfig,
    private readonly fetcher: typeof globalThis.fetch = globalThis.fetch,
    private readonly now: () => Date = () => new Date(),
  ) {}

  async resolve(): Promise<NonNullable<LeaderResolver["cached"]>> {
    try {
      const response = await this.fetcher(
        `${this.config.witnessBaseUrl.replace(/\/$/, "")}/api/v1/admin/leadership/status`,
        {
          headers: {
            authorization: `Bearer ${this.config.witnessToken}`,
          },
          signal: AbortSignal.timeout(5000),
        },
      );
      if (!response.ok) {
        throw new LeadershipFencedError(
          `witness returned HTTP ${response.status}`,
        );
      }
      const status = statusSchema.parse(await response.json());
      const proof = verifyLeadershipToken(
        status.leadershipToken,
        this.config.witnessPublicKey,
      );
      if (
        status.clusterId !== this.config.clusterId ||
        proof.cluster !== this.config.clusterId ||
        proof.leader !== status.currentLeader ||
        proof.epoch !== status.fabricEpoch
      ) {
        throw new LeadershipFencedError(
          "witness status and signed leadership proof do not match",
        );
      }
      const endpoint = this.config.leaderEndpoints[status.currentLeader];
      if (!endpoint) {
        throw new LeadershipFencedError(
          `no gateway endpoint is configured for leader ${status.currentLeader}`,
        );
      }
      this.cached = {
        leader: status.currentLeader,
        endpoint: endpoint.replace(/\/$/, ""),
        epoch: status.fabricEpoch,
        expiresAt: proof.expiresAt,
        verifiedAt: this.now().toISOString(),
      };
      return this.cached;
    } catch (error) {
      if (
        this.cached &&
        new Date(this.cached.expiresAt).getTime() > this.now().getTime()
      ) {
        return this.cached;
      }
      throw error;
    }
  }

  snapshot(): Record<string, unknown> {
    return {
      state:
        this.cached &&
        new Date(this.cached.expiresAt).getTime() > this.now().getTime()
          ? "routable"
          : "fenced",
      ...(this.cached ?? {
        leader: null,
        endpoint: null,
        epoch: null,
        expiresAt: null,
        verifiedAt: null,
      }),
    };
  }
}

export function buildGateway(config: GatewayConfig, resolver = new LeaderResolver(config)) {
  return createServer(async (request: IncomingMessage, response: ServerResponse) => {
    if (request.url === "/gateway/status") {
      response.setHeader("content-type", "application/json");
      try {
        await resolver.resolve();
        response.end(JSON.stringify(resolver.snapshot()));
      } catch (error) {
        response.statusCode = 503;
        response.end(
          JSON.stringify({
            ...resolver.snapshot(),
            error:
              error instanceof Error
                ? error.message
                : "leader resolution failed",
          }),
        );
      }
      return;
    }
    try {
      const leader = await resolver.resolve();
      const upstream = await fetch(`${leader.endpoint}${request.url ?? "/"}`, {
        method: request.method,
        headers: Object.fromEntries(
          Object.entries(request.headers)
            .filter(([name, value]) => name.toLowerCase() !== "host" && value !== undefined)
            .map(([name, value]) => [
              name,
              Array.isArray(value) ? value.join(",") : String(value),
            ]),
        ),
        body:
          request.method === "GET" || request.method === "HEAD"
            ? undefined
            : (request as unknown as BodyInit),
        duplex: "half",
        redirect: "manual",
        signal: AbortSignal.timeout(35000),
      } as RequestInit & { duplex: "half" });
      response.statusCode = upstream.status;
      upstream.headers.forEach((value, name) => response.setHeader(name, value));
      if (upstream.body) {
        await pipeline(
          upstream.body as unknown as NodeJS.ReadableStream,
          response,
        );
      } else {
        response.end();
      }
    } catch (error) {
      response.statusCode = 503;
      response.setHeader("content-type", "application/json");
      response.end(
        JSON.stringify({
          error: "leadership_unavailable",
          message:
            error instanceof Error ? error.message : "leader resolution failed",
        }),
      );
    }
  });
}
