import { useRef, useState } from 'react'
import { useDismiss } from '../lib/useDismiss'

export type SelectOption = { value: string; label: string }

/** Custom listbox dropdown — same external API as the native <select> it
 *  replaced, so every call site (Dashboard, Transactions, Import, modals,
 *  Kit) needed no changes. Native selects render an unstyleable OS popup
 *  that clashed with the rest of the app's design; this one matches it. */
export default function Select({
  label,
  value,
  options,
  onChange,
  className = '',
}: {
  label: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useDismiss(rootRef, open, () => setOpen(false))

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={rootRef} className={`relative inline-block ${className}`}>
      <span className="sr-only">{label}</span>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
      >
        <span className="min-w-0 flex-1 truncate text-left">{selected?.label ?? value}</span>
        <svg
          viewBox="0 0 24 24"
          className={`h-3.5 w-3.5 shrink-0 fill-current text-ink-faint transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        >
          <polygon points="6.77 8 12.5 13.57 18.24 8 20 9.72 12.5 17 5 9.72" />
        </svg>
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label={label}
          className="absolute top-full left-0 z-50 mt-1.5 max-h-64 min-w-full overflow-auto rounded-panel border border-line bg-carbon-1 p-1 shadow-xl [animation:popIn_150ms_var(--ease-out-hard)]"
        >
          {options.map((o) => (
            <li key={o.value} role="option" aria-selected={o.value === value}>
              <button
                type="button"
                onClick={() => {
                  onChange(o.value)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between gap-2 rounded-chip px-3 py-1.5 text-left text-sm whitespace-nowrap transition-colors duration-150 ${
                  o.value === value ? 'text-ink' : 'text-ink-mute hover:bg-carbon-2 hover:text-ink'
                }`}
                style={o.value === value ? { background: 'var(--color-sector-green-dim)' } : undefined}
              >
                {o.label}
                {o.value === value && (
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0 fill-current text-sector-green">
                    <polygon points="9.86 18.61 4 12.75 5.41 11.34 9.86 15.78 18.59 7.05 20 8.46" />
                  </svg>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
