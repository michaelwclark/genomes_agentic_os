# Agentic OS Command Center — Design System

Companion to `src/renderer/theme/tokens.css`, the canonical token sheet. This
app is going from a handful of screens to roughly 100 (automation
dashboards, reporting engine, work-queue watchers, health dashboards,
admin). Every value in this document matches `tokens.css` exactly — if the
two ever disagree, the CSS file is the bug.

Ground truth for the current-state audit: `src/renderer/styles.css` (250
lines, ~150 ad hoc hex/spacing/radius values, 5 pre-existing custom
properties) and `src/shared/presentation.ts` (`modelColor()`, `compactAge()`).

---

## 1. Principles

- **Dark-first operator console, not a marketing surface.** This is a tool
  people stare at for hours while triaging automations. Optimize for low
  eye strain and fast scanning, not visual flourish.
- **Density with calm.** Screens will carry a lot of tabular/status data.
  Tight spacing is fine; visual noise is not — every added color or weight
  must earn its place by carrying meaning.
- **Color carries one meaning system-wide.** Teal (`--color-accent`) means
  interactive or healthy. Amber (`--color-warn`) means needs attention.
  Red (`--color-danger`) means failed. Never repurpose these for anything
  else (branding, decoration, categorical charting) — see §5 for why the
  data-viz palette deliberately avoids these hues.
- **oklch for computed identity.** Per-conversation model accents are not
  static tokens — `modelColor()` in `presentation.ts` computes
  `oklch(L C H)` at runtime from provider hue (openai 165 / anthropic 40 /
  unknown 255) × tier intensity × reasoning-effort bump. Static tokens and
  computed identity colors are two different systems that happen to share
  a color space; don't try to collapse one into the other.
- **Motion is restrained.** 120–160ms, `--ease-out`, no bounce, no spring
  physics. Motion confirms state changed; it should never be the thing you
  notice.
- **Every color, space, and radius comes from a token.** No raw hex, no
  arbitrary px. If the scale doesn't have what you need, that's a design
  conversation, not a license to inline a one-off.
- **Accessibility is a floor, not a stretch goal.** Every interactive
  element gets a visible focus ring (`--color-focus`). Every text token
  clears WCAG AA against every background depth it's meant to sit on — see
  §2.7 for the actual computed ratios, not an assumption.

---

## 2. Token Reference

Values below are transcribed from `tokens.css`. Use-when is guidance, not
a hard rule — when two rows both plausibly fit, prefer the one with lower
visual weight.

### 2.1 Color — depth & surface

| Token | Value | Use when |
|---|---|---|
| `--color-bg-0` | `#090c11` | Deepest structural chrome: nav rail, full-screen boot/fatal states |
| `--color-bg-1` | `#0b0e13` | App canvas — the window root background |
| `--color-bg-2` | `#0e1219` | Recessed list panels (conversation list, metadata sidebar) |
| `--color-bg-3` | `#10151d` | Base panel body (workspace, conversation view). Legacy `--panel`. |
| `--color-surface` | `#111720` | Elevated card on top of a depth: KPI tiles, message bubbles, floating palettes |
| `--color-surface-raised` | `#151b25` | Raised/hover/active surface: selected row, active tab, composer. Legacy `--panel-raised`. |

### 2.2 Color — border

| Token | Value | Use when |
|---|---|---|
| `--color-border-subtle` | `#242b36` | Low-contrast structural dividers, section rules, nav rail edge. Legacy `--border`. |
| `--color-border-default` | `#2c3541` | Component borders on cards, buttons, inputs |
| `--color-border-strong` | `#313a47` | Emphasized chrome: floating panels, framed chips, modal borders |

### 2.3 Color — text

| Token | Value | Use when |
|---|---|---|
| `--color-text-primary` | `#edf1f7` | Headings, primary body copy, values that matter |
| `--color-text-secondary` | `#c6ced8` | Supporting copy, metadata values, table cell content |
| `--color-text-muted` | `#8e99a9` | Labels, timestamps, eyebrows, disabled/inactive text. Legacy `--muted`. |

### 2.4 Color — accent (teal)

| Token | Value | Use when |
|---|---|---|
| `--color-accent` | `#55d5a9` | Default interactive/status-ok signal: live dots, health indicators, progress accents |
| `--color-accent-strong` | `#7fe3c3` | Highest-visibility teal: focus rings, links, active-tab indicator. Counterintuitively the *lightest, lowest-chroma* of the four — it earns "strong" from being the legacy `--focus` value, tuned for maximum visibility against dark surfaces, not for saturation. |
| `--color-accent-muted` | `#78dbba` | Mid-emphasis fill: primary CTA button background |
| `--color-accent-soft` | `#83dbc0` | Low-emphasis label/text tint: role labels, small accent text on a dark chip |

### 2.5 Color — status (warn / danger)

| Token | Value | Use when |
|---|---|---|
| `--color-warn` | `#edc568` | Amber foreground: warning dot, degraded-state text, queued/pending chip text |
| `--color-warn-soft` | `#ffe0a3` | Paler amber for body text sitting on a warn-tinted background |
| `--color-danger` | `#ff8075` | Red foreground: failure dot, critical-state text |
| `--color-danger-soft` | `#ff9889` | Paler red for body text sitting on a danger-tinted background |

### 2.6 Color — focus

| Token | Value | Use when |
|---|---|---|
| `--color-focus` | `var(--color-accent-strong)` → `#7fe3c3` | `outline-color` on any focusable element |
| `--focus-ring-width` | `2px` | `outline-width` |
| `--focus-ring-offset` | `2px` | `outline-offset` |

### 2.7 Accessibility floor — computed contrast ratios

WCAG 2 contrast, computed from the actual token hex values (relative
luminance formula, not estimated). AA normal text = 4.5:1, AA large
text/UI = 3:1, AAA normal text = 7:1.

Text tokens against every background depth:

| Text token | bg-0 `#090c11` | bg-1 `#0b0e13` | bg-2 `#0e1219` | bg-3 `#10151d` | surface `#111720` | surface-raised `#151b25` |
|---|---|---|---|---|---|---|
| `--color-text-primary` | 17.28 | **17.05** | 16.55 | 16.15 | 15.87 | 15.24 |
| `--color-text-secondary` | 12.33 | **12.17** | 11.81 | 11.53 | 11.33 | 10.88 |
| `--color-text-muted` | 6.79 | **6.70** | 6.50 | 6.35 | 6.24 | 5.99 |

`--color-text-muted` is the one to watch: it clears AA (6.70:1 on bg-1) but
not AAA (short by 0.3) — consistent with its intended role as
labels/timestamps, never primary content.

Accent and status colors used as text/foreground also clear AA against
both the app canvas and the raised surface — safe for status labels, not
just dots:

| Token | vs bg-1 | vs surface-raised |
|---|---|---|
| `--color-accent` | 10.56:1 | 9.44:1 |
| `--color-accent-strong` | 12.59:1 | 11.25:1 |
| `--color-accent-muted` | 11.63:1 | 10.40:1 |
| `--color-accent-soft` | 11.84:1 | 10.58:1 |
| `--color-warn` | 11.77:1 | 10.52:1 |
| `--color-warn-soft` | 15.13:1 | 13.53:1 |
| `--color-danger` | 7.91:1 | 7.07:1 |
| `--color-danger-soft` | 9.30:1 | 8.31:1 |

### 2.8 Typography

| Token | Value |
|---|---|
| `--font-ui` | `Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` |
| `--font-mono` | `ui-monospace, SFMono-Regular, Menlo, monospace` |
| `--text-2xs` | `10px` |
| `--text-xs` | `11px` |
| `--text-sm` | `12px` |
| `--text-md` | `13px` |
| `--text-base` | `14px` |
| `--text-lg` | `16px` |
| `--text-xl` | `20px` |
| `--text-2xl` | `24px` |

Role mapping is in §6.

### 2.9 Spacing (4px base)

| Token | Value | Token | Value |
|---|---|---|---|
| `--space-0` | `0` | `--space-5` | `20px` |
| `--space-1` | `4px` | `--space-6` | `24px` |
| `--space-2` | `8px` | `--space-7` | `32px` |
| `--space-3` | `12px` | `--space-8` | `40px` |
| `--space-4` | `16px` | `--space-px-2` | `2px` (hairline escape hatch) |

### 2.10 Radius

| Token | Value | Use when |
|---|---|---|
| `--radius-xs` | `4px` | Chips, tags, tiny controls |
| `--radius-sm` | `6px` | Buttons, inputs |
| `--radius-md` | `8px` | Cards, small panels |
| `--radius-lg` | `12px` | Panels, drawers, modals |
| `--radius-xl` | `16px` | Large containers, brand marks |
| `--radius-pill` | `999px` | Pills, status badges |

### 2.11 Elevation

| Token | Value | Use when |
|---|---|---|
| `--shadow-1` | `0 16px 40px rgba(0, 0, 0, 0.4)` | Docked floating chrome (composer) |
| `--shadow-2` | `0 24px 80px rgba(0, 0, 0, 0.73)` | Fully floating panels (command palette, modals) |
| `--scrim` | `rgba(2, 5, 9, 0.55)` | Backdrop behind a modal/palette overlay |

Colored glows (e.g. a "live" dot's halo) are not tokens — compose them
with `box-shadow: 0 0 8px color-mix(in oklch, var(--color-accent) 50%, transparent)`,
matching the `color-mix` idiom `styles.css` already uses for per-conversation
model accents (`.model-rail`, `.conversation-card[data-selected="true"]`).

### 2.12 Motion

| Token | Value |
|---|---|
| `--motion-fast` | `120ms` |
| `--motion-base` | `160ms` |
| `--ease-out` | `cubic-bezier(0.2, 0, 0, 1)` |

### 2.13 Layout / sash

| Token | Value |
|---|---|
| `--sash-size` | `6px` |
| `--sash-hover` | `#7fe3c34d` (`--color-accent-strong` @ ~30% alpha — matches the shipped resizable-shell code, not `--color-accent-muted`) |

### 2.14 Z-index ladder

| Token | Value | Use when |
|---|---|---|
| `--z-base` | `0` | Default stacking |
| `--z-raised` | `10` | Sticky headers, dropdowns within a panel |
| `--z-overlay` | `100` | Full-screen overlays (command palette backdrop today sits here) |
| `--z-palette` | `200` | Command palette / quick-switcher itself, above other overlays |
| `--z-toast` | `300` | Toasts and transient banners — always on top |

---

## 3. Consolidation Map

Legacy hex values observed in `styles.css` → canonical token. This is the
worklist for the later refactor pass. Rows group hexes that fold to the
same token; each hex's originating selector is noted so the refactor can
grep for it directly.

### 3.1 Background / surface (8 ramp values in the task brief, 21 total observed incl. near-duplicate panel shades)

| Legacy hex(es) | Selector(s) | → Token |
|---|---|---|
| `#090c11` | `.scope-tree`, `.boot`/`.fatal` fullscreen | `--color-bg-0` |
| `#0b0e13` | `:root` body background, `.boot`/`.fatal` | `--color-bg-1` |
| `#0e1219`, `#0d1218` | `.conversation-list-panel`; `.metadata-panel` | `--color-bg-2` |
| `#10151d` (was `--panel`), `#10161e` | `.conversation-header`/workspace; `.fabric-section` | `--color-bg-3` |
| `#111720`, `#121821`, `#131b25`, `#0b1016`, `#0b1017`, `#0c1118` | `.command-palette`, `.fabric-kpis article`; `.message`; `.pool-card`; `.workspace-tabs`; `.message-body pre`; `.fabric-table thead th` | `--color-surface` |
| `#151b25` (was `--panel-raised`), `#151a23`, `#151b24`, `#151c24`, `#151d27`, `#161b25`, `#171d26`, `#171e28`, `#17202b` | `--panel-raised`; `.search-box`; `.conversation-card:hover`/active tab; `.link-stack button`; `.fabric-filters input`/`.task-drawer`; `.message[data-role=assistant]`; `.composer`; `.pin-button`/`.secondary-button`; `.fabric-close` | `--color-surface-raised` |

The last row is the single biggest fold: 9 visually-indistinguishable
"raised panel" shades collapsing to one token — this is the drift the
token system exists to kill.

### 3.2 Border

| Legacy hex(es) | Selector(s) | → Token |
|---|---|---|
| `#242b36` (was `--border`), `#252d38`, `#252e39`, `#242e3a`, `#222b36` | `--border`; `.project-list`; `.message`; `.fabric-table-wrap`; `.fabric-table td` | `--color-border-subtle` |
| `#2b3442`, `#2b3644`, `#2c3541`, `#283240`, `#283544`, `#27313e`, `#28313d`, `#28303b`, `#29433e`, `#29413c`, `#29483e`, `#2a3440`, `#303b49` | `.message[data-role=assistant/user]`; `.message-body pre`; `.link-stack button`; `.task-drawer dl div`; `.pool-card`; `.fabric-kpis article`/`.fabric-section`; `.message-header`; card-selected color-mix fallback; `.runtime-health-strip`; `.command-palette footer`; `.fabric-filters input` | `--color-border-default` |
| `#313a47`, `#315f52`, `#323b48`, `#334151`, `#344050`, `#344253`, `#354052`, `#354151`, `#3a4656`, `#394454`, `#2d3744` | `.header-model`; `.runtime-detail-button`; `.composer`; `.task-drawer`; `.message-body th/td`; `.secondary-button`; `.copy-message`; `.fabric-close`; `.command-palette`; `.command-palette kbd`; `.command-palette label` | `--color-border-strong` |

**Note on the task-brief value `#2b3642`:** verified via exhaustive grep —
that exact hex does not appear in `styles.css`. The nearest real values are
`#2b3442` (message border) and `#2b3644` (code-block border), both one hex
step away and both folded into `--color-border-default` above. Treating
this as a transcription artifact rather than silently matching a
non-existent value or dropping the requirement.

### 3.3 Text

| Legacy hex(es) | Selector(s) | → Token |
|---|---|---|
| `#edf1f7` (root `color`), `#eff3f8`, `#edf2f8`, `#e8edf4`, `#e6ebf2`, `#e3e9f1`, `#dfe5ed` | root text color; message-body headings; command-palette input; search input; composer textarea; copy-message hover; no-selection h2 | `--color-text-primary` |
| `#c6ced8` (metadata dd), `#c7cfda`, `#c4cfdb`, `#c7d2df`, `#b9c4d2`, `#d9dfe8`, `#d4dde8`, `#d4dce7`, `#dce4ee`, `#d6deea`, `#d6e8ff` | `.metadata-section dd`; `.empty-state strong`; `.task-drawer dd`; `.secondary-button`; `.header-model`; `.message-body`; `.fabric-table button`; `.palette-results`; tab-close hover; `.fabric-filters input`; `.message-body code` | `--color-text-secondary` |
| `#8e99a9` (`--muted`) + 17 near-dup label grays (`#778497`, `#768397`, `#737f8f`, `#7f8b9c`, `#7f8b9b`, `#7d8998`, `#84909f`, `#8290a2`, `#8190a2`, `#818d9d`, `#808c9b`, `#8f9baa`, `#91a0b2`, `#9ba7b6`, `#9eabba`, `#6f7d8e`, `#728094`, `#778291`, `#7f8a98`) | eyebrows, `dt` labels, small meta text across nearly every panel | `--color-text-muted` |

### 3.4 Accent (teal)

| Legacy hex(es) | Selector(s) | → Token |
|---|---|---|
| `#55d5a9` + glow `#55d5a980` | `.live-dot`; `.runtime-health-dot`; `.pool-card progress` accent-color | `--color-accent` |
| `#7fe3c3` (was `--focus`) | focus outline; `.message-body a` link | `--color-accent-strong` |
| `#78dbba`, `#77dbba` | `.composer-foot button` (primary CTA); `.refresh-time` | `--color-accent-muted` |
| `#83dbc0` | `.message[data-role=user] .message-role` | `--color-accent-soft` |
| `#9eecd5`, `#b9f3df`, `#8ee2c5`, `#9edbc7`, `#74cdb0`, `#70d9b4` | `.brand-mark`; `.active-scope`; `.runtime-detail-button`; `.status-chip`; `.pool-card span`; `.runtime-status[active]` | nearest of the four above by lightness (all fold within the accent family; none needs a 5th token) |

### 3.5 Status — warn / danger

| Legacy hex(es) | Selector(s) | → Token |
|---|---|---|
| `#edc568`, `#f0c96c`, `#efd17e` | `.runtime-health-strip[degraded]` dot; `.fabric-kpis[data-health=degraded]`; `.status-chip[queued/approval-needed]` | `--color-warn` |
| `#ffe0a3`, `#dfc988` | `.snapshot-warning`; `.limitation-banner` text | `--color-warn-soft` |
| `#ff8075`, `#ff8378` | `.runtime-health-strip[critical]` dot; `.fabric-kpis[data-health=critical]` | `--color-danger` |
| `#ff9889`, `#ff9b92`, `#f4aaa1`, `#ffd4ce` | `.runtime-status[blocked/error]`; `.status-chip[failed/dead-letter]`; `.stream-error` text; `.cancel-button` text | `--color-danger-soft` |

### 3.6 Gaps — no canonical token (flagged, not silently dropped)

| Legacy hex(es) | Selector(s) | Status |
|---|---|---|
| `#d0bff6` / `#2a213d` | `.metadata-chip` | Violet — no hue in the 21-token palette covers this. Either fold it into a real 5th semantic (e.g. "info") or replace the component with an existing status/accent chip. Needs a design decision before the refactor pass touches this selector. |
| `#a8b7c8` / `#1b2531` | `.badge-line .route-badge` | A distinct blue-gray, bluer than `--color-text-secondary` and not part of the accent family. Same treatment: decide whether it becomes a token or gets remapped to an existing one before refactor. |
| `--model-accent` (runtime `oklch(...)`) | `.model-rail`, `.conversation-card`, `.badge-line .model-badge` | Intentionally out of scope — computed per-conversation by `modelColor()`, not a static token. Do not attempt to fold into the accent family. |
| `#3c4653` / `#7d8998` / `#151a21` | `.runtime-health-strip[unavailable]` | A 4th "neutral/unknown" status state beyond the ok/warn/fail three-way model in §5. Nearest fold is `--color-text-muted` for the dot/text and `--color-bg-2`-family for the background, but this is a real gap in the semantic model, not just a color snap — flagging for a product decision on whether "unavailable" deserves its own semantic tier. |

**Z-index, for the same refactor pass:** current overlay values don't line
up with the new ladder (`.fabric-overlay` is `60`, `.palette-backdrop` is
`100`, `.fabric-close` is `62`, `.snapshot-warning` is `110`) — only the
palette backdrop matches `--z-overlay`/`--z-palette` already; the other
three need re-homing, not preservation.

---

## 4. Component Conventions

Illustrative reference patterns — token consumption, not literal existing
class names. New components should look like this.

**Panel** (base container, sits on a depth)
```css
.panel { background: var(--color-bg-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-lg); }
```
```jsx
<section className="panel">…</section>
```

**Raised card** (elevated on top of a panel)
```css
.card { background: var(--color-surface); border: 1px solid var(--color-border-default); border-radius: var(--radius-md); box-shadow: var(--shadow-1); padding: var(--space-4); }
```
```jsx
<article className="card"><span>Queue depth</span><strong>128</strong></article>
```

**Pill / badge**
```css
.badge { display: inline-flex; align-items: center; padding: var(--space-1) var(--space-2); border-radius: var(--radius-pill); font-size: var(--text-2xs); text-transform: uppercase; letter-spacing: 0.06em; background: var(--color-surface-raised); color: var(--color-text-muted); }
.badge[data-tone="accent"] { color: var(--color-accent); background: color-mix(in oklch, var(--color-accent) 14%, var(--color-bg-3)); }
```
```jsx
<span className="badge" data-tone="accent">active</span>
```

**Button** (default / accent / danger)
```css
.btn { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-default); border-radius: var(--radius-sm); background: var(--color-surface-raised); color: var(--color-text-secondary); font-size: var(--text-sm); transition: background var(--motion-fast) var(--ease-out); }
.btn-accent { border: 0; background: var(--color-accent-muted); color: var(--color-bg-1); font-weight: 700; }
.btn-danger { border: 0; background: var(--color-danger); color: var(--color-bg-1); }
.btn:focus-visible { outline: var(--focus-ring-width) solid var(--color-focus); outline-offset: var(--focus-ring-offset); }
```
```jsx
<button className="btn-accent">Run now</button>
```

**Input / search**
```css
.input { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); background: var(--color-surface-raised); color: var(--color-text-muted); }
.input input { border: 0; outline: 0; background: transparent; color: var(--color-text-primary); font-size: var(--text-sm); }
```

**Tab strip + active tab**
```css
.tab-strip { display: flex; border-bottom: 1px solid var(--color-border-subtle); background: var(--color-bg-1); }
.tab { border-top: 2px solid transparent; color: var(--color-text-muted); font-size: var(--text-xs); }
.tab[data-active="true"] { border-top-color: var(--color-focus); background: var(--color-surface-raised); color: var(--color-text-primary); }
```

**Status dot**
```css
.status-dot { width: 7px; height: 7px; border-radius: var(--radius-pill); background: var(--color-accent); box-shadow: 0 0 8px color-mix(in oklch, var(--color-accent) 50%, transparent); }
.status-dot[data-status="warn"] { background: var(--color-warn); box-shadow: 0 0 8px color-mix(in oklch, var(--color-warn) 50%, transparent); }
.status-dot[data-status="fail"] { background: var(--color-danger); box-shadow: 0 0 8px color-mix(in oklch, var(--color-danger) 50%, transparent); }
```

**Key-value metadata row**
```css
.kv-row { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: var(--space-2); font-size: var(--text-sm); }
.kv-row dt { color: var(--color-text-muted); }
.kv-row dd { margin: 0; color: var(--color-text-secondary); }
```

**Empty state**
```css
.empty-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-5); color: var(--color-text-muted); text-align: center; font-size: var(--text-sm); }
.empty-state strong { color: var(--color-text-secondary); }
```
```jsx
<div className="empty-state"><strong>No runs yet</strong><span>Runs appear here once a job is scheduled.</span></div>
```

**Sash / divider states** (no existing implementation — new convention for resizable panes)
```css
.sash { width: var(--sash-size); cursor: col-resize; background: transparent; transition: background var(--motion-fast) var(--ease-out); }
.sash:hover, .sash[data-active="true"] { background: var(--sash-hover); }
```

---

## 5. Data-Viz Standards

Applies to every dashboard: automation health, reporting engine, work-queue
watchers, admin metrics.

### 5.1 Categorical series palette

Six oklch hues, same lightness/chroma recipe (`L 0.78 C 0.11`) so all
series read as equal visual weight. Deliberately built around — not
colliding with — the three model-identity hues (openai `165`, anthropic
`40`, unknown `255`):

- **`165` and `255` are used directly** as series anchors (teal, indigo) —
  they're already load-bearing hues in this app via `modelColor()`, so
  reusing them keeps the whole app's color language coherent.
- **`40` is deliberately excluded.** Computed hue of the real `--color-warn`
  (`#edc568`) is `~86°` and `--color-danger` (`#ff8075`) is `~27°` — both
  land in the same red-orange-gold arc as `40`. Any categorical series
  placed near there risks being misread as a status color mid-dashboard.
  The whole `335°→130°` arc (through `0°`) is reserved for warn/danger and
  gets zero categorical series.

| Series | oklch | sRGB fallback |
|---|---|---|
| 1 — teal (brand/default) | `oklch(0.78 0.11 165)` | `#6ccea6` |
| 2 — azure | `oklch(0.78 0.11 205)` | `#4fccd9` |
| 3 — indigo | `oklch(0.78 0.11 255)` | `#87bafd` |
| 4 — violet | `oklch(0.78 0.11 285)` | `#b0adfb` |
| 5 — rose | `oklch(0.78 0.11 335)` | `#e39cd3` |
| 6 — moss | `oklch(0.78 0.11 130)` | `#a0c679` |

Series 1 (teal) is the "default/highlighted" series when a chart has one
primary line and several comparison lines — it echoes `--color-accent`
without being identical to it, so a chart never looks like a status
readout. If a series needs to *be* a status literally (e.g. "this line is
the failure count"), use `--color-danger` directly instead of a
categorical slot.

### 5.2 Sequential ramp (intensity / heatmaps)

Single hue (`165`, brand teal), rising lightness and chroma — standard
"more color = more of the thing" convention:

| Step | oklch | sRGB |
|---|---|---|
| 1 (lowest) | `oklch(0.28 0.040 165)` | `#142f24` |
| 2 | `oklch(0.42 0.070 165)` | `#205943` |
| 3 | `oklch(0.56 0.095 165)` | `#328666` |
| 4 | `oklch(0.70 0.115 165)` | `#4cb58c` |
| 5 (highest) | `oklch(0.84 0.130 165)` | `#6ce5b5` |

Step 5 approaches `--color-accent-strong` by design — the top of the
intensity scale should feel like "fully lit," not a different color family.

### 5.3 Status semantics

| Meaning | Token |
|---|---|
| OK / healthy / success | `--color-accent` |
| Warning / degraded / needs attention | `--color-warn` |
| Failure / critical | `--color-danger` |
| Unknown / unavailable | `--color-text-muted` (see §3.6 — flagged gap, no dedicated token yet) |

### 5.4 Chrome (axes, gridlines, labels)

| Element | Token |
|---|---|
| Gridlines | `--color-border-subtle` |
| Axis line | `--color-border-default` |
| Axis tick labels | `--color-text-muted`, `--text-2xs` |
| Data callout labels | `--color-text-secondary`, `--text-xs` |
| Chart title | `--color-text-primary`, `--text-md` |

### 5.5 Sparkline & KPI-tile conventions

- Sparkline: single series color, 1–1.5px stroke, no fill (or a
  `color-mix(in oklch, <series> 12%, transparent)` wash at most), no
  axes/gridlines, one end-point dot. Height 24–32px. Pair with the current
  value in `--font-mono` `--text-sm` beside it, not inside it.
- KPI tile: label `--text-2xs` uppercase muted with tracking (§6); value
  `--text-xl`–`--text-2xl` bold in `--color-text-primary`; delta indicator
  colored by **actual health meaning, not raw sign** — a rising error count
  is `--color-danger` even though it's numerically "up." Never hardcode
  green-up/red-down.

### 5.6 Don'ts

- No gradients or 3D effects on data marks (bars, pies, donuts).
- No drop shadows on marks — `--shadow-*` is chrome-only.
- No legend when direct end-of-line labeling fits; legends cost more
  scanning time than they save at this data density.
- Cap categorical charts at 6 series (the palette size). More than that,
  aggregate an "other" bucket or split the chart.
- Never encode status with color alone — pair with an icon, label, or
  position so the colorblind reading matches the color reading.

---

## 6. Typography Rules

**Mono (`--font-mono`) vs UI (`--font-ui`):** mono for anything the user
might copy/paste or that must not misread a character — ids, file paths,
counts, durations, timestamps, hashes. UI font for everything else,
including numbers that are *labels* rather than *data* (e.g. a page title
that happens to contain a number).

**Size by role:**

| Role | Token |
|---|---|
| Page title | `--text-xl` |
| Section header | `--text-lg` |
| Body copy | `--text-base` |
| Default UI text (buttons, list items) | `--text-md` |
| Dense table cell | `--text-sm` |
| Micro-label / eyebrow | `--text-xs`, uppercase, `+0.06em` letter-spacing |
| Ultra-dense chip/tab-number text | `--text-2xs` |
| Hero KPI number | `--text-2xl` |

---

## 7. Voice & Labels

- **Sentence case everywhere**, including buttons and headers. No Title
  Case, no ALL CAPS — the one exception is the micro-label/eyebrow role
  (`--text-xs`/`--text-2xs` + uppercase + tracking), which is a deliberate
  typographic treatment, not a voice choice.
- **No exclamation marks.** This is an ops console; nothing here is
  exciting, including success states. "Run complete." not "Run complete!"
- **Timestamps follow `compactAge()`** (`src/shared/presentation.ts`): `now`
  / `12m` / `3h` / `4d` / `2w` / `1y` in any dense or list context. Use
  `formatMessageDate()`'s absolute `DD/MM HH:MMam` form only in expanded
  detail views where the exact moment matters.
- **Empty-state phrasing:** a short bold noun-phrase headline stating
  what's missing, followed by a muted sentence giving the calm reason or
  next action. No apology, no exclamation. `"No runs yet" / "Runs appear
  here once a job is scheduled."` — not `"Oops! Nothing to show."`

---

## 8. Adding a New Page/Dashboard — Checklist

- [ ] Backgrounds use `--color-bg-0..3` / `--color-surface{,-raised}` — no raw hex
- [ ] Borders use `--color-border-{subtle,default,strong}` — no raw hex
- [ ] Text uses `--color-text-{primary,secondary,muted}` at the size matching its role (§6)
- [ ] Status/health uses accent = ok, warn = attention, danger = failure — never an ad hoc color
- [ ] Every interactive element has a visible focus ring (`--color-focus`, `--focus-ring-width`, `--focus-ring-offset`)
- [ ] Spacing uses `--space-*` (4px grid); radius uses `--radius-*`
- [ ] State-change transitions use `--motion-fast`/`--motion-base` with `--ease-out` — no bounce
- [ ] Charts use the §5 categorical/sequential oklch palettes, capped at 6 series, direct-labeled over legended where possible
- [ ] Copy is sentence case, no exclamation marks, timestamps via `compactAge()`
- [ ] Reviewed against the nearest sibling dashboard for structural consistency before merge
