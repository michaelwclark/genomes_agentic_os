import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LAYOUT_STORAGE_KEY,
  clampLayout,
  createLayoutStore,
  defaultLayout,
  deserializeLayout,
  layoutBounds,
  serializeLayout,
} from "../src/renderer/layout/layoutState";
import { SASH_KEYBOARD_STEP_PX, sashDragValue, sashKeyboardValue } from "../src/renderer/layout/Sash";

const memoryStorage = (initial?: string) => {
  const map = new Map<string, string>();
  if (initial !== undefined) map.set(LAYOUT_STORAGE_KEY, initial);
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: vi.fn((key: string, value: string) => { map.set(key, value); }),
  };
};

describe("layout state", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("clamps every resizable dimension to its bounds", () => {
    const clamped = clampLayout({ ...defaultLayout, navWidth: 20, listWidth: 5000, railWidth: 0, centerSplitRatio: 0.9 });
    expect(clamped.navWidth).toBe(layoutBounds.navWidth.min);
    expect(clamped.listWidth).toBe(layoutBounds.listWidth.max);
    expect(clamped.railWidth).toBe(layoutBounds.railWidth.min);
    expect(clamped.centerSplitRatio).toBe(layoutBounds.centerSplitRatio.max);
    expect(clampLayout(defaultLayout)).toEqual(defaultLayout);
  });

  it("round-trips serialize and deserialize", () => {
    const state = { ...defaultLayout, navWidth: 300, navVisible: false, centerSplitRatio: 0.3 };
    expect(deserializeLayout(serializeLayout(state))).toEqual(state);
  });

  it("falls back to defaults on garbage payloads", () => {
    expect(deserializeLayout(undefined)).toEqual(defaultLayout);
    expect(deserializeLayout(null)).toEqual(defaultLayout);
    expect(deserializeLayout("")).toEqual(defaultLayout);
    expect(deserializeLayout("{not json")).toEqual(defaultLayout);
    expect(deserializeLayout("42")).toEqual(defaultLayout);
    expect(deserializeLayout('{"schemaVersion":2,"navWidth":300}')).toEqual(defaultLayout);
  });

  it("repairs individually corrupt fields and clamps out-of-range values", () => {
    const raw = '{"schemaVersion":1,"navWidth":"wide","listWidth":9999,"railWidth":250,"navVisible":"yes","railVisible":false,"centerSplitRatio":null}';
    expect(deserializeLayout(raw)).toEqual({
      ...defaultLayout,
      listWidth: layoutBounds.listWidth.max,
      railWidth: 250,
      railVisible: false,
    });
  });

  it("hydrates the store from storage and notifies subscribers on real changes only", () => {
    const storage = memoryStorage(serializeLayout({ ...defaultLayout, navWidth: 320 }));
    const store = createLayoutStore(storage);
    expect(store.getState().navWidth).toBe(320);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.update({ navWidth: 9999 });
    expect(store.getState().navWidth).toBe(layoutBounds.navWidth.max);
    expect(listener).toHaveBeenCalledTimes(1);
    store.update({ navWidth: 9999 });
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.update({ navWidth: 200 });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("debounces persistence into a single trailing write", () => {
    vi.useFakeTimers();
    const storage = memoryStorage();
    const store = createLayoutStore(storage);
    store.update({ listWidth: 400 });
    store.update({ listWidth: 410 });
    store.update({ listWidth: 420 });
    expect(storage.setItem).not.toHaveBeenCalled();
    vi.advanceTimersByTime(149);
    expect(storage.setItem).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(storage.setItem).toHaveBeenCalledTimes(1);
    expect(deserializeLayout(storage.getItem(LAYOUT_STORAGE_KEY)).listWidth).toBe(420);
  });

  it("flushes pending state immediately and only when dirty", () => {
    vi.useFakeTimers();
    const storage = memoryStorage();
    const store = createLayoutStore(storage);
    store.flush();
    expect(storage.setItem).not.toHaveBeenCalled();
    store.update({ railVisible: false });
    store.flush();
    expect(storage.setItem).toHaveBeenCalledTimes(1);
    expect(deserializeLayout(storage.getItem(LAYOUT_STORAGE_KEY)).railVisible).toBe(false);
    vi.advanceTimersByTime(500);
    expect(storage.setItem).toHaveBeenCalledTimes(1);
  });
});

describe("sash math", () => {
  it("converts pointer deltas into clamped values", () => {
    expect(sashDragValue(230, 40, { min: 170, max: 340 })).toBe(270);
    expect(sashDragValue(230, -400, { min: 170, max: 340 })).toBe(170);
    expect(sashDragValue(230, 400, { min: 170, max: 340 })).toBe(340);
  });

  it("inverts direction for panels on the right of the divider", () => {
    expect(sashDragValue(270, 30, { min: 220, max: 420, invert: true })).toBe(240);
    expect(sashDragValue(270, -30, { min: 220, max: 420, invert: true })).toBe(300);
  });

  it("scales ratio sashes by their container width", () => {
    expect(sashDragValue(0.5, 100, { min: 0.25, max: 0.75, pixelsPerUnit: 1000 })).toBeCloseTo(0.6, 10);
    expect(sashDragValue(0.5, -1000, { min: 0.25, max: 0.75, pixelsPerUnit: 1000 })).toBe(0.25);
    expect(sashDragValue(0.5, 1000, { min: 0.25, max: 0.75, pixelsPerUnit: 1000 })).toBe(0.75);
  });

  it("moves 16px per arrow press and ignores other keys", () => {
    expect(sashKeyboardValue(230, "ArrowRight", { min: 170, max: 340 })).toBe(230 + SASH_KEYBOARD_STEP_PX);
    expect(sashKeyboardValue(230, "ArrowLeft", { min: 170, max: 340 })).toBe(230 - SASH_KEYBOARD_STEP_PX);
    expect(sashKeyboardValue(335, "ArrowRight", { min: 170, max: 340 })).toBe(340);
    expect(sashKeyboardValue(270, "ArrowRight", { min: 220, max: 420, invert: true })).toBe(270 - SASH_KEYBOARD_STEP_PX);
    expect(sashKeyboardValue(230, "Enter", { min: 170, max: 340 })).toBeUndefined();
    expect(sashKeyboardValue(230, "ArrowUp", { min: 170, max: 340 })).toBeUndefined();
  });
});
