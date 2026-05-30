#!/usr/bin/env node
// Repairs stale Claude context-mode plugin cache symlinks after auto-updates.
// Pure Node.js so it can run from a SessionStart hook without shell quoting.
import { existsSync, lstatSync, readFileSync, readdirSync, statSync, symlinkSync, unlinkSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { homedir } from "node:os";

function configDir() {
  const configured = process.env.CLAUDE_CONFIG_DIR;
  if (configured && configured.trim() !== "") {
    return configured.startsWith("~")
      ? resolve(homedir(), configured.replace(/^~[/\\]?/, ""))
      : resolve(configured);
  }
  return resolve(homedir(), ".claude");
}

try {
  const installedPath = resolve(configDir(), "plugins", "installed_plugins.json");
  if (!existsSync(installedPath)) process.exit(0);

  const cacheRoot = resolve(configDir(), "plugins", "cache");
  const installed = JSON.parse(readFileSync(installedPath, "utf-8"));

  for (const [key, entries] of Object.entries(installed.plugins || {})) {
    if (key !== "context-mode@context-mode") continue;
    for (const entry of entries) {
      const installPath = entry.installPath;
      if (!installPath || existsSync(installPath)) continue;
      if (!resolve(installPath).startsWith(cacheRoot + sep)) continue;

      const parent = dirname(installPath);
      if (!existsSync(parent)) continue;
      try {
        if (lstatSync(installPath).isSymbolicLink()) unlinkSync(installPath);
      } catch {}

      const versions = readdirSync(parent)
        .filter((name) => /^\d+\.\d+/.test(name) && statSync(join(parent, name)).isDirectory())
        .sort((a, b) => {
          const pa = a.split(".").map(Number);
          const pb = b.split(".").map(Number);
          for (let i = 0; i < 3; i += 1) {
            if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
          }
          return 0;
        });

      if (!versions.length) continue;
      try {
        symlinkSync(join(parent, versions[versions.length - 1]), installPath, process.platform === "win32" ? "junction" : undefined);
      } catch {}
    }
  }
} catch {}

