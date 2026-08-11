import { Line, LineChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { RewardHistoryPoint } from '../api/types'
import { formatINR } from '../lib/format'

function formatPoint(p: RewardHistoryPoint): string {
  return p.value_type === 'points' ? `${p.value.toLocaleString('en-IN')} pts` : formatINR(p.value)
}

/**
 * Single-series change-over-time — no axes/gridlines (a true sparkline), no
 * legend (one series names itself via the panel it sits in), but still gets
 * the hover layer: a dot + tooltip on the nearest point, per the house rule
 * that any line chart ships interaction, not just decoration.
 */
export default function RewardSparkline({ history }: { history: RewardHistoryPoint[] }) {
  if (history.length < 2) {
    return <p className="text-2xs text-ink-faint">Not enough history yet for a trend.</p>
  }
  return (
    <ResponsiveContainer width="100%" height={36}>
      <LineChart data={history} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
        <Tooltip
          content={<SparklineTooltip />}
          cursor={{ stroke: 'var(--color-line-strong)', strokeWidth: 1 }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="var(--color-series-amber)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3, fill: 'var(--color-series-amber)', stroke: 'var(--color-carbon-1)', strokeWidth: 1 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

type TooltipEntry = { payload?: RewardHistoryPoint }

function SparklineTooltip({ active, payload }: { active?: boolean; payload?: TooltipEntry[] }) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="rounded-panel border border-line-strong bg-carbon-2 px-2.5 py-1.5 shadow-lg">
      <p className="text-2xs text-ink-faint">{point.as_of}</p>
      <p className="figure text-xs text-ink">{formatPoint(point)}</p>
    </div>
  )
}
