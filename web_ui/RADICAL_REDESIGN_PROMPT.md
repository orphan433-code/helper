# RADICAL REDESIGN — Tzk / PlatCore Operator Console

## Mission
Do a **radical visual and structural redesign** of `web_ui/index.html`. The previous pass was a weak skin refresh — REJECT that approach. The new UI must look like a **different product**, not the same stacked cards with new border-radius.

If a designer glances for 3 seconds and says “same page, just polished” — you FAILED.

## Files
- Main: `web_ui/index.html` (CSS + HTML + JS)
- Bridge: `web_ui/bridge.js` (browser engine controls)
- Served as raw HTML by FastAPI / pywebview — **no React migration**

## Non-negotiable: preserve behavior
Keep ALL of these working (same IDs / data-* / JS API):
- Engine bar: `#browser-server-bar`, `#srv-state`, `#btn-srv-start`, `#btn-srv-stop`, `#btn-srv-restart`
- Job stop: `#btn-stop`
- Status: `#status-bar`, `#status`, `#status-label`
- Recovery: `#recovery-card` and all `#recovery-*` + recovery buttons
- Steps: `#action-login`, `#action-start`, `#action-receipts` and all their buttons/desc/progress IDs
- Settings: `#max-deals`, `#min-amount`, `#max-amount`, `#allow-visa`, `#allow-mastercard`, `#btn-save`
- ADB: `#adb-device-line`, `#adb-device-value`, `#btn-adb-check`
- Redirect/decline tabs + all `#redir-*`, `#btn-redirect`, `#btn-decline`, decline progress IDs
- Log: `#log`, `#btn-copy-log`
- Dialog: `#dialog-overlay`, `#dialog-title`, `#dialog-body`, `#dialog-footer`
- Existing JS state classes: `idle|running|waiting|success|error`, `highlight|active|waiting|disabled-wait`, progress `visible|processing|done`

You MAY move nodes in the DOM tree and change wrappers/classes freely — **IDs and script behavior stay**.

## What MUST change (radical)

### 1) Information architecture — rearrange blocks
Current vertical “card soup” is wrong. Rebuild layout as a real operator console:

**Suggested target layout (implement something this bold or better):**
```
┌─────────────────────────────────────────────────────────────┐
│ TOP BAR: brand | engine ON/OFF/RESTART | job STOP | status   │
├──────────────────────────────┬──────────────────────────────┤
│ LEFT / PRIMARY               │ RIGHT / CONTEXT              │
│ Stepper workflow 1→2→3       │ Live status + progress       │
│ big CTAs, clear next action  │ deal list / pipeline feed    │
│                              │ ADB device chip              │
├──────────────────────────────┴──────────────────────────────┤
│ TOOLS STRIP (horizontal or 2-col bento)                     │
│ [Параметры] [Карты Visa/MC as segment] [Редирект/Отмена]    │
├─────────────────────────────────────────────────────────────┤
│ LOG — full-width terminal panel, collapsible                │
└─────────────────────────────────────────────────────────────┘
```
On mobile: stack primary → context → tools → log. Do not keep the old single 720px column of identical sections.

### 2) Engine controls are first-class
`Включить` / `Выключить` / `Перезапустить` must be **impossible to miss** — top bar or prominent engine cluster, always visible. Never hide them in injection-only ephemeral UI. Style them as a power cluster (ON green / OFF danger / RESTART warn).

### 3) Checkboxes → modern controls
Replace pill-checkboxes with **segmented controls / toggle groups / switch-like UI** for:
- Visa / Mastercard
- Redirect account 104.1 / 104.2
Keep underlying `<input type="checkbox">` with same IDs if JS depends on them, but the **visible control** must look new (custom switch/segment).

### 4) Visual language — break the old look
- New composition (bento / split panes / sticky command bar) — not restyled stacked cards
- Strong hierarchy: one obvious primary CTA per state
- Dense but readable ops aesthetic (Linear / Vercel / Stripe Dashboard energy) — NOT generic SaaS purple, NOT neon cyberpunk
- New typography scale, spacing system, surfaces (glass/panel/terminal mix OK)
- Motion: command-bar transitions, step advance, progress, panel slide-ins, log type feel — respect `prefers-reduced-motion`

### 5) States must scream the truth
Each mode visually distinct:
- engine off / on / restarting
- idle / running / waiting-for-user / success / error / recovery
- step locked / available / active / done

Descriptions: short Russian, actionable (“что делать сейчас”).

### 6) Anti-patterns (forbidden)
- “Same sections, new shadows”
- Keeping identical vertical order of all blocks
- Tiny engine buttons that blend into status
- Leaving Visa/MC as the same check-pills
- Purple gradients, emoji decoration, cluttered badge soup
- Breaking IDs / `window.pywebview.api` / bridge handlers

## Process
1. Read full `index.html` (CSS + markup + JS state handlers) and `bridge.js`
2. Sketch new IA (brief) then **implement immediately**
3. Rewrite CSS heavily; restructure HTML wrappers
4. Wire engine bar styles in CSS; ensure bridge still binds handlers
5. Smoke-check: all IDs exist once; class toggles still match JS

## Done criteria
- Side-by-side with old UI: layout looks **structurally different**
- Engine start/stop/restart visible and styled as power controls
- Checkboxes visually reinvented
- Blocks logically regrouped (workflow vs tools vs log)
- Animations present and intentional
- Zero missing critical IDs; no API regressions
