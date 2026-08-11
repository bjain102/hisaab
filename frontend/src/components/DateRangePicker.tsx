import { useEffect, useRef, useState } from 'react'
import { DayPicker } from 'react-day-picker'
import type { DateRange, DayButtonProps } from 'react-day-picker'
import { useDismiss } from '../lib/useDismiss'

/** 'YYYY-MM-DD' → local-midnight Date. Avoids the UTC-parse shift that
 *  `new Date('YYYY-MM-DD')` introduces in negative-offset time zones. */
function parseISO(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function toISO(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
function formatShort(date: Date): string {
  return date.toLocaleDateString('en', { month: 'short', day: 'numeric' })
}

/** The calendar's own day button. Overridden (rather than styled purely via
 *  `classNames`) because the fill/outline logic is genuinely conditional —
 *  solid circle for range endpoints, flat continuous band for the days
 *  between them, an outline ring for today that's independent of selection.
 *  `modifiers` is the one prop that makes that conditional logic simple. */
function DayButton({ day: _day, modifiers, className: _className, style: _style, children, ...props }: DayButtonProps) {
  // react-day-picker only sets range_start/range_end once BOTH endpoints
  // exist (`Boolean(from && to && isSameDay(...))` in its source) — so the
  // very first click of a new range (from picked, to not yet) gets neither
  // flag and would otherwise render with no fill at all. `selected` is true
  // for that lone day too (and stays true for every day once a full range
  // exists), so excluding `range_middle` is what keeps this addition from
  // also painting the days *between* a completed range's endpoints.
  const isEndpoint = modifiers.range_start || modifiers.range_end || (modifiers.selected && !modifiers.range_middle)
  return (
    <button
      type="button"
      className={`flex h-9 w-9 items-center justify-center rounded-full text-sm transition-colors duration-150 ${
        modifiers.disabled
          ? 'cursor-not-allowed text-ink-faint/40'
          : modifiers.outside
            ? 'text-ink-faint/50 hover:bg-carbon-2'
            : isEndpoint
              ? 'font-semibold text-carbon-0'
              : 'text-ink hover:bg-carbon-2'
      } ${modifiers.today && !isEndpoint ? 'ring-1 ring-inset ring-sector-green' : ''}`}
      // react-day-picker's own `style` prop (destructured above as `_style`
      // and discarded) would otherwise land in `...props` and, spread after
      // this attribute, silently overwrite the endpoint fill with `undefined`.
      style={isEndpoint ? { background: 'var(--color-sector-green)' } : undefined}
      {...props}
    >
      {children}
    </button>
  )
}

export default function DateRangePicker({
  from,
  to,
  onChange,
  onClear,
  max,
}: {
  from: string
  to: string
  onChange: (range: { from: string; to: string }) => void
  /** When given, a small clear control appears once a range is set — for
   *  callers (like Transactions) where "no date filter" is itself a
   *  reachable, meaningful state and not just a preset away (unlike
   *  Dashboard, which has an "All time" range option for that). */
  onClear?: () => void
  /** ISO date string — days after this are disabled (e.g. today). */
  max?: string
}) {
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => parseISO(to || from))
  // The in-progress selection while the popover is open. Deliberately NOT
  // derived from `from`/`to` on every render: with `resetOnSelect`, the
  // picker starts a fresh range whenever the CURRENT selection is already
  // complete, so a draft that briefly holds only `from` (no `to`) must stay
  // incomplete — synthesizing `to = from` here would make every second
  // click look like "already complete" and reset again instead of
  // finishing the range.
  const [draft, setDraft] = useState<DateRange | undefined>(undefined)
  const rootRef = useRef<HTMLDivElement>(null)
  useDismiss(rootRef, open, () => setOpen(false))

  useEffect(() => {
    if (open) setDraft(from ? { from: parseISO(from), to: to ? parseISO(to) : undefined } : undefined)
    // Only reset the draft at the moment the popover opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Clicking a day only updates the draft — never applies it. The parent's
  // committed from/to (and any onClear side effect elsewhere) only change
  // when the user explicitly hits Apply, so an outside-click dismiss can
  // never silently commit a half-made or last-second selection.
  const handleSelect = (range: DateRange | undefined) => setDraft(range)

  const applyDraft = () => {
    if (!draft?.from || !draft.to) return
    onChange({ from: toISO(draft.from), to: toISO(draft.to) })
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative inline-flex items-center gap-1">
      <button
        type="button"
        onClick={() => {
          setMonth(parseISO(to || from || new Date().toISOString().slice(0, 10)))
          setOpen((v) => !v)
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
      >
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0 text-ink-faint" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 9h18M8 3v4M16 3v4" />
        </svg>
        {from ? (
          <span className="figure">
            {formatShort(parseISO(from))}
            {to && to !== from ? ` – ${formatShort(parseISO(to))}` : ''}
          </span>
        ) : (
          <span className="text-ink-faint">Select range</span>
        )}
      </button>
      {onClear && from && (
        <button
          type="button"
          onClick={() => {
            onClear()
            setOpen(false)
          }}
          aria-label="Clear date range"
          className="rounded-full p-1.5 text-ink-faint transition-colors duration-150 hover:bg-carbon-2 hover:text-ink"
        >
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}

      {open && (
        // `w-max` and `right-0` are both load-bearing, not cosmetic. Both call
        // sites (Dashboard's header actions, Transactions' filter row) put this
        // trigger at the RIGHT edge of the page. An absolutely-positioned box
        // anchored `left-0` there has almost no room to its right, so it
        // shrink-to-fits: the 7×36px day grid gets crushed (measured 192px wide
        // against a 284px natural width — cramped columns, a footer label
        // wrapping one word per line) AND still overflows the viewport by ~66px.
        // `w-max` refuses to compress below natural width; `right-0` opens the
        // popover leftward, into the space that actually exists.
        <div className="absolute top-full right-0 z-50 mt-1.5 w-max rounded-panel border border-line bg-carbon-1 p-4 shadow-xl [animation:popIn_150ms_var(--ease-out-hard)]">
          <DayPicker
            mode="range"
            resetOnSelect
            selected={draft}
            onSelect={handleSelect}
            month={month}
            onMonthChange={setMonth}
            disabled={max ? { after: parseISO(max) } : undefined}
            navLayout="around"
            components={{ DayButton }}
            classNames={{
              months: 'flex flex-col',
              month: 'grid grid-cols-[auto_1fr_auto] items-center gap-y-3',
              month_caption: 'text-center font-display text-sm font-bold text-ink',
              button_previous:
                'flex h-8 w-8 items-center justify-center rounded-full text-ink-mute transition-colors duration-150 hover:bg-carbon-2 hover:text-ink disabled:opacity-30',
              button_next:
                'flex h-8 w-8 items-center justify-center rounded-full text-ink-mute transition-colors duration-150 hover:bg-carbon-2 hover:text-ink disabled:opacity-30',
              chevron: 'h-4 w-4 fill-current',
              // border-separate + vertical spacing (not border-collapse) is
              // load-bearing: with cells touching edge-to-edge, a wide range
              // where most/all days are in-range renders as one solid block
              // spanning every week instead of a distinct band per week.
              month_grid: 'col-span-3 mt-3 border-separate [border-spacing:0_3px]',
              weekdays: '',
              weekday: 'w-9 pb-1 text-center text-2xs font-medium text-ink-faint',
              week: '',
              day: 'p-0 text-center',
              range_start: 'rounded-l-full bg-sector-green/15',
              range_end: 'rounded-r-full bg-sector-green/15',
              range_middle: 'bg-sector-green/15',
            }}
          />
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
            <span className="figure shrink-0 whitespace-nowrap text-xs text-ink-mute">
              {draft?.from && draft.to
                ? `${formatShort(draft.from)} – ${formatShort(draft.to)}`
                : draft?.from
                  ? `${formatShort(draft.from)} – pick an end date`
                  : 'Pick a start date'}
            </span>
            <div className="flex gap-2">
              <button type="button" onClick={() => setOpen(false)} className="btn-secondary !px-3 !py-1 !text-xs">
                <span>Cancel</span>
              </button>
              <button
                type="button"
                onClick={applyDraft}
                disabled={!draft?.from || !draft.to}
                className="btn-primary !px-3 !py-1 !text-xs disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span>Apply</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
