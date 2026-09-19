import PageHeader from '../shell/PageHeader'

export default function ComingSoon({
  eyebrow,
  title,
  phase,
  blurb,
}: {
  eyebrow: string
  title: string
  phase: string
  blurb: string
}) {
  return (
    <div>
      <PageHeader eyebrow={eyebrow} title={title} />
      <div className="flex flex-col items-start gap-2 rounded-panel border border-dashed border-line bg-carbon-1 px-6 py-10">
        <span className="rounded-chip border border-line px-2 py-0.5 font-display text-2xs font-semibold tracking-[0.09em] text-ink-faint uppercase">
          {phase}
        </span>
        <p className="max-w-md text-sm text-ink-mute">{blurb}</p>
      </div>
    </div>
  )
}
