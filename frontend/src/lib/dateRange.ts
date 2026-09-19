// Date-range presets. Mirrors the legacy dateRangeFor() in static/js/app.js
// EXACTLY (including its toISOString/UTC quirk) — the Phase 0 parity gate
// compares numbers between the two UIs, so both must send identical ranges.

export type RangeKey = 'all' | 'ytd' | '6m' | '3m' | '1m' | 'custom'

export const RANGE_OPTIONS: { value: RangeKey; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: 'ytd', label: 'Year to date' },
  { value: '6m', label: 'Last 6 months' },
  { value: '3m', label: 'Last 3 months' },
  { value: '1m', label: 'This month' },
  { value: 'custom', label: 'Custom range' },
]

/** 'custom' has no fixed window — the caller (Dashboard) supplies its own
 * from/to instead of calling this; it's listed in RangeKey purely so the
 * Select can offer it as an option. */
export function dateRangeFor(key: RangeKey): { from: string; to: string } {
  const today = new Date()
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  let from = '2000-01-01'
  if (key === 'ytd') from = `${today.getFullYear()}-01-01`
  if (key === '6m') {
    const d = new Date(today)
    d.setMonth(d.getMonth() - 6)
    from = fmt(d)
  }
  if (key === '3m') {
    const d = new Date(today)
    d.setMonth(d.getMonth() - 3)
    from = fmt(d)
  }
  if (key === '1m') from = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`
  return { from, to: fmt(today) }
}

/** 'YYYY-MM' of the month in progress — its data is incomplete by definition. */
export function currentMonthKey(): string {
  return new Date().toISOString().slice(0, 7)
}
