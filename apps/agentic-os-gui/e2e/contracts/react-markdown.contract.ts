/**
 * Contract test: react-markdown
 * Validates the API surface used by this project.
 *
 * Renderer usage (src/renderer/components/ConversationView.tsx):
 * `<ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>`.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";

describe("react-markdown contract", () => {
  it("default export is a component function", () => {
    expect(typeof ReactMarkdown).toBe("function");
  });

  it("renders markdown children with remarkPlugins=[remarkGfm] as ConversationView does", () => {
    const markdown = [
      "# Title",
      "",
      "| a | b |",
      "| - | - |",
      "| 1 | 2 |",
      "",
      "~~gone~~",
    ].join("\n");
    const html = renderToStaticMarkup(
      createElement(ReactMarkdown, { remarkPlugins: [remarkGfm], children: markdown })
    );
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain("<table>");
    expect(html).toContain("<del>gone</del>");
  });

  it("renders plain markdown without plugins (baseline surface)", () => {
    const html = renderToStaticMarkup(createElement(ReactMarkdown, { children: "**bold**" }));
    expect(html).toContain("<strong>bold</strong>");
  });
});
