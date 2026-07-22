/**
 * Contract test: typescript
 * Validates the API surface used by this project.
 *
 * Usage: `tsc --noEmit` drives the typecheck script against tsconfig.json
 * (jsx: react-jsx, module: ESNext, target: ES2022). This contract exercises
 * the compiler API on a TSX snippet with those options.
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

describe("typescript contract", () => {
  it("exposes a semver version", () => {
    expect(ts.version).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("enums cover the tsconfig values this app uses", () => {
    expect(ts.JsxEmit.ReactJSX).toBeDefined();
    expect(ts.ModuleKind.ESNext).toBeDefined();
    expect(ts.ScriptTarget.ES2022).toBeDefined();
  });

  it("transpileModule compiles TSX with jsx: react-jsx as tsconfig does", () => {
    const source = 'const value: string = "hi";\nexport const el = <div title="x">{value}</div>;\n';
    const result = ts.transpileModule(source, {
      compilerOptions: {
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: "sample.tsx",
    });
    expect(result.outputText).toContain("react/jsx-runtime");
    expect(result.outputText).toContain("jsx");
    expect(result.diagnostics ?? []).toHaveLength(0);
  });
});
