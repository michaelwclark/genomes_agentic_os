#!/usr/bin/env node

/**
 * Verifies that every dependency listed in package.json has a corresponding
 * contract test file in e2e/contracts/. Exits non-zero if any are missing.
 *
 * Usage: node scripts/check-contract-coverage.mjs   (from apps/agentic-os-gui)
 *
 * Packages can be excluded by adding them to the EXCLUDED set below
 * (for tooling-only packages that have no importable API surface).
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const EXCLUDED = new Set([
  // Type definitions only — no runtime surface to contract-test
  "@types/node",
  "@types/react",
  "@types/react-dom",
  // CLI-only packager (package:mac script) — never imported by source
  "electron-builder",
]);

const pkg = JSON.parse(fs.readFileSync(path.join(appRoot, "package.json"), "utf-8"));
const allDeps = [...Object.keys(pkg.dependencies ?? {}), ...Object.keys(pkg.devDependencies ?? {})];

const contractDir = path.join(appRoot, "e2e", "contracts");
const existingFiles = fs.existsSync(contractDir)
  ? fs.readdirSync(contractDir).filter((f) => f.endsWith(".contract.ts"))
  : [];

const existingContracts = new Set(existingFiles.map((f) => f.replace(".contract.ts", "")));

function toFileName(dep) {
  return dep.replace(/^@/, "").replace(/\//g, "-");
}

const missing = [];
const covered = [];

for (const dep of allDeps.sort()) {
  if (EXCLUDED.has(dep)) continue;
  const fileName = toFileName(dep);
  if (existingContracts.has(fileName)) {
    covered.push(dep);
  } else {
    missing.push({ dep, expectedFile: `${fileName}.contract.ts` });
  }
}

console.log(
  `Contract test coverage: ${covered.length}/${covered.length + missing.length} dependencies covered\n`
);

if (covered.length > 0) {
  console.log("Covered:");
  for (const dep of covered) {
    console.log(`   ${dep}`);
  }
}

if (missing.length > 0) {
  console.log("\nMissing contract tests:");
  for (const { dep, expectedFile } of missing) {
    console.log(`   ${dep} -> e2e/contracts/${expectedFile}`);
  }
  console.log("\nAdd contract test files for the above dependencies.");
  console.log(
    "If a package is tooling-only (not imported in source), add it to the EXCLUDED set in scripts/check-contract-coverage.mjs."
  );
  process.exit(1);
}

console.log("\nAll dependencies have contract test coverage.");
