import { formatINRSigned } from '../lib/format'

/**
 * Interval-styled delta: +₹12,340 like a timing gap (+0.340).
 * Sector semantics: green = moved the good way, yellow = moved the wrong way,
 * mute = flat. `goodWhen` says which direction is good — for spend it's
 * 'down', for rewards it's 'up'. Red is not used here; red is for losses
 * and alerts (the Phase 5 gap report), not month-to-month drift.
 */
export default function DeltaChip({
  value,
  goodWhen = 'down',
  format = formatINRSigned,
  className = '',
}: {
  value: number
  goodWhen?: 'down' | 'up'
  format?: (v: number) => string
  className?: string
}) {
  const flat = Math.round(value) === 0
  const good = goodWhen === 'down' ? value < 0 : value > 0
  const tone = flat
    ? 'text-ink-mute border-line'
    : good
      ? 'text-sector-green border-sector-green/30'
      : 'text-sector-yellow border-sector-yellow/30'

  return (
    <span
      className={`figure inline-flex items-center rounded-chip border bg-carbon-2 px-1.5 py-0.5 ${tone} ${className || 'text-xs'}`}
    >
      {format(value)}
    </span>
  )
}
