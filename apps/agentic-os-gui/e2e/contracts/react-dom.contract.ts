/**
 * Contract test: react-dom
 * Validates the API surface used by this project.
 *
 * Renderer usage: `import ReactDOM from "react-dom/client"` +
 * ReactDOM.createRoot(...).render(...) in src/renderer/main.tsx.
 */
import { createElement, version as reactVersion } from "react";
import ReactDOM from "react-dom/client";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import { version as reactDomVersion } from "react-dom";
import { describe, expect, it } from "vitest";

describe("react-dom contract", () => {
  it("react-dom/client default export exposes createRoot as main.tsx uses it", () => {
    expect(typeof ReactDOM.createRoot).toBe("function");
    expect(typeof createRoot).toBe("function");
  });

  it("renders React elements produced by the installed react version", () => {
    // A react/react-dom version mismatch throws here — this is the pairing check.
    expect(renderToStaticMarkup(createElement("p", null, "x"))).toBe("<p>x</p>");
    expect(typeof renderToString).toBe("function");
  });

  it("react-dom version matches react (packages must upgrade together)", () => {
    expect(reactDomVersion).toBe(reactVersion);
  });
});
