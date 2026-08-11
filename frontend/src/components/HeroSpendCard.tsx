import AnimatedNumber from './AnimatedNumber'
import { formatINR } from '../lib/format'

export type SparkPoint = { month: string; total: number }

/**
 * The dashboard's tallest hero card — a corner gradient blob, a count-up
 * figure (reusing AnimatedNumber, which already respects
 * prefers-reduced-motion), and a trailing sparkline of the last few months'
 * spend. Structurally unrelated to StatCard's simple label/value/meta stack,
 * so it's its own component rather than a StatCard variant.
 */
export default function HeroSpendCard({
  value,
  refundCredits,
  sparkline,
  className = '',
}: {
  value: number
  refundCredits: number
  sparkline: SparkPoint[]
  className?: string
}) {
  const max = Math.max(...sparkline.map((p) => p.total), 1)
  return (
    <div
      className={`relative overflow-hidden rounded-[22px] border border-line bg-gradient-to-br from-carbon-2 to-carbon-1 p-7 transition-transform duration-150 hover:-translate-y-0.5 ${className}`}
    >
      <div
        className="pointer-events-none absolute -top-16 -right-16 h-56 w-56 rounded-full"
        style={{ background: 'radial-gradient(circle, var(--color-sector-green-dim), transparent 70%)' }}
        aria-hidden="true"
      />
      <p className="eyebrow relative mb-3.5">Net spend</p>
      <AnimatedNumber value={value} format={formatINR} className="relative block text-2xl" />
      <p className="relative mt-3.5 mb-5 text-xs text-ink-faint">
        −{formatINR(refundCredits)} refunds applied
      </p>
      {sparkline.length > 0 && (
        <div className="relative flex h-14 items-end gap-1.5">
          {sparkline.map((p, i) => (
            <span
              key={p.month}
              className="flex-1 rounded-t-[5px] rounded-b-[2px]"
              style={{
                height: `${Math.max(8, (p.total / max) * 100)}%`,
                opacity: 0.4 + (i / Math.max(sparkline.length - 1, 1)) * 0.5,
                background: 'linear-gradient(180deg, var(--color-sector-green), var(--color-sector-green-dim))',
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
