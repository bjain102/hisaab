// Sticky category → hue assignment. The dataviz rule: color follows the
// ENTITY, never its rank — changing a filter must not repaint surviving
// categories. First time a category enters the top-N it claims the next
// free hue and keeps it for the session.
//
// FOUR hues, not six. This is a validated ceiling, not a style choice: the
// composition chart is STACKED, so any two segments can touch once a category
// is absent for a month, and every pair must therefore clear the CVD/normal
// separation floors (`--pairs all`). Five hues only ever reached CVD ΔE 6.1 —
// the bottom of the band that is legal only with secondary encoding — while
// four clears 12.9, above the ≥8 target. See tokens.css's chart palette block.
// Adding a fifth hue here silently pushes the palette back under the floor.

const HUES = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
] as const

export const OTHER_HUE = 'var(--color-chart-other)'
export const OTHER_KEY = 'Other'

/** Categories shown individually before the rest fold into "Other" — bounded by
 *  HUES.length so a category can never be handed a hue already in use. */
export const MAX_CATEGORIES = HUES.length

const assigned = new Map<string, string>()

export function hueFor(category: string): string {
  if (category === OTHER_KEY) return OTHER_HUE
  const existing = assigned.get(category)
  if (existing) return existing
  const hue = HUES[assigned.size % HUES.length]
  assigned.set(category, hue)
  return hue
}
