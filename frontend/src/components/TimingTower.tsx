import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { Link } from 'react-router'

export type TowerRow = {
  id: string
  label: string
  value: string
  /** 0..1 — drives the pace bar under the row. */
  share?: number
  /** Right-side slot, e.g. a DeltaChip or a share percentage. */
  trailing?: ReactNode
  /** Second line under the label — dimension metadata (counts, averages) that
   *  would crowd the trailing slot. Optional: rows without it are unchanged. */
  sublabel?: ReactNode
  /** When set, the row becomes a link (drill-down). Absent leaves today's
   *  non-interactive row with byte-identical markup. */
  href?: string
  /** Tooltip for the row body — used to state a drill-down's caveats. */
  title?: string
}

/**
 * The signature component: an F1 timing tower. Rank chip · label · mono
 * value · trailing slot, with a pace bar under each row. Rows FLIP-reorder
 * (layout animation) when ranking changes, and stagger in on mount.
 */
export default function TimingTower({
  rows,
  barClass = 'bg-series-amber',
  leaderBarClass,
}: {
  rows: TowerRow[]
  barClass?: string
  /** Optional distinct bar for P1 (e.g. sector purple = session best). */
  leaderBarClass?: string
}) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">No data in this range.</p>
  }
  return (
    <motion.ol
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.045 } } }}
      className="flex flex-col"
    >
      {rows.map((row, i) => {
        const body = (
          <>
            <div className="flex items-center gap-3">
              <span
                className={`figure w-7 shrink-0 rounded-chip py-0.5 text-center text-2xs ${
                  i === 0 ? 'bg-carbon-3 text-ink' : 'bg-carbon-2 text-ink-mute'
                }`}
              >
                P{i + 1}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm text-ink group-hover:text-brand-bright" title={row.label}>
                  {row.label}
                </span>
                {row.sublabel && (
                  <span className="truncate text-2xs text-ink-faint">{row.sublabel}</span>
                )}
              </span>
              <span className="figure shrink-0 text-sm text-ink">{row.value}</span>
              {row.trailing && <span className="shrink-0">{row.trailing}</span>}
            </div>
            {row.share !== undefined && (
              <div className="mt-1.5 ml-10 h-0.5 overflow-hidden rounded-chip bg-carbon-2">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(100, Math.max(0, row.share * 100))}%` }}
                  transition={{ duration: 0.5, ease: [0.2, 0, 0, 1], delay: 0.1 + i * 0.045 }}
                  className={`h-full ${i === 0 && leaderBarClass ? leaderBarClass : barClass}`}
                />
              </div>
            )}
          </>
        )
        return (
          <motion.li
            key={row.id}
            layout
            variants={{
              hidden: { opacity: 0, x: -10 },
              show: { opacity: 1, x: 0, transition: { duration: 0.22, ease: [0.2, 0, 0, 1] } },
            }}
            transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
            className="border-b border-line py-2.5 last:border-b-0"
          >
            {row.href ? (
              // A real <a> (not onClick on the li) so the row gets keyboard
              // focus, Enter, and open-in-new-tab for free. The negative margin
              // is cancelled by equal padding, so row HEIGHT is unchanged and
              // the layout animation still measures what it did before.
              <Link
                to={row.href}
                title={row.title}
                aria-label={`${row.label}, ${row.value} — view transactions`}
                className="group -mx-2 block rounded-panel px-2 transition-colors duration-150 hover:bg-carbon-2/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand-bright"
              >
                {body}
              </Link>
            ) : (
              body
            )}
          </motion.li>
        )
      })}
    </motion.ol>
  )
}
