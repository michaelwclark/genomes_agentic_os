export const ROLE_ENTRYPOINTS = {
  api: "dist/src/main.js",
  observer: "dist/src/observer-main.js",
  healer: "dist/src/healer-main.js",
  scheduler: "dist/src/scheduler-main.js",
} as const;

export type ServiceRole = keyof typeof ROLE_ENTRYPOINTS;

export async function runPeriodicRole(options: {
  role: Exclude<ServiceRole, "api">;
  intervalMs: number;
  signal: AbortSignal;
  tick: () => Promise<void>;
  once?: boolean;
  onError?: (error: unknown) => void;
}): Promise<void> {
  do {
    try {
      await options.tick();
    } catch (error) {
      options.onError?.(error);
    }
    if (options.once || options.signal.aborted) return;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, options.intervalMs);
      options.signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
    });
  } while (!options.signal.aborted);
}

export function boundedIntegerEnvironment(
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const value = process.env[name];
  if (value === undefined) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

export function allowListEnvironment<T extends string>(
  name: string,
  allowed: readonly T[],
  fallback: readonly T[],
): T[] {
  const raw = process.env[name];
  const values = raw === undefined
    ? [...fallback]
    : raw.split(",").map((value) => value.trim()).filter(Boolean);
  if (values.length === 0) {
    throw new Error(`${name} must contain at least one allow-listed action`);
  }
  const invalid = values.filter((value) => !allowed.includes(value as T));
  if (invalid.length > 0) {
    throw new Error(`${name} contains unsupported action(s): ${invalid.join(",")}`);
  }
  return [...new Set(values)] as T[];
}
