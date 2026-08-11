import type { ReactNode } from 'react'
import { motion } from 'motion/react'

export type Column<T> = {
  key: string
  header: string
  align?: 'left' | 'right'
  /** Right-aligned numeric columns render in figure (mono, tabular) style. */
  numeric?: boolean
  cell: (row: T) => ReactNode
}

const rowVariants = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0, transition: { duration: 0.2, ease: [0.2, 0, 0, 1] as const } },
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = 'Nothing here yet.',
  motionRows = false,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  empty?: string
  /** Animate rows in with a stagger on mount/filter change. Opt-in — off by
   * default so existing plain usages (e.g. the /kit gallery) are unaffected. */
  motionRows?: boolean
}) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">{empty}</p>
  }
  const Row = motionRows ? motion.tr : 'tr'
  const rowProps = motionRows
    ? { variants: rowVariants, initial: 'hidden' as const, animate: 'show' as const, layout: true as const }
    : {}
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line-strong">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 font-display text-2xs font-semibold tracking-[0.09em] text-ink-faint uppercase ${
                  c.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <motion.tbody
          initial={motionRows ? 'hidden' : false}
          animate={motionRows ? 'show' : false}
          variants={motionRows ? { show: { transition: { staggerChildren: 0.03 } } } : undefined}
        >
          {rows.map((row) => (
            <Row key={rowKey(row)} className="border-b border-line last:border-b-0" {...rowProps}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-3 py-2 text-ink ${c.align === 'right' ? 'text-right' : 'text-left'} ${
                    c.numeric ? 'figure' : ''
                  }`}
                >
                  {c.cell(row)}
                </td>
              ))}
            </Row>
          ))}
        </motion.tbody>
      </table>
    </div>
  )
}
