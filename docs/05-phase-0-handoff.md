# 05 — Phase 0 Handoff

**Final version, 2026-07-13.** Phase 0 is **complete** — every backlog task 0.0–0.6
done, nothing deferred — with three honest caveats in §4. Written for a successor
session (assume a less capable model, working alone). The docs in `/docs` are the
source of truth; read [04-phased-backlog.md](04-phased-backlog.md) before Phase 1.

An earlier mid-run snapshot of this file (commit `0238b6e`) recorded the state at an
interruption; this version supersedes it.

---

## 1. What was built (one commit per backlog task)

| Task | Commit | Summary |
|---|---|---|
| 0.0 env | — | Node v22.17.0 / npm 10.9.2 present; nothing installed. |
| 0.1 scaffold | `b86ffb1` | `frontend/`: Vite 8, React 19, TS, Tailwind v4 (`@tailwindcss/vite`), `motion` 12, TanStack Query 5, react-router 7, recharts 3. Dev proxy `/api` → Flask `:5000`. Fonts self-hosted via fontsource (no CDN, no external requests at runtime). *(Majors are newer than ADR-002's names — "boring current" intent kept; no issues found.)* |
| 0.2 tokens | `bcfe5ff` | `frontend/src/styles/tokens.css` — the only file allowed raw hex. F1-telemetry: carbon grounds, sector status colors (purple/green/yellow, scarce red `#E10600`), chart series palette, Titillium/Inter/JetBrains Mono, tight radii, 150/220ms motion, reduced-motion respected. Base classes: `.figure` `.display` `.eyebrow`. |
| 0.3 shell | `4962841` | Sidebar (6 destinations, 2 badged "soon"), layoutId active pill, AnimatePresence route transitions, styled ComingSoon pages, ToastHost. |
| 0.4 kit | `3ef4889` | `src/components/`: StatCard (+`reserved` variant), Panel, DataTable, Select, Modal, Toast/`toast()`, EmptyState, Skeleton, **TimingTower** (rank chips, pace bars, FLIP reorder), **DeltaChip** (sector-colored interval), AnimatedNumber (en-IN ticker). `src/lib/format.ts` = the single money-format source (Phase 3's paise flip happens only there). `/kit` gallery renders all states. |
| 0.5a API+tests | `49c87ff`+`b049d08` | Additive `monthly_by_category` on `/api/summary` (signed per-category nets — see §3). First tests in the repo: 9 API tests, synthetic fixture DB. `test.ps1`. |
| 0.5b dashboard | `58c8015` | M4 rev. 2: 5-slot hero (Net spend ticker · vs-last-month DeltaChip over the last two *complete* months · cashback · reserved Gap/Trust), stacked month×top-5+Other composition with dimmed partial month + footnote, custom dark tooltip, legend, sticky category→hue map; By-card / Category / Merchants as TimingTowers; card+range filters mirroring legacy `dateRangeFor` exactly; skeletons; API-error empty state. Chart palette re-tuned to **pass the dataviz validator as a set** on `#121216` (values + warning comment in tokens.css). |
| 0.6 serving | `67a1023` | `/` serves `frontend/dist` with SPA fallback (client routes survive refresh); friendly 503 → "run build.ps1" + `/legacy` link when unbuilt; `/api/*`/`/static/*` guarded from the catch-all; legacy UI byte-identical at `/legacy`; `dev.ps1`, `build.ps1`; 4 route tests (13 total). |

**Definition-of-done run:** `./build.ps1; python app.py` → new dashboard on real data
at `http://127.0.0.1:5000/`, legacy intact at `/legacy`. Verified working.

## 2. Verification performed

- **Tests:** 13/13 green (`./test.ps1`): net-spend semantics, filters, the
  column-sum invariant, additive-shape guard, serving topology.
- **Parity gate (backlog 0.5) — PASSED:** legacy and new UI driven side by side on
  the real DB for all three required combos — (all cards, YTD), (HDFC-Swiggy-1930,
  all time), (all cards, last 3 months). Every DOM-comparable number matched
  row-for-row: all card rows (including a net-negative card at −1%), all category
  rows with percentages, top merchants, refund metas. Column-sum invariant is
  pinned by a unit test.
- **Design system:** verified via computed styles (carbon-0 ground, Titillium 40px
  display, mono `tabular-nums` figures, uppercase tracked eyebrows, 6px panels with
  hairlines, validated series hues in the rendered SVG) plus screenshots of tokens,
  shell, transitions, and empty states taken earlier in the run. Hex discipline
  clean: no raw hex outside `tokens.css`.

## 3. Decisions a successor must not silently reverse

- **`monthly_by_category` is signed** (refund-heavy categories net negative). That is
  what makes stacked columns sum to `monthly_trend` exactly; display clamping lives in
  `MonthlyComposition.tsx` (segments floor at 0, Other absorbs the remainder). Pinned
  by test.
- **Sector colors are status-only; chart uses series-\* only; red is losses/alerts
  only.** The series palette passes the dataviz validator *as a set* — never change
  one value without re-running the validator (command in tokens.css history / §4 of
  the mid-run snapshot, commit `0238b6e`). "Other" is muted rose because gray fails
  the chroma floor; it recedes by stack position.
- **Category hue follows the entity** (`lib/categoryHues.ts` sticky map): changing
  filters must never repaint a surviving category.
- **vs-last-month compares complete months only**; the partial current month renders
  dimmed with a footnote — never a cliff to zero.
- **Money formatting only in `lib/format.ts`**; range presets in `lib/dateRange.ts`
  intentionally reproduce the legacy code including its UTC quirk (parity).
- **Legacy untouched** except: route moved to `/legacy`, startup banner de-emojied
  (see §4). Parsers, templates, static, schema: zero changes. No schema migration
  exists or was needed for Phase 0.

## 4. Landmines & honest caveats

1. **Startup banner emoji crashed the server** under captured/piped stdout on Windows
   (cp1252 can't encode ✅ — `UnicodeEncodeError` before Flask binds). Fixed by
   de-emojing the print in `app.py`. Keep all server-side prints ASCII.
2. **The browser pane's renderer was occlusion-throttled for most of the run**
   (rAF never fired — probably the app window was minimized). Consequences: (a) final
   dashboard **pixel** QA could not be completed — layout/type/color were verified by
   computed style and DOM, and earlier screenshots covered tokens/shell, but nobody
   has *seen* the finished dashboard yet; **owner should eyeball `/` and `/kit` and
   judge the "broadcast telemetry, not merch" bar**; (b) AnimatedNumber tickers
   read ₹0.00 in that throttled environment — they are rAF-driven and count up
   normally on a visible screen; the values they animate to are the raw API fields
   with no arithmetic. If tickers ever misbehave on a real screen, look at
   `components/AnimatedNumber.tsx`.
3. **Legacy import flow was not live-tested this run** (it would have written
   duplicate rows into the real DB — the dedup gate doesn't exist until Phase 3).
   The import code path is untouched; only its page URL moved to `/legacy`.
4. Windows quirks for successors: Bash-tool cwd persists between calls; the Write
   tool refuses files it hasn't read (cost one fixup commit `b049d08`); CRLF warnings
   on commit are noise. Recharts makes the bundle ~830 kB minified — fine for a
   localhost app; don't spend time code-splitting it.

## 5. How to run everything

```powershell
./test.ps1                    # 13 tests, must be green
./build.ps1; python app.py    # production mode: new UI at :5000/, legacy at /legacy
./dev.ps1                     # dev mode: Flask window + Vite HMR at :5173
```

## 6. What's next

Phase 1 (backlog): the parser safety net — pytest corpus scaffolding on
`statements/` (tier-1 redacted files committable; the Axis-Rewards redacted file
must be re-made with amounts intact — owner task, backlog 1.2), golden snapshot
tests, statement-period + printed-totals extraction with reconciliation, the F3
date-order fix, Kotak credits (F7), and deleting `debug_rewards.py` (F11).
Do not touch parsers before the corpus tests exist.
