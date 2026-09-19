import type { ReactNode } from 'react'

/**
 * Hero stat slot. `reserved` renders the designed empty state for slots that
 * light up in later phases — dimmed, chip-labelled, never a blank.
 */
export default function StatCard({
  label,
  children,
  meta,
  reserved,
  className = '',
}: {
  label: string
  children?: ReactNode
  meta?: ReactNode
  reserved?: { phase: string; note: string }
  className?: string
}) {
  if (reserved) {
    return (
      <div
        className={`flex flex-col gap-1.5 rounded-panel border border-dashed border-line bg-carbon-1/50 px-4 py-3.5 ${className}`}
      >
        <span className="eyebrow">{label}</span>
        <span className="w-fit rounded-chip border border-line px-1.5 py-0.5 font-display text-2xs font-semibold tracking-[0.09em] text-ink-faint uppercase">
          {reserved.phase}
        </span>
        <span className="text-xs text-ink-faint">{reserved.note}</span>
      </div>
    )
  }

  return (
    <div
      // Same lift-on-hover idiom as HeroSpendCard/RewardCard — the hero row's
      // sibling cards should feel like the same kind of surface, not a
      // static one next to two interactive ones.
      className={`flex flex-col gap-2 rounded-panel border border-line bg-carbon-1 px-4 py-4 transition-[transform,border-color] duration-150 hover:-translate-y-0.5 hover:border-line-strong ${className}`}
    >
      <span className="eyebrow">{label}</span>
      <span className="text-xl leading-none text-ink">{children}</span>
      {meta && <span className="text-xs leading-relaxed text-ink-faint">{meta}</span>}
    </div>
  )
}
