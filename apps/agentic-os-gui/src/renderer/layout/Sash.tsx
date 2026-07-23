import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

export const SASH_KEYBOARD_STEP_PX = 16;

interface SashMathOptions {
  min: number;
  max: number;
  /** Pixels represented by one unit of value; ratio sashes pass their container width. Defaults to 1. */
  pixelsPerUnit?: number;
  /** Set when the resized panel sits to the right of the divider, so dragging right shrinks it. */
  invert?: boolean;
}

const clampValue = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export function sashDragValue(startValue: number, deltaPx: number, options: SashMathOptions): number {
  const pixelsPerUnit = options.pixelsPerUnit !== undefined && options.pixelsPerUnit > 0 ? options.pixelsPerUnit : 1;
  const direction = options.invert ? -1 : 1;
  return clampValue(startValue + (direction * deltaPx) / pixelsPerUnit, options.min, options.max);
}

export function sashKeyboardValue(value: number, key: string, options: SashMathOptions): number | undefined {
  if (key !== "ArrowLeft" && key !== "ArrowRight") return undefined;
  const deltaPx = key === "ArrowRight" ? SASH_KEYBOARD_STEP_PX : -SASH_KEYBOARD_STEP_PX;
  return sashDragValue(value, deltaPx, options);
}

interface SashProps {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange(next: number): void;
  onReset(): void;
  invert?: boolean;
  getPixelsPerUnit?(): number;
}

interface ActiveDrag {
  pointerId: number;
  startX: number;
  startValue: number;
  pixelsPerUnit: number;
}

export function Sash({ label, value, min, max, onChange, onReset, invert, getPixelsPerUnit }: SashProps) {
  const drag = useRef<ActiveDrag | undefined>(undefined);
  const [dragging, setDragging] = useState(false);
  const resolvePixelsPerUnit = () => {
    const pixels = getPixelsPerUnit?.() ?? 1;
    return pixels > 0 ? pixels : 1;
  };
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startValue: value, pixelsPerUnit: resolvePixelsPerUnit() };
    setDragging(true);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    onChange(sashDragValue(active.startValue, event.clientX - active.startX, { min, max, pixelsPerUnit: active.pixelsPerUnit, invert }));
  };
  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = undefined;
    setDragging(false);
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const next = sashKeyboardValue(value, event.key, { min, max, pixelsPerUnit: resolvePixelsPerUnit(), invert });
    if (next === undefined) return;
    event.preventDefault();
    onChange(next);
  };
  return (
    <div
      className="sash"
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(value * 100) / 100}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      data-dragging={dragging}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
    />
  );
}
