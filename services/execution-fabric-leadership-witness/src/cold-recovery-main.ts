import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { commitColdWitness, fileHash, safeFile } from "./cold-recovery.js";

async function main(): Promise<void> {
  const [operation, policyFile, anchorFile, ...extra] = process.argv.slice(2);
  if (operation !== "commit" || !policyFile || !anchorFile || extra.length) throw new Error("unsupported offline witness operation");
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    const data = Buffer.from(chunk); bytes += data.length;
    if (bytes > 4_194_304) throw new Error("cold request is too large");
    chunks.push(data);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
  const policy = JSON.parse(readFileSync(safeFile(policyFile), "utf8"));
  if (fileHash(fileURLToPath(import.meta.url)) !== policy.witnessActorSha256) throw new Error("unreviewed witness actor image");
  const receipt = await commitColdWitness(request, policy, JSON.parse(readFileSync(safeFile(anchorFile), "utf8")));
  process.stdout.write(JSON.stringify(receipt)+"\n");
}
main().catch(() => { process.stderr.write("cold_recovery_refused: witness remains held\n"); process.exitCode = 1; });
