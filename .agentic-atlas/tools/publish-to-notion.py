#!/usr/bin/env python3
"""Publish the docs/ handbook to Genome's Notion as a hub page + child pages.

Markdown-first stays authoritative (in-repo); this mirrors it into Notion as a
browsable bundle. Uses the GENOMES_NOTION_PAT integration token (workspace
"Genome's Notion") via the direct API — never prints the token.

Conversion scope (block-level): headings (#/##/###), paragraphs, bulleted and
numbered lists, code fences, blockquotes->callout, tables->code block (readable
monospace; faithful Notion tables are intentionally skipped for reliability),
images->callout placeholder (diagram PNGs are not uploaded in this pass; they
live in the repo), and --- dividers. Inline: links, **bold**, `code`.

Usage:
  python3 .agentic-atlas/tools/publish-to-notion.py --parent <page_id> [--only NN-name.md]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
DOCS = Path(__file__).resolve().parents[2] / "docs"
TOKEN = os.environ.get("GENOMES_NOTION_PAT", "")
_UPLOADS: dict[str, str] = {}  # rel path -> file_upload id (cache, one upload per image)


def _req(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:  # surface the API error body
        raise SystemExit(f"Notion API {method} {path} failed: {exc.code}\n{exc.read().decode()}")


# ---- inline rich-text parsing (links, bold, code) ----
_INLINE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`")


def rich(text: str) -> list[dict]:
    out: list[dict] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(_t(text[pos:m.start()]))
        if m.group(1) is not None:  # link
            out.append(_t(m.group(1), link=m.group(2)))
        elif m.group(3) is not None:  # bold
            out.append(_t(m.group(3), bold=True))
        elif m.group(4) is not None:  # code
            out.append(_t(m.group(4), code=True))
        pos = m.end()
    if pos < len(text):
        out.append(_t(text[pos:]))
    return out or [_t("")]


def _t(content: str, *, bold=False, code=False, link: str | None = None) -> dict:
    content = content[:2000]
    ann = {"bold": bold, "code": code}
    obj: dict = {"type": "text", "text": {"content": content}, "annotations": ann}
    if link and link.startswith(("http://", "https://")):
        obj["text"]["link"] = {"url": link}
    return obj


def _para(rt): return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}


def _is_sep_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _table_block(rows_md: list[str]) -> dict | None:
    """Build a real Notion table block from markdown table rows."""
    grid = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in rows_md]
    grid = [r for r in grid if not _is_sep_row(r)]
    if not grid:
        return None
    width = min(max(len(r) for r in grid), 100)

    def cells(r: list[str]) -> list[list]:
        r = (r + [""] * width)[:width]
        return [rich(c) if c.strip() else [] for c in r]

    children = [{"object": "block", "type": "table_row", "table_row": {"cells": cells(r)}} for r in grid]
    return {"object": "block", "type": "table", "table": {
        "table_width": width, "has_column_header": True, "has_row_header": False, "children": children}}


def upload_image(rel: str) -> str | None:
    """Upload a local image via the Notion file-upload API; return file_upload id (cached)."""
    if rel in _UPLOADS:
        return _UPLOADS[rel]
    path = DOCS / rel
    if not path.is_file():
        print(f"  ! image not found: {rel}", flush=True)
        return None
    created = _req("POST", "/file_uploads", {"filename": path.name, "content_type": "image/png"})
    fid, url = created["id"], created["upload_url"]
    boundary = "----notionform" + fid.replace("-", "")[:18]
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        print(f"  ! image upload failed: {rel} ({exc.code})", flush=True)
        return None
    _UPLOADS[rel] = fid
    return fid


def md_to_blocks(md: str) -> list[dict]:
    blocks: list[dict] = []
    lines = md.splitlines()
    # Drop a leading H1 — the Notion page title (from properties) already shows it.
    _i0 = 0
    while _i0 < len(lines) and not lines[_i0].strip():
        _i0 += 1
    if _i0 < len(lines) and lines[_i0].startswith("# "):
        del lines[_i0]
    i = 0
    while i < len(lines):
        line = lines[i]
        # HTML comments (diagram-source breadcrumbs) -> skip
        if line.strip().startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        # code fence
        if line.startswith("```"):
            lang = line[3:].strip() or "plain text"
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            blocks.append({"object": "block", "type": "code", "code": {
                "language": _lang(lang), "rich_text": [_t("\n".join(buf)[:2000])]}})
            continue
        # table -> real Notion table block (collect consecutive | rows)
        if line.lstrip().startswith("|"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                buf.append(lines[i].strip()); i += 1
            tb = _table_block(buf)
            if tb:
                blocks.append(tb)
            continue
        # image -> upload the PNG and embed a real image block (callout fallback)
        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
        if m:
            alt, rel = m.group(1), m.group(2)
            fid = upload_image(rel)
            if fid:
                blocks.append({"object": "block", "type": "image", "image": {
                    "type": "file_upload", "file_upload": {"id": fid},
                    "caption": rich(alt) if alt.strip() else []}})
            else:
                blocks.append({"object": "block", "type": "callout", "callout": {
                    "icon": {"type": "emoji", "emoji": "📊"},
                    "rich_text": [_t(f"Diagram — {alt[:1800]} (repo: docs/{rel})")]}})
            i += 1
            continue
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            htype = f"heading_{min(level, 3)}"
            blocks.append({"object": "block", "type": htype, htype: {"rich_text": rich(text)}})
            i += 1
            continue
        if stripped.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            blocks.append({"object": "block", "type": "callout", "callout": {
                "icon": {"type": "emoji", "emoji": "💡"}, "rich_text": rich(" ".join(buf))}})
            continue
        m = re.match(r"^(\s*)[-*] (.*)", line)
        if m:
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": rich(m.group(2))}})
            i += 1
            continue
        m = re.match(r"^(\s*)\d+\. (.*)", line)
        if m:
            blocks.append({"object": "block", "type": "numbered_list_item",
                           "numbered_list_item": {"rich_text": rich(m.group(2))}})
            i += 1
            continue
        blocks.append(_para(rich(stripped)))
        i += 1
    return blocks


# Notion's code-block language enum is fixed; anything else must fall back to
# "plain text" (note: "text" is NOT valid — it must be "plain text").
_ALIAS = {"text": "plain text", "txt": "plain text", "md": "markdown", "sh": "bash", "": "plain text"}
_VALID = {
    "bash", "shell", "python", "json", "yaml", "markdown", "toml", "xml", "html",
    "javascript", "typescript", "sql", "diff", "plain text", "mermaid", "go",
    "rust", "c", "c++", "java", "docker", "graphql", "css",
}


def _lang(l: str) -> str:
    l = _ALIAS.get(l.lower().strip(), l.lower().strip())
    return l if l in _VALID else "plain text"


def create_page(parent_id: str, title: str, blocks: list[dict], icon: str | None = None) -> dict:
    payload: dict = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "children": blocks[:100],
    }
    if icon:
        payload["icon"] = {"type": "emoji", "emoji": icon}
    page = _req("POST", "/pages", payload)
    # append remaining blocks in chunks of 100
    rest = blocks[100:]
    while rest:
        _req("PATCH", f"/blocks/{page['id']}/children", {"children": rest[:100]})
        rest = rest[100:]
    return page


def existing_titles(parent_id: str) -> set[str]:
    """Titles of child pages already under a parent — for idempotent resume."""
    titles: set[str] = set()
    cursor = None
    while True:
        path = f"/blocks/{parent_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        d = _req("GET", path)
        for b in d.get("results", []):
            if b.get("type") == "child_page":
                titles.add(b["child_page"]["title"])
        if not d.get("has_more"):
            return titles
        cursor = d.get("next_cursor")


def main() -> int:
    if not TOKEN:
        raise SystemExit("GENOMES_NOTION_PAT is not set")
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True, help="Parent page ID in Genome's Notion")
    ap.add_argument("--hub-title", default="Genome's Agentic OS — Handbook")
    ap.add_argument("--only", help="Publish a single docs file (e.g. 00-overview.md) under the parent, for testing")
    ap.add_argument("--hub", help="Existing hub page ID to resume under (skips hub creation and already-created sections)")
    args = ap.parse_args()

    if args.only:
        f = DOCS / args.only
        title = f.stem.replace("-", " ").title()
        page = create_page(args.parent, title, md_to_blocks(f.read_text()), icon="📄")
        print(f"created: {page['url']}")
        return 0

    # Hub page from docs/README.md, then each NN-*.md as a child of the hub.
    # --hub resumes under an existing hub, skipping sections already created.
    if args.hub:
        hub_id = args.hub
        existing = existing_titles(hub_id)
        print(f"resuming under hub {hub_id}; {len(existing)} sections already present", flush=True)
    else:
        hub = create_page(args.parent, args.hub_title, md_to_blocks((DOCS / "README.md").read_text()), icon="🗺️")
        hub_id = hub["id"]
        existing = set()
        print(f"hub: {hub['url']}", flush=True)
    for f in sorted(DOCS.glob("[0-9][0-9]-*.md")):
        first = next((ln for ln in f.read_text().splitlines() if ln.startswith("# ")), None)
        title = first[2:].strip() if first else f.stem.replace("-", " ").title()
        if title in existing:
            print(f"  = skip (exists): {title}", flush=True)
            continue
        page = create_page(hub_id, title, md_to_blocks(f.read_text()), icon="📄")
        print(f"  + {title} -> {page['url']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
