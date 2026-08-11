import type { ReactNode } from 'react'

export default function PageHeader({
  eyebrow,
  title,
  sub,
  actions,
}: {
  eyebrow: string
  title: string
  sub?: string
  actions?: ReactNode
}) {
  return (
    <header className="mb-8 flex items-end justify-between gap-4">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="display mt-1 text-2xl leading-none tracking-tight text-ink">{title}</h1>
        {sub && <p className="mt-2 text-sm text-ink-mute">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </header>
  )
}
