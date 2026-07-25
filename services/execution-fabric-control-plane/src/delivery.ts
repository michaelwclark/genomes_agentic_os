import { Queue, type ConnectionOptions } from "bullmq";
import { Redis } from "ioredis";
import type { TaskRecord } from "./contracts.js";

export interface DeliveryPort {
  publish(task: TaskRecord): Promise<void>;
  acknowledge(task: TaskRecord): Promise<void>;
  waitForWork(queues: string[], waitMs: number): Promise<void>;
  ping(): Promise<void>;
  close(): Promise<void>;
}

function physicalQueue(prefix: string, logicalQueue: string): string {
  const safeQueue = logicalQueue.replace(/[^a-zA-Z0-9_-]/g, "_");
  return `${prefix.replace(/:/g, "_")}__${safeQueue}`;
}

export class BullMqDelivery implements DeliveryPort {
  private readonly redis: Redis;
  private readonly connection: ConnectionOptions;
  private readonly queues = new Map<string, Queue>();

  constructor(
    valkeyUrl: string,
    private readonly prefix: string,
  ) {
    const parsed = new URL(valkeyUrl);
    this.connection = {
      host: parsed.hostname,
      port: Number(parsed.port || 6379),
      ...(parsed.username ? { username: decodeURIComponent(parsed.username) } : {}),
      ...(parsed.password ? { password: decodeURIComponent(parsed.password) } : {}),
      ...(parsed.pathname.length > 1
        ? { db: Number(parsed.pathname.slice(1)) }
        : {}),
      ...(parsed.protocol === "rediss:" ? { tls: {} } : {}),
      maxRetriesPerRequest: null,
    };
    this.redis = new Redis(valkeyUrl, {
      maxRetriesPerRequest: null,
      enableReadyCheck: true,
      lazyConnect: true,
    });
  }

  private queue(logicalQueue: string): Queue {
    let queue = this.queues.get(logicalQueue);
    if (!queue) {
      queue = new Queue(physicalQueue(this.prefix, logicalQueue), {
        connection: this.connection,
        defaultJobOptions: {
          attempts: 1,
          removeOnComplete: { age: 3600, count: 10000 },
          removeOnFail: false,
        },
      });
      this.queues.set(logicalQueue, queue);
    }
    return queue;
  }

  async publish(task: TaskRecord): Promise<void> {
    const queue = this.queue(task.queue);
    const existing = await queue.getJob(task.id);
    if (existing) return;
    await queue.add(
      "task-ready",
      {
        apiVersion: "agentic-os-fabric-delivery/v1",
        taskId: task.id,
        queue: task.queue,
      },
      {
        jobId: task.id,
        priority: Math.max(1, 1001 - task.priority),
      },
    );
  }

  async acknowledge(task: TaskRecord): Promise<void> {
    const job = await this.queue(task.queue).getJob(task.id);
    if (job) {
      await job.remove().catch(() => undefined);
    }
  }

  async waitForWork(queues: string[], waitMs: number): Promise<void> {
    const deadline = Date.now() + waitMs;
    do {
      const counts = await Promise.all(
        queues.map((queue) => this.queue(queue).getWaitingCount()),
      );
      if (counts.some((count) => count > 0)) return;
      const remaining = deadline - Date.now();
      if (remaining <= 0) return;
      await new Promise((resolve) => setTimeout(resolve, Math.min(250, remaining)));
    } while (Date.now() < deadline);
  }

  async ping(): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    const result = await this.redis.ping();
    if (result !== "PONG") throw new Error("Valkey PING did not return PONG");
  }

  async close(): Promise<void> {
    await Promise.all([...this.queues.values()].map((queue) => queue.close()));
    if (this.redis.status !== "end") await this.redis.quit();
  }
}
