/**
 * Contract test: remark-gfm
 * Validates the API surface used by this project.
 *
 * Renderer usage: passed to react-markdown as `remarkPlugins={[remarkGfm]}` to
 * enable GitHub-flavored markdown (tables, strikethrough) in conversations.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";

const TABLE_MARKDOWN = ["| a | b |", "| - | - |", "| 1 | 2 |"].join("\n");

describe("remark-gfm contract", () => {
  it("default export is a plugin function", () => {
    expect(typeof remarkGfm).toBe("function");
  });

  it("enables GFM tables when passed via remarkPlugins (our only call shape)", () => {
    const withPlugin = renderToStaticMarkup(
      createElement(ReactMarkdown, { remarkPlugins: [remarkGfm], children: TABLE_MARKDOWN })
    );
    const withoutPlugin = renderToStaticMarkup(
      createElement(ReactMarkdown, { children: TABLE_MARKDOWN })
    );
    expect(withPlugin).toContain("<table>");
    expect(withoutPlugin).not.toContain("<table>");
  });
});
