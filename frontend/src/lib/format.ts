/*
 * The single source of money formatting. Phase 3 flips the API to integer
 * paise; when that happens, only this file changes (divide by 100 here).
 */

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const inrWhole = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

export function formatINR(rupees: number): string {
  return inr.format(rupees)
}

/** Whole-rupee form for axes and dense rows. */
export function formatINRWhole(rupees: number): string {
  return inrWhole.format(rupees)
}

/** Compact axis labels: ₹1.2L, ₹45k, ₹980. */
export function formatINRCompact(rupees: number): string {
  const abs = Math.abs(rupees)
  const sign = rupees < 0 ? '-' : ''
  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(1)}Cr`
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(1)}L`
  if (abs >= 1_000) return `${sign}₹${Math.round(abs / 1_000)}k`
  return `${sign}₹${Math.round(abs)}`
}

/** Signed interval form for deltas: +₹12,340 / −₹8,120. */
export function formatINRSigned(rupees: number): string {
  const body = inrWhole.format(Math.abs(rupees))
  if (Math.round(rupees) === 0) return `±${body}`
  return `${rupees > 0 ? '+' : '−'}${body}`
}

/** "2026-03" → "Mar". Month labels are for humans, not machines.
 *  Deliberately year-less. For an axis that can span more than one calendar
 *  year, pair with a non-text year boundary marker instead of printing the
 *  year on every tick — see MonthlyComposition's ReferenceLine use: the
 *  year is real data (`formatMonthLabelFull` below carries it into the
 *  tooltip, on demand), it just doesn't belong painted onto the chart
 *  permanently. Twenty repeated "'25"/"'26" suffixes read as clutter, not
 *  as a fix — the owner's call after seeing it live. */
export function formatMonthLabel(isoMonth: string): string {
  const [y, m] = isoMonth.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleString('en', { month: 'short' })
}

/** "2026-03" → "Mar 2026". Unambiguous — for the one place a reader needs
 *  the exact year without hunting for it: a tooltip, reached by hovering a
 *  specific bar, where showing it costs nothing extra visually. */
export function formatMonthLabelFull(isoMonth: string): string {
  const [y, m] = isoMonth.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' })
}

export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

// Effective reward rates are small (1–8%) and one decimal is meaningful —
// distinct from formatPercent's whole-number shares/trust.
export function formatRate(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`
}
