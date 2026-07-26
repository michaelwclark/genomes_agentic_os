import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

type LockPackage = {
  cpu?: string[];
  dev?: boolean;
  gypfile?: boolean;
  hasInstallScript?: boolean;
  libc?: string[];
  os?: string[];
};

type PackageLock = {
  packages: Record<string, LockPackage>;
};

const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function nativeBinaries(directory: string): string[] {
  if (!existsSync(directory)) {
    return [];
  }

  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return nativeBinaries(path);
    }
    return entry.isFile() && entry.name.endsWith(".node") ? [path] : [];
  });
}

describe("portable production dependencies", () => {
  it("keeps the build-platform dependency tree safe to copy into every target image", () => {
    const lock = JSON.parse(
      readFileSync(join(serviceRoot, "package-lock.json"), "utf8"),
    ) as PackageLock;

    const violations: string[] = [];
    for (const [packagePath, metadata] of Object.entries(lock.packages)) {
      if (!packagePath || metadata.dev === true) {
        continue;
      }

      for (const field of ["os", "cpu", "libc"] as const) {
        if (metadata[field]?.length) {
          violations.push(`${packagePath}: ${field}=${metadata[field]?.join(",")}`);
        }
      }
      if (metadata.gypfile) {
        violations.push(`${packagePath}: gypfile=true`);
      }
      if (metadata.hasInstallScript) {
        violations.push(`${packagePath}: hasInstallScript=true`);
      }

      for (const binary of nativeBinaries(join(serviceRoot, packagePath))) {
        violations.push(`${packagePath}: native binary ${binary}`);
      }
    }

    expect(violations).toEqual([]);
  });
});
