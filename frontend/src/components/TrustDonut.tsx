/**
 * Conic-gradient trust ring — replaces the flat "Category trust" StatCard.
 * A ring + inner circle is structurally unrelated to StatCard's label/value
 * stack, so it's its own small component rather than a StatCard variant.
 */
export default function TrustDonut({
  pct,
  label = 'Category trust',
  title,
}: {
  pct: number
  label?: string
  title?: string
}) {
  return (
    <div
      // Same lift-on-hover idiom as its hero-row siblings (HeroSpendCard,
      // StatCard) — this card predates that sweep (it was hand-rolled, not
      // a StatCard variant) and had quietly fallen out of step with them.
      className="flex flex-col items-center justify-center gap-2.5 rounded-panel border border-line bg-carbon-1 px-4 py-3.5 text-center transition-[transform,border-color] duration-150 hover:-translate-y-0.5 hover:border-line-strong"
      title={title}
    >
      <div
        className="flex h-[74px] w-[74px] items-center justify-center rounded-full"
        style={{
          background: `conic-gradient(var(--color-sector-green) 0% ${pct}%, var(--color-carbon-3) ${pct}% 100%)`,
        }}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-carbon-1">
          <span className="figure text-sm">{pct}%</span>
        </div>
      </div>
      <p className="eyebrow">{label}</p>
    </div>
  )
}
