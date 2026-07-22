import { useEffect, useSyncExternalStore } from "react";

export interface LayoutState {
  schemaVersion: 1;
  navWidth: number;
  listWidth: number;
  railWidth: number;
  navVisible: boolean;
  railVisible: boolean;
  centerSplitRatio: number;
}

export type LayoutUpdate = Partial<Omit<LayoutState, "schemaVersion">>;

interface LayoutBounds {
  min: number;
  max: number;
  default: number;
}

export const layoutBounds: Record<"navWidth" | "listWidth" | "railWidth" | "centerSplitRatio", LayoutBounds> = {
  navWidth: { min: 170, max: 340, default: 230 },
  listWidth: { min: 280, max: 560, default: 390 },
  railWidth: { min: 220, max: 420, default: 270 },
  centerSplitRatio: { min: 0.25, max: 0.75, default: 0.5 },
};

export const defaultLayout: LayoutState = {
  schemaVersion: 1,
  navWidth: layoutBounds.navWidth.default,
  listWidth: layoutBounds.listWidth.default,
  railWidth: layoutBounds.railWidth.default,
  navVisible: true,
  railVisible: true,
  centerSplitRatio: layoutBounds.centerSplitRatio.default,
};

export const LAYOUT_STORAGE_KEY = "aos.layout.v1";
const PERSIST_DEBOUNCE_MS = 150;

const clampNumber = (value: number, bounds: LayoutBounds) => Math.min(bounds.max, Math.max(bounds.min, value));

export function clampLayout(state: LayoutState): LayoutState {
  return {
    ...state,
    navWidth: clampNumber(state.navWidth, layoutBounds.navWidth),
    listWidth: clampNumber(state.listWidth, layoutBounds.listWidth),
    railWidth: clampNumber(state.railWidth, layoutBounds.railWidth),
    centerSplitRatio: clampNumber(state.centerSplitRatio, layoutBounds.centerSplitRatio),
  };
}

export function serializeLayout(state: LayoutState): string {
  return JSON.stringify(state);
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const finiteOr = (value: unknown, fallback: number) => typeof value === "number" && Number.isFinite(value) ? value : fallback;
const booleanOr = (value: unknown, fallback: boolean) => typeof value === "boolean" ? value : fallback;

/** Tolerant by design: layout is a convenience, so garbage in storage silently falls back to defaults. */
export function deserializeLayout(raw: string | null | undefined): LayoutState {
  if (!raw) return defaultLayout;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return defaultLayout;
  }
  if (!isRecord(parsed) || parsed.schemaVersion !== 1) return defaultLayout;
  return clampLayout({
    schemaVersion: 1,
    navWidth: finiteOr(parsed.navWidth, defaultLayout.navWidth),
    listWidth: finiteOr(parsed.listWidth, defaultLayout.listWidth),
    railWidth: finiteOr(parsed.railWidth, defaultLayout.railWidth),
    navVisible: booleanOr(parsed.navVisible, defaultLayout.navVisible),
    railVisible: booleanOr(parsed.railVisible, defaultLayout.railVisible),
    centerSplitRatio: finiteOr(parsed.centerSplitRatio, defaultLayout.centerSplitRatio),
  });
}

const sameLayout = (a: LayoutState, b: LayoutState) =>
  a.navWidth === b.navWidth
  && a.listWidth === b.listWidth
  && a.railWidth === b.railWidth
  && a.navVisible === b.navVisible
  && a.railVisible === b.railVisible
  && a.centerSplitRatio === b.centerSplitRatio;

type LayoutStorage = Pick<Storage, "getItem" | "setItem">;

export interface LayoutStore {
  getState(): LayoutState;
  update(partial: LayoutUpdate): void;
  subscribe(listener: () => void): () => void;
  flush(): void;
}

export function createLayoutStore(storage?: LayoutStorage): LayoutStore {
  let state = deserializeLayout(storage?.getItem(LAYOUT_STORAGE_KEY));
  const listeners = new Set<() => void>();
  let pending: ReturnType<typeof setTimeout> | undefined;
  const persist = () => {
    pending = undefined;
    try {
      storage?.setItem(LAYOUT_STORAGE_KEY, serializeLayout(state));
    } catch {
      // Storage may be full or unavailable; the layout simply stays in-memory.
    }
  };
  return {
    getState: () => state,
    update(partial) {
      const next = clampLayout({ ...state, ...partial });
      if (sameLayout(state, next)) return;
      state = next;
      for (const listener of listeners) listener();
      if (pending !== undefined) clearTimeout(pending);
      pending = setTimeout(persist, PERSIST_DEBOUNCE_MS);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    flush() {
      if (pending === undefined) return;
      clearTimeout(pending);
      persist();
    },
  };
}

const resolveStorage = (): LayoutStorage | undefined => {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
};

let sharedStore: LayoutStore | undefined;
const getSharedStore = (): LayoutStore => {
  sharedStore ??= createLayoutStore(resolveStorage());
  return sharedStore;
};

export function useLayoutState(): [LayoutState, LayoutStore["update"]] {
  const store = getSharedStore();
  const state = useSyncExternalStore(store.subscribe, store.getState);
  useEffect(() => {
    const flush = () => store.flush();
    window.addEventListener("beforeunload", flush);
    return () => window.removeEventListener("beforeunload", flush);
  }, [store]);
  return [state, store.update];
}
