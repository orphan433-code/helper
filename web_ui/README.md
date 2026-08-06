# TJS Web UI

Vite + React + TypeScript + Tailwind CSS v4 + shadcn-style Radix components.

## Design

**Teal SaaS Paper (B):** light mint wash `#F0FDFA`, white cards, teal `#0D9488`, DM Sans + JetBrains Mono. Button motion: shimmer / glare / press scale.

## Commands

```bash
npm install
npm run build    # → dist/ (served by FastAPI / pywebview)
npm run dev      # Vite on :5173, proxies /api to :8765
```

## Layout

- `src/components/ui/` — shadcn-like primitives
- `src/store/console.ts` — Zustand + `window.*` bridge for backend eval
- `bridge.js` — browser engine API (served by FastAPI, not bundled)
- `index.legacy.html` — previous single-file UI fallback
