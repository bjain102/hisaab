import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MonthCategoryPoint, MonthPoint } from '../api/types'
import { formatINR, formatINRCompact, formatMonthLabel, formatMonthLabelFull } from '../lib/format'
import { hueFor, MAX_CATEGORIES, OTHER_KEY } from '../lib/categoryHues'
import { currentMonthKey } from '../lib/dateRange'

type Row = {
  /** "YYYY-MM" — unique across years, unlike the bare month name, so it's
   *  what the axis positions bars by (`XAxis dataKey`) and what a
   *  ReferenceLine targets for a year boundary. The TICK TEXT stays bare
   *  ("Mar") via `tickFormatter`; the year never gets painted onto the axis
   *  itself — see formatMonthLabel's own comment for why. */
  month: string
  /** Always "Mon YYYY" — the tooltip's header. A range spanning more than
   *  one year has more than one bar named "Jan"/"Mar"/etc; the tooltip is
   *  the one place a misread bar reads as a data bug, not a label bug, so
   *  it stays unambiguous on hover even though the axis stays bare. */
  fullLabel: string
  partial: boolean
  total: number
  [segment: string]: string | number | boolean
}

/**
 * Month × top-N-categories + Other, stacked (N = MAX_CATEGORIES, currently 4 —
 * set by how many hues the palette can separate, see categoryHues).
 * Segments clamp at zero for
 * display; Other absorbs the remainder so each column sums to the month's
 * trend value exactly (the API's signed per-category nets make that hold —
 * see /api/summary monthly_by_category). The current partial month renders
 * at reduced opacity: incomplete data must look incomplete.
 */
export default function MonthlyComposition({
  trend,
  byCategory,
}: {
  trend: MonthPoint[]
  byCategory: MonthCategoryPoint[]
}) {
  const { rows, segments, yearBoundaries } = useMemo(() => {
    const totals = new Map<string, number>()
    for (const p of byCategory) {
      totals.set(p.category, (totals.get(p.category) ?? 0) + Math.max(0, p.total))
    }
    // Bounded by the palette, not by taste: one hue per shown category, and the
    // palette tops out at 4 (see categoryHues). A 5th named band would have to
    // reuse a hue, which is the one thing a categorical scale may never do.
    const topCats = [...totals.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_CATEGORIES)
      .map(([c]) => c)

    const nowKey = currentMonthKey()
    const rows: Row[] = trend.map((m) => {
      const row: Row = {
        month: m.month,
        fullLabel: formatMonthLabelFull(m.month),
        partial: m.month === nowKey,
        total: m.total,
      }
      let allocated = 0
      for (const cat of topCats) {
        const net = byCategory.find((p) => p.month === m.month && p.category === cat)?.total ?? 0
        const clamped = Math.max(0, net)
        row[cat] = clamped
        allocated += clamped
      }
      row[OTHER_KEY] = Math.max(0, m.total - allocated)
      return row
    })
    const hasOther = rows.some((r) => (r[OTHER_KEY] as number) > 0.005)
    // Every January AFTER the first bar marks a year boundary worth a visual
    // break — not the very first one, which would just draw a line at the
    // chart's own left edge and separate nothing.
    const yearBoundaries = rows.slice(1).filter((r) => r.month.endsWith('-01')).map((r) => r.month)
    return { rows, segments: hasOther ? [...topCats, OTHER_KEY] : topCats, yearBoundaries }
  }, [trend, byCategory])

  if (rows.length === 0) {
    return <p className="py-10 text-center text-sm text-ink-faint">No months in this range.</p>
  }

  const anyPartial = rows.some((r) => r.partial)

  return (
    <div>
      {/* Legend: identity is never color-alone — names sit in ink, chips carry hue. */}
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 text-xs text-ink-mute">
            <span className="h-2 w-2 rounded-[1px]" style={{ background: hueFor(s) }} />
            {s}
          </span>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--color-line)" strokeWidth={1} />
          <XAxis
            dataKey="month"
            tickFormatter={formatMonthLabel}
            tickLine={false}
            axisLine={{ stroke: 'var(--color-line-strong)' }}
            tick={{ fill: 'var(--color-ink-faint)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          />
          {/* Year boundary: a plain divider, not a text label — the year is
              real data (the tooltip has it on hover), it doesn't need to be
              painted onto the axis to do its job here. */}
          {yearBoundaries.map((month) => (
            <ReferenceLine
              key={month}
              x={month}
              ifOverflow="extendDomain"
              stroke="var(--color-line-strong)"
              strokeDasharray="3 3"
            />
          ))}
          <YAxis
            tickFormatter={formatINRCompact}
            tickLine={false}
            axisLine={false}
            width={52}
            tick={{ fill: 'var(--color-ink-faint)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          />
          <Tooltip content={<CompositionTooltip segments={segments} />} cursor={{ fill: 'var(--color-carbon-2)', fillOpacity: 0.5 }} />
          {segments.map((s, si) => (
            <Bar
              key={s}
              dataKey={s}
              stackId="m"
              fill={hueFor(s)}
              // 2px surface-coloured gap between stacked fills, per the dataviz
              // mark spec. Doubles as the secondary encoding that makes any
              // residual CVD closeness legible as a boundary rather than a blend.
              stroke="var(--color-carbon-1)"
              strokeWidth={2}
              isAnimationActive
              animationDuration={500}
              radius={si === segments.length - 1 ? [3, 3, 0, 0] : undefined}
            >
              {rows.map((r) => (
                <Cell key={r.month} fillOpacity={r.partial ? 0.4 : 1} />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>

      {anyPartial && (
        <p className="mt-2 text-2xs text-ink-faint">
          Dimmed bar: current month in progress — figures incomplete until its statements land.
        </p>
      )}
    </div>
  )
}

type TooltipEntry = { payload?: Row }

function CompositionTooltip({
  active,
  payload,
  segments,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  segments: string[]
}) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="rounded-panel border border-line-strong bg-carbon-2 px-3.5 py-2.5 shadow-lg">
      <p className="eyebrow">
        {row.fullLabel}
        {row.partial ? ' · in progress' : ''}
      </p>
      <div className="mt-1.5 flex flex-col gap-0.5">
        {segments
          .filter((s) => (row[s] as number) > 0.005)
          .map((s) => (
            <div key={s} className="flex items-center justify-between gap-6 text-xs">
              <span className="inline-flex items-center gap-1.5 text-ink-mute">
                <span className="h-2 w-2 rounded-[1px]" style={{ background: hueFor(s) }} />
                {s}
              </span>
              <span className="figure text-ink">{formatINR(row[s] as number)}</span>
            </div>
          ))}
        <div className="mt-1 flex items-center justify-between gap-6 border-t border-line pt-1 text-xs">
          <span className="text-ink-mute">Net spend</span>
          <span className="figure text-ink">{formatINR(row.total)}</span>
        </div>
      </div>
    </div>
  )
}
