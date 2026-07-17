import { watch, type FSWatcher } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const RELEVANT = /(?:project|work)\.ya?ml$|\.jsonl$|local_[A-Za-z0-9_-]+\.json$|state_5\.sqlite(?:-wal)?$|\.codex-global-state\.json$|state\.db(?:-wal)?$/;

export function isRelevantWatchPath(path: string): boolean {
  return RELEVANT.test(path);
}

export function watchTargets(root: string, home = homedir()): string[] {
  return [
    root,
    join(home, ".codex"),
    join(home, ".claude", "projects"),
    join(home, ".claude", "sessions"),
    join(home, "Library", "Application Support", "Claude", "claude-code-sessions"),
  ];
}

export class WatchCoordinator {
  private readonly watchers: FSWatcher[] = [];
  private timer?: NodeJS.Timeout;

  constructor(private readonly root: string, private readonly onChange: () => void, private readonly debounceMs = 500) {}

  start(): void {
    for (const target of watchTargets(this.root)) {
      try {
        this.watchers.push(
          watch(target, { recursive: true }, (_event, filename) => {
            if (filename && !isRelevantWatchPath(filename)) return;
            if (this.timer) clearTimeout(this.timer);
            this.timer = setTimeout(this.onChange, this.debounceMs);
          }),
        );
      } catch {
        // Optional harness stores may be absent; the snapshot diagnostic owns visibility.
      }
    }
  }

  close(): void {
    if (this.timer) clearTimeout(this.timer);
    for (const watcher of this.watchers) watcher.close();
    this.watchers.length = 0;
  }
}
