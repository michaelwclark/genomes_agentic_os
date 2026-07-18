"""Self-contained offline HTML projection for Agentic OS cockpit snapshots."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any


_TABS = (
    "Today",
    "Work",
    "Conversations",
    "Reviews",
    "Reports",
    "Automations",
    "Runtime",
    "Sources",
    "Hosts",
    "Hygiene",
)


def _script_safe_json(snapshot: dict[str, Any]) -> str:
    """Serialize JSON without permitting data to terminate its script element."""

    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_cockpit_html(snapshot: dict[str, Any]) -> str:
    """Render *snapshot* as a polished, dependency-free offline cockpit."""

    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dictionary")

    tab_buttons = "\n".join(
        f'        <button class="tab" id="tab-{name.lower()}" role="tab" '
        f'aria-controls="panel" aria-selected="{str(index == 0).lower()}" '
        f'tabindex="{0 if index == 0 else -1}" data-tab="{name.lower()}">{name}</button>'
        for index, name in enumerate(_TABS)
    )
    snapshot_json = _script_safe_json(snapshot)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'">
  <title>Agentic OS Cockpit</title>
  <style>
    :root {{
      --ink: #f7f8f4; --muted: #a8b1ad; --dim: #727c78;
      --canvas: #080b0a; --surface: #111614; --raised: #18201d;
      --line: #2b3631; --line-soft: #202925; --accent: #a6f4c5;
      --accent-strong: #57d999; --warning: #ffd37a; --danger: #ff938a;
      --info: #8dc9ff; --radius: 18px; --shadow: 0 18px 60px #0008;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: var(--canvas); color: var(--ink); }}
    body {{ margin: 0; min-height: 100vh; background:
      radial-gradient(circle at 12% -10%, #183829 0, transparent 32rem),
      radial-gradient(circle at 92% 5%, #142c33 0, transparent 30rem), var(--canvas); }}
    button, input, select {{ font: inherit; }}
    button {{ color: inherit; }}
    .shell {{ width: min(1520px, 100%); margin: 0 auto; padding: 30px clamp(18px, 4vw, 58px) 60px; }}
    .masthead {{ display: grid; grid-template-columns: 1fr auto; gap: 26px; align-items: end; margin-bottom: 28px; }}
    .eyebrow {{ color: var(--accent); font-size: .74rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ margin: 8px 0 7px; max-width: 900px; font-size: clamp(2rem, 5vw, 4.8rem); line-height: .96; letter-spacing: -.055em; }}
    .subtitle {{ color: var(--muted); max-width: 780px; margin: 0; font-size: clamp(.95rem, 1.5vw, 1.12rem); line-height: 1.6; }}
    .snapshot-meta {{ text-align: right; color: var(--muted); font-size: .78rem; line-height: 1.65; max-width: 360px; }}
    .snapshot-meta strong {{ color: var(--ink); display: block; font-size: .82rem; }}
    .tabs {{ display: flex; gap: 8px; overflow-x: auto; padding: 6px; margin: 0 0 20px; border: 1px solid var(--line); border-radius: 16px; background: #0d1210cc; scrollbar-width: thin; }}
    .tab {{ border: 0; border-radius: 11px; padding: 10px 14px; background: transparent; color: var(--muted); cursor: pointer; white-space: nowrap; transition: .18s ease; }}
    .tab:hover {{ color: var(--ink); background: var(--raised); }}
    .tab[aria-selected="true"] {{ color: #07100b; background: var(--accent); font-weight: 800; box-shadow: 0 5px 24px #57d99935; }}
    .toolbar {{ position: sticky; top: 10px; z-index: 5; display: grid; grid-template-columns: minmax(240px, 1fr) minmax(150px, 220px) auto; gap: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 16px; background: #0d1210ee; box-shadow: 0 10px 36px #0007; backdrop-filter: blur(15px); }}
    .control {{ width: 100%; min-height: 43px; border: 1px solid var(--line); border-radius: 11px; color: var(--ink); background: var(--surface); padding: 0 13px; outline: none; }}
    .control:focus {{ border-color: var(--accent-strong); box-shadow: 0 0 0 3px #57d99922; }}
    .result-count {{ align-self: center; min-width: 90px; color: var(--muted); text-align: right; font-size: .82rem; }}
    #panel {{ min-height: 420px; outline: none; }}
    .section-head {{ display: flex; justify-content: space-between; gap: 20px; align-items: end; padding: 34px 2px 18px; }}
    .section-head h2 {{ margin: 0; font-size: clamp(1.5rem, 3vw, 2.45rem); letter-spacing: -.04em; }}
    .section-head p {{ margin: 7px 0 0; color: var(--muted); max-width: 680px; line-height: 1.5; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric {{ min-height: 128px; border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; background: linear-gradient(145deg, #18201ddd, #0f1412dd); }}
    .metric strong {{ display: block; margin-top: 22px; font-size: 2.15rem; letter-spacing: -.05em; }}
    .metric span {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .1em; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; }}
    .card {{ position: relative; display: flex; flex-direction: column; min-height: 218px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius); background: linear-gradient(155deg, #18201df2, #0f1412f2); box-shadow: 0 10px 36px #0003; transition: transform .18s ease, border-color .18s ease; }}
    .card:hover {{ transform: translateY(-2px); border-color: #45554e; }}
    .card-button {{ flex: 1; border: 0; background: transparent; text-align: left; padding: 19px; cursor: pointer; }}
    .card-top {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .card h3 {{ margin: 13px 0 9px; font-size: 1.05rem; line-height: 1.3; letter-spacing: -.015em; }}
    .card p {{ margin: 0; color: var(--muted); line-height: 1.52; font-size: .9rem; }}
    .kind {{ color: var(--info); font-size: .69rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    .status {{ border: 1px solid var(--line); border-radius: 99px; padding: 4px 8px; color: var(--muted); font-size: .68rem; white-space: nowrap; }}
    .status[data-tone="danger"] {{ color: var(--danger); border-color: #743c38; background: #381c1b; }}
    .status[data-tone="warning"] {{ color: var(--warning); border-color: #725c2e; background: #302713; }}
    .status[data-tone="good"] {{ color: var(--accent); border-color: #2f674b; background: #142d21; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 17px; }}
    .tag {{ color: #bac4bf; background: #222c28; border-radius: 6px; padding: 4px 7px; font-size: .67rem; }}
    .card-foot {{ display: flex; gap: 8px; align-items: center; padding: 10px 19px; border-top: 1px solid var(--line-soft); color: var(--dim); font-size: .71rem; }}
    .card-foot span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .empty {{ grid-column: 1 / -1; display: grid; place-items: center; min-height: 300px; border: 1px dashed #39443f; border-radius: var(--radius); padding: 30px; color: var(--muted); text-align: center; background: #0e1311aa; }}
    .empty strong {{ display: block; color: var(--ink); margin-bottom: 8px; font-size: 1.1rem; }}
    dialog {{ width: min(720px, calc(100vw - 24px)); max-height: calc(100vh - 32px); margin: 16px 16px 16px auto; padding: 0; border: 1px solid var(--line); border-radius: 22px; color: var(--ink); background: #111614; box-shadow: var(--shadow); }}
    dialog::backdrop {{ background: #000a; backdrop-filter: blur(5px); }}
    .drawer-head {{ position: sticky; top: 0; z-index: 2; display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; padding: 22px; border-bottom: 1px solid var(--line); background: #111614f5; backdrop-filter: blur(12px); }}
    .drawer-head h2 {{ margin: 5px 0 0; font-size: 1.5rem; letter-spacing: -.03em; }}
    .icon-button {{ width: 38px; height: 38px; flex: 0 0 auto; border: 1px solid var(--line); border-radius: 50%; background: var(--raised); cursor: pointer; }}
    .drawer-body {{ padding: 22px; }}
    .drawer-summary {{ color: var(--muted); font-size: 1rem; line-height: 1.65; margin: 0 0 20px; }}
    .detail-list {{ display: grid; gap: 1px; overflow: hidden; border: 1px solid var(--line); border-radius: 13px; background: var(--line); }}
    .detail-row {{ display: grid; grid-template-columns: 150px 1fr; gap: 16px; padding: 12px 14px; background: var(--surface); }}
    .detail-key {{ color: var(--dim); font-size: .72rem; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }}
    .detail-value {{ min-width: 0; color: #d6ddd9; font: .82rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .copy-button {{ margin-top: 16px; border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; color: var(--accent); background: var(--raised); cursor: pointer; }}
    .diagnostic {{ margin: 16px 0 0; border-left: 3px solid var(--warning); padding: 10px 14px; color: var(--muted); background: #30271366; }}
    .noscript {{ margin: 20px 0; padding: 16px; border: 1px solid #743c38; border-radius: 12px; color: var(--danger); }}
    .visually-hidden {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }}
    :focus-visible {{ outline: 3px solid var(--accent-strong); outline-offset: 3px; }}
    @media (max-width: 1000px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .metrics {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 680px) {{
      .shell {{ padding: 22px 14px 40px; }} .masthead {{ grid-template-columns: 1fr; }}
      .snapshot-meta {{ text-align: left; }} .toolbar {{ grid-template-columns: 1fr; top: 4px; }}
      .result-count {{ text-align: left; padding: 0 4px 3px; }} .grid {{ grid-template-columns: 1fr; }}
      .detail-row {{ grid-template-columns: 1fr; gap: 5px; }} dialog {{ margin: 12px 6px; max-height: calc(100vh - 24px); }}
    }}
    @media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; transition: none !important; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="masthead">
      <div>
        <div class="eyebrow">Engineering lead workspace</div>
        <h1>Agentic OS Cockpit</h1>
        <p class="subtitle">A local, read-only view of current work, conversations, reviews, reports, runtime surfaces, and cleanup signals.</p>
      </div>
      <div class="snapshot-meta" id="snapshot-meta" aria-live="polite"></div>
    </header>
    <nav class="tabs" role="tablist" aria-label="Cockpit sections">
{tab_buttons}
    </nav>
    <div class="toolbar" role="search">
      <label class="visually-hidden" for="search">Search this section</label>
      <input class="control" id="search" type="search" placeholder="Search titles, summaries, tags, projects…" autocomplete="off">
      <label class="visually-hidden" for="status-filter">Filter by status</label>
      <select class="control" id="status-filter"><option value="">All statuses</option></select>
      <div class="result-count" id="result-count" aria-live="polite"></div>
    </div>
    <main id="panel" role="tabpanel" aria-labelledby="tab-today" tabindex="0"></main>
    <noscript><div class="noscript">This offline cockpit needs JavaScript enabled to render its embedded snapshot.</div></noscript>
  </div>
  <dialog id="detail-drawer" aria-labelledby="drawer-title">
    <div class="drawer-head">
      <div><div class="eyebrow" id="drawer-kind">Detail</div><h2 id="drawer-title">Item detail</h2></div>
      <button class="icon-button" id="drawer-close" type="button" aria-label="Close detail">×</button>
    </div>
    <div class="drawer-body" id="drawer-body"></div>
  </dialog>
  <script id="cockpit-data" type="application/json">{snapshot_json}</script>
  <script>
  (() => {{
    'use strict';
    const raw = document.getElementById('cockpit-data').textContent;
    let snapshot = {{}};
    try {{ snapshot = JSON.parse(raw); }} catch (error) {{ snapshot = {{ diagnostics: [{{severity:'error', summary:'Snapshot JSON could not be parsed.', detail:String(error)}}] }}; }}

    const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    const panel = document.getElementById('panel');
    const search = document.getElementById('search');
    const statusFilter = document.getElementById('status-filter');
    const resultCount = document.getElementById('result-count');
    const drawer = document.getElementById('detail-drawer');
    const drawerTitle = document.getElementById('drawer-title');
    const drawerKind = document.getElementById('drawer-kind');
    const drawerBody = document.getElementById('drawer-body');
    let activeTab = 'today';

    const descriptions = {{
      today: 'The signals most likely to need attention now.', work: 'Routed work items and their next actions.',
      conversations: 'Captured Claude and Codex conversation metadata.', reviews: 'Pull requests and review activity found in OS evidence.',
      reports: 'Layered summaries with canonical evidence paths.', automations: 'Declared programs, workflows, schedules, and latest receipts.',
      runtime: 'Authoritative named-queue depth, admission limits, worker capacity, and health.',
      sources: 'Configured watches, observed usage, and proposed coverage.', hosts: 'Declared hosts and last-known health receipts.',
      hygiene: 'Read-only findings with guarded follow-up commands.'
    }};
    const sectionMap = {{ work:'work_items', conversations:'conversations', reviews:'reviews', reports:'reports', automations:'automations', runtime:'runtime', hosts:'hosts', hygiene:'hygiene' }};
    const list = value => Array.isArray(value) ? value : [];
    const text = value => value === null || value === undefined ? '' : typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : JSON.stringify(value);
    const titleCase = value => String(value || '').replace(/[_-]+/g, ' ').replace(/\\b\\w/g, letter => letter.toUpperCase());
    const normalizedStatus = item => text(item.status || item.state || item.severity || item.phase || 'unknown').toLowerCase();
    const tone = status => /error|critical|blocked|failure|stale|danger/.test(status) ? 'danger' : /warn|pending|queued|unknown|triaged|captured/.test(status) ? 'warning' : /ok|healthy|complete|finished|merged|active|running|ready|good/.test(status) ? 'good' : 'neutral';
    const el = (name, className, value) => {{ const node = document.createElement(name); if (className) node.className = className; if (value !== undefined) node.textContent = text(value); return node; }};

    function sourceItems() {{
      const sources = snapshot.sources && typeof snapshot.sources === 'object' ? snapshot.sources : {{}};
      return ['configured','observed','suggestions'].flatMap(group => list(sources[group]).map(item => Object.assign({{source_group:group}}, item)));
    }}
    function sectionItems(tab) {{
      if (tab === 'sources') return sourceItems();
      if (tab === 'today') {{
        const runtime = list(snapshot.runtime).filter(item => tone(normalizedStatus(item)) !== 'good').slice(0, 6);
        const urgent = list(snapshot.hygiene).filter(item => tone(normalizedStatus(item)) !== 'good').slice(0, 6);
        const work = list(snapshot.work_items).filter(item => !/finished|archived|complete|dropped/.test(normalizedStatus(item))).slice(0, 6);
        const reviews = list(snapshot.reviews).filter(item => !/merged|closed|complete/.test(normalizedStatus(item))).slice(0, 4);
        const reports = list(snapshot.reports).slice(0, 3);
        return [...runtime.map(item => Object.assign({{today_group:'Runtime health'}}, item)), ...urgent.map(item => Object.assign({{today_group:'Needs attention'}}, item)), ...work.map(item => Object.assign({{today_group:'Active work'}}, item)), ...reviews.map(item => Object.assign({{today_group:'Reviews'}}, item)), ...reports.map(item => Object.assign({{today_group:'Recent reports'}}, item))];
      }}
      return list(snapshot[sectionMap[tab]]);
    }}
    function searchable(item) {{
      try {{ return JSON.stringify(item).toLowerCase(); }} catch (_) {{ return Object.values(item || {{}}).map(text).join(' ').toLowerCase(); }}
    }}
    function filtered(items) {{
      const query = search.value.trim().toLowerCase(); const status = statusFilter.value;
      return items.filter(item => (!query || searchable(item).includes(query)) && (!status || normalizedStatus(item) === status));
    }}
    function refreshStatuses(items) {{
      const selected = statusFilter.value;
      const statuses = Array.from(new Set(items.map(normalizedStatus).filter(Boolean))).sort();
      statusFilter.replaceChildren();
      const all = document.createElement('option'); all.value = ''; all.textContent = 'All statuses'; statusFilter.append(all);
      statuses.forEach(status => {{ const option = document.createElement('option'); option.value = status; option.textContent = titleCase(status); statusFilter.append(option); }});
      statusFilter.value = statuses.includes(selected) ? selected : '';
    }}
    function metric(label, value) {{ const node = el('div','metric'); node.append(el('span','',label), el('strong','',value)); return node; }}
    function renderMetrics() {{
      const metrics = el('div','metrics');
      const activeWork = list(snapshot.work_items).filter(item => !/finished|archived|complete|dropped/.test(normalizedStatus(item))).length;
      const attention = list(snapshot.hygiene).filter(item => tone(normalizedStatus(item)) !== 'good').length;
      const openReviews = list(snapshot.reviews).filter(item => !/merged|closed|complete/.test(normalizedStatus(item))).length;
      metrics.append(metric('Active work', activeWork), metric('Open reviews', openReviews), metric('Queue depth', (snapshot.summary || {{}}).queue_depth || 0), metric('Active workers', (snapshot.summary || {{}}).active_workers || 0), metric('Runtime health', (snapshot.summary || {{}}).runtime_health || 'unknown'), metric('Needs attention', attention));
      return metrics;
    }}
    function cardTitle(item) {{ return item.title || item.name || item.summary || item.id || 'Untitled item'; }}
    function cardSummary(item) {{ return item.summary || item.detail || item.next_action || item.reason || 'No summary captured.'; }}
    function cardKind(item) {{ return item.today_group || item.source_group || item.kind || item.report_type || item.type || activeTab; }}
    function renderCard(item) {{
      const card = el('article','card'); const button = el('button','card-button'); button.type = 'button'; button.setAttribute('aria-label', 'Open detail for ' + cardTitle(item));
      const top = el('div','card-top'); top.append(el('span','kind',titleCase(cardKind(item))));
      const status = normalizedStatus(item); const badge = el('span','status',titleCase(status)); badge.dataset.tone = tone(status); top.append(badge);
      button.append(top, el('h3','',cardTitle(item)), el('p','',cardSummary(item)));
      const tags = list(item.tags).slice(0, 6); if (tags.length) {{ const tagRow = el('div','tags'); tags.forEach(tag => tagRow.append(el('span','tag',tag))); button.append(tagRow); }}
      button.addEventListener('click', () => openDetail(item));
      const foot = el('div','card-foot'); const route = [item.domain,item.project,item.work_item].filter(Boolean).join(' / '); foot.append(el('span','',route || item.updated_at || item.source || 'Local evidence')); card.append(button, foot); return card;
    }}
    function valueForDetail(value) {{ if (value && typeof value === 'object') return JSON.stringify(value, null, 2); return text(value); }}
    function openDetail(item) {{
      drawerTitle.textContent = cardTitle(item); drawerKind.textContent = titleCase(cardKind(item)); drawerBody.replaceChildren();
      drawerBody.append(el('p','drawer-summary',cardSummary(item)));
      const details = el('div','detail-list');
      Object.keys(item).sort().filter(key => !['title','name','summary'].includes(key)).forEach(key => {{
        const row = el('div','detail-row'); row.append(el('div','detail-key',titleCase(key)), el('div','detail-value',valueForDetail(item[key]))); details.append(row);
      }});
      drawerBody.append(details);
      const copy = el('button','copy-button','Copy item JSON'); copy.type = 'button'; copy.addEventListener('click', async () => {{ try {{ await navigator.clipboard.writeText(JSON.stringify(item, null, 2)); copy.textContent = 'Copied'; }} catch (_) {{ copy.textContent = 'Copy unavailable'; }} }}); drawerBody.append(copy);
      if (typeof drawer.showModal === 'function') drawer.showModal(); else drawer.setAttribute('open','');
    }}
    function render() {{
      const allItems = sectionItems(activeTab); refreshStatuses(allItems); const items = filtered(allItems); panel.replaceChildren();
      const heading = el('div','section-head'); const textBlock = el('div',''); textBlock.append(el('h2','',titleCase(activeTab)), el('p','',descriptions[activeTab])); heading.append(textBlock); panel.append(heading);
      if (activeTab === 'today') panel.append(renderMetrics());
      const grid = el('div','grid');
      if (!items.length) {{ const empty = el('div','empty'); const wrap = el('div',''); wrap.append(el('strong','',search.value || statusFilter.value ? 'No matching items' : 'Nothing captured here yet'), el('span','',search.value || statusFilter.value ? 'Try a broader search or remove the status filter.' : 'The cockpit stays usable while this optional source is empty.')); empty.append(wrap); grid.append(empty); }} else items.forEach(item => grid.append(renderCard(item)));
      panel.append(grid); resultCount.textContent = items.length + (items.length === 1 ? ' item' : ' items');
    }}
    function activate(tab, focus = false) {{
      activeTab = tab; search.value = ''; statusFilter.value = '';
      tabs.forEach(button => {{ const active = button.dataset.tab === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; if (active) panel.setAttribute('aria-labelledby', button.id); }});
      render(); if (focus) panel.focus();
    }}
    tabs.forEach((button, index) => {{
      button.addEventListener('click', () => activate(button.dataset.tab, true));
      button.addEventListener('keydown', event => {{ if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); let next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; tabs[next].focus(); activate(tabs[next].dataset.tab); }});
    }});
    search.addEventListener('input', render); statusFilter.addEventListener('change', render);
    document.getElementById('drawer-close').addEventListener('click', () => drawer.close());
    drawer.addEventListener('click', event => {{ if (event.target === drawer) drawer.close(); }});
    const meta = document.getElementById('snapshot-meta'); meta.append(el('strong','', snapshot.generated_at ? 'Snapshot ' + snapshot.generated_at : 'Local snapshot'));
    meta.append(document.createTextNode(snapshot.root ? 'Source: ' + snapshot.root : 'Read-only offline projection'));
    activate('today');
  }})();
  </script>
</body>
</html>
"""


def write_cockpit_html(snapshot: dict[str, Any], output_path: str | Path) -> Path:
    """Render *snapshot* to *output_path* and return the resolved artifact path."""

    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cockpit_html(snapshot), encoding="utf-8")
    return path.resolve()
