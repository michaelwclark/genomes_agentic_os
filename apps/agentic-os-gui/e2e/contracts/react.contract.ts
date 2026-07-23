/**
 * Contract test: react
 * Validates the API surface used by this project.
 *
 * Renderer usage: default React import (React.StrictMode), Fragment, and the
 * hooks useState/useEffect/useMemo/useRef/useCallback/useSyncExternalStore;
 * JSX is compiled with the react-jsx runtime (react/jsx-runtime).
 */
import React, {
  Fragment,
  StrictMode,
  createElement,
  useCallback,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  useEffect,
  version,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

describe("react contract", () => {
  it("exposes the hooks the renderer imports", () => {
    for (const hook of [useState, useEffect, useMemo, useRef, useCallback, useSyncExternalStore]) {
      expect(typeof hook).toBe("function");
    }
  });

  it("default export carries StrictMode and createElement (React.StrictMode usage)", () => {
    expect(React.StrictMode).toBe(StrictMode);
    expect(typeof React.createElement).toBe("function");
    expect(Fragment).toBeDefined();
  });

  it("render-phase hooks work inside a component render", () => {
    function Probe(): React.ReactElement {
      const [state] = useState("state");
      const memo = useMemo(() => `${state}-memo`, [state]);
      const ref = useRef("ref");
      const cb = useCallback(() => ref.current, []);
      const store = useSyncExternalStore(
        () => () => undefined,
        () => "store",
        () => "store"
      );
      return createElement("span", null, `${memo}:${cb()}:${store}`);
    }
    expect(renderToStaticMarkup(createElement(Probe))).toBe("<span>state-memo:ref:store</span>");
  });

  it("react-jsx runtime module exists with jsx/jsxs", async () => {
    const runtime = await import("react/jsx-runtime");
    expect(typeof runtime.jsx).toBe("function");
    expect(typeof runtime.jsxs).toBe("function");
    expect(runtime.Fragment).toBeDefined();
  });

  it("reports a semver version", () => {
    expect(version).toMatch(/^\d+\.\d+\.\d+/);
  });
});
