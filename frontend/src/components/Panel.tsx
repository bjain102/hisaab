import type { ReactNode } from 'react'

export default function Panel({
  title,
  meta,
  children,
  className = '',
  interactive = false,
}: {
  title?: string
  meta?: ReactNode
  children: ReactNode
  className?: string
  /** Same lift-on-hover idiom as HeroSpendCard/StatCard/RewardCard — for a
   *  panel a reader browses and drills into (Dashboard's report cards), not
   *  a form/filter surface (Transactions' filter bar, Import's upload
   *  panel) where a hover lift would read as "click me" and be wrong. Off
   *  by default so only call sites that want it opt in. */
  interactive?: boolean
}) {
  return (
    <section
      className={`rounded-panel border border-line bg-carbon-1 ${
        interactive ? 'transition-[transform,border-color] duration-150 hover:-translate-y-0.5 hover:border-line-strong' : ''
      } ${className}`}
    >
      {(title || meta) && (
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          {title && <h3 className="font-display text-sm font-bold text-ink">{title}</h3>}
          {meta && <div className="text-xs text-ink-faint">{meta}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}
