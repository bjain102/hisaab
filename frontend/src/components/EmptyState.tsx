export default function EmptyState({
  chip,
  title,
  blurb,
}: {
  chip?: string
  title: string
  blurb?: string
}) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-panel border border-dashed border-line bg-carbon-1 px-6 py-10">
      {chip && (
        <span className="rounded-chip border border-line px-2 py-0.5 font-display text-2xs font-semibold tracking-[0.09em] text-ink-faint uppercase">
          {chip}
        </span>
      )}
      <p className="text-sm text-ink">{title}</p>
      {blurb && <p className="max-w-md text-sm text-ink-mute">{blurb}</p>}
    </div>
  )
}
