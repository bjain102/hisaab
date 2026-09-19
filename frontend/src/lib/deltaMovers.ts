import type { MonthCategoryPoint } from '../api/types'

export type CategoryMove = { category: string; delta: number; prev: number; last: number }

export type MoversResult = {
  /** Every category that changed, sorted by absolute move, largest first. */
  movers: CategoryMove[]
  movedCount: number
  /**
   * Whether the movers add up to the headline delta.
   *
   * HONESTY NOTE. `monthly_trend` floors each month at max(0, debits − credits)
   * while `monthly_by_category` is deliberately left signed and unfloored (see
   * the comments on both queries in app.py). The two agree unless a month
   * netted negative overall, in which case the flooring added rupees to the
   * headline that no category accounts for. When this is false the UI must say
   * so rather than implying a complete decomposition.
   */
  reconciles: boolean
}

/** Which categories moved between two months, largest absolute move first. */
export function categoryMovers(
  byCategory: MonthCategoryPoint[],
  prevMonth: string,
  lastMonth: string,
  headlineDelta: number,
): MoversResult {
  const prev = new Map<string, number>()
  const last = new Map<string, number>()
  for (const r of byCategory) {
    if (r.month === prevMonth) prev.set(r.category, (prev.get(r.category) ?? 0) + r.total)
    if (r.month === lastMonth) last.set(r.category, (last.get(r.category) ?? 0) + r.total)
  }

  const movers: CategoryMove[] = []
  for (const category of new Set([...prev.keys(), ...last.keys()])) {
    const p = prev.get(category) ?? 0
    const l = last.get(category) ?? 0
    const delta = l - p
    if (delta !== 0) movers.push({ category, delta, prev: p, last: l })
  }
  movers.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))

  const summed = movers.reduce((acc, m) => acc + m.delta, 0)
  return {
    movers,
    movedCount: movers.length,
    reconciles: Math.round(summed) === Math.round(headlineDelta),
  }
}
