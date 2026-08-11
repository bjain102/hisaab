import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import PageHeader from '../shell/PageHeader'
import Panel from '../components/Panel'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import Select from '../components/Select'
import DateRangePicker from '../components/DateRangePicker'
import Skeleton from '../components/Skeleton'
import RecategorizeModal from '../components/RecategorizeModal'
import ReviewQueue from '../components/ReviewQueue'
import { useCards, useCategories, useReviewQueue, useTransactions } from '../api/hooks'
import type { Transaction } from '../api/types'
import { formatINR } from '../lib/format'
import { useDebouncedValue } from '../lib/useDebouncedValue'

const SORT_OPTIONS = [
  { value: 'date_desc', label: 'Newest first' },
  { value: 'date_asc', label: 'Oldest first' },
  { value: 'amount_desc', label: 'Highest amount' },
  { value: 'amount_asc', label: 'Lowest amount' },
]

const TYPE_OPTIONS = [
  { value: '', label: 'All types' },
  { value: 'debit', label: 'Spends' },
  { value: 'credit', label: 'Credits' },
]

/** An unknown value would leave a Select showing nothing — fall back instead. */
const readType = (v: string | null) => (v === 'debit' || v === 'credit' ? v : '')
const readSort = (v: string | null) =>
  SORT_OPTIONS.some((o) => o.value === v) ? (v as string) : 'date_desc'

export default function Transactions() {
  // Filters seed from the URL so a dashboard drill-down lands pre-filtered (the
  // param names are the /api/transactions names — see lib/drilldown.ts). State
  // stays local afterwards and is deliberately NOT written back: the search box
  // is debounced per keystroke and would otherwise spam browser history.
  const [searchParams] = useSearchParams()
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '')
  const [card, setCard] = useState(() => searchParams.get('card') ?? '')
  const [category, setCategory] = useState(() => searchParams.get('category') ?? '')
  const [type, setType] = useState(() => readType(searchParams.get('type')))
  const [sort, setSort] = useState(() => readSort(searchParams.get('sort')))
  const [fromDate, setFromDate] = useState(() => searchParams.get('from_date') ?? '')
  const [toDate, setToDate] = useState(() => searchParams.get('to_date') ?? '')
  const [recatTarget, setRecatTarget] = useState<Transaction | null>(null)
  const [mode, setMode] = useState<'all' | 'review'>('all')

  // Lazy initialisers run once. If the query string changes while this page is
  // already mounted (drill-down → back → a different drill-down), re-seed.
  const qs = searchParams.toString()
  useEffect(() => {
    if (!qs) return // a bare /transactions must never wipe filters typed by hand
    const p = new URLSearchParams(qs)
    setSearch(p.get('search') ?? '')
    setCard(p.get('card') ?? '')
    setCategory(p.get('category') ?? '')
    setType(readType(p.get('type')))
    setSort(readSort(p.get('sort')))
    setFromDate(p.get('from_date') ?? '')
    setToDate(p.get('to_date') ?? '')
    setMode('all') // a drill-down must never land in the review queue
  }, [qs])

  const debouncedSearch = useDebouncedValue(search)
  const { data: cards } = useCards()
  const { data: categories } = useCategories()
  const { data: reviewQueue } = useReviewQueue()
  const queueCount = reviewQueue?.length ?? 0

  const filters = useMemo(
    () => ({
      search: debouncedSearch || undefined,
      card: card || undefined,
      category: category || undefined,
      type: type || undefined,
      sort,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
    }),
    [debouncedSearch, card, category, type, sort, fromDate, toDate],
  )

  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage } = useTransactions(filters)
  const rows = useMemo(() => data?.pages.flatMap((p) => p.rows) ?? [], [data])
  const total = data?.pages[0]?.total ?? 0

  const columns: Column<Transaction>[] = [
    { key: 'date', header: 'Date', cell: (t) => t.date },
    {
      key: 'description',
      header: 'Description',
      cell: (t) => (
        <span className="inline-flex items-center gap-2">
          <span className="max-w-[280px] truncate" title={t.description}>
            {t.description}
          </span>
          {t.is_cashback ? (
            <span className="rounded-full border border-sector-green/30 bg-sector-green/10 px-2 py-0.5 text-2xs text-sector-green">
              cashback
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'card',
      header: 'Card',
      cell: (t) => (
        <span className="rounded-full border border-line bg-carbon-2 px-2.5 py-0.5 text-xs text-ink-mute">
          {t.card_label}
        </span>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      cell: (t) => (
        <span className="inline-flex flex-col gap-0.5">
          <button
            onClick={() => setRecatTarget(t)}
            className="w-fit rounded-full border border-line px-2.5 py-0.5 text-xs text-ink transition-colors duration-150 hover:border-brand-bright hover:text-brand-bright"
          >
            {t.category}
          </button>
          {t.bank_category ? (
            <span className="text-2xs text-ink-faint" title="Bank category">
              bank: {t.bank_category}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'amount',
      header: 'Amount',
      align: 'right',
      numeric: true,
      cell: (t) => (
        <span className={t.type === 'credit' ? 'text-sector-green' : 'text-ink'}>
          {t.type === 'credit' ? '+' : ''}
          {formatINR(t.amount)}
        </span>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Cards"
        title="Transactions"
        sub="Search, filter, and fix categorization."
        actions={
          <div className="flex gap-1 rounded-full border border-line bg-carbon-2 p-1">
            {(['all', 'review'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded-full px-3.5 py-1.5 text-xs transition-colors duration-150 ${
                  mode === m ? 'bg-carbon-3 text-ink' : 'text-ink-mute hover:text-ink'
                }`}
              >
                {m === 'all' ? 'All' : 'Review queue'}
                {m === 'review' && queueCount > 0 && (
                  <span className="ml-1.5 rounded-full bg-series-amber/20 px-1.5 py-0.5 text-2xs text-series-amber">
                    {queueCount}
                  </span>
                )}
              </button>
            ))}
          </div>
        }
      />

      {mode === 'review' ? (
        <Panel title="Review queue" meta="unconfirmed spend, grouped by merchant, biggest first">
          <ReviewQueue />
        </Panel>
      ) : (
        <>
      <Panel>
        <div className="flex flex-wrap items-end gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search merchant or description…"
            className="min-w-[220px] flex-1 rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint transition-colors duration-150 focus:border-brand-bright focus:outline-none"
          />
          <Select
            label="Card"
            value={card}
            onChange={setCard}
            options={[{ value: '', label: 'All cards' }, ...(cards ?? []).map((c) => ({ value: c, label: c }))]}
          />
          <Select
            label="Category"
            value={category}
            onChange={setCategory}
            options={[
              { value: '', label: 'All categories' },
              ...(categories ?? []).map((c) => ({ value: c, label: c })),
            ]}
          />
          <Select label="Type" value={type} onChange={setType} options={TYPE_OPTIONS} />
          <Select label="Sort" value={sort} onChange={setSort} options={SORT_OPTIONS} />
          <DateRangePicker
            from={fromDate}
            to={toDate}
            onChange={({ from: f, to: t }) => {
              setFromDate(f)
              setToDate(t)
            }}
            onClear={() => {
              setFromDate('')
              setToDate('')
            }}
          />
        </div>
      </Panel>

      <Panel title="Results" meta={total ? `${rows.length} of ${total}` : undefined}>
        {isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton shape="line" className="w-full" />
            <Skeleton shape="line" className="w-full" />
            <Skeleton shape="line" className="w-5/6" />
          </div>
        ) : (
          <>
            <DataTable<Transaction>
              columns={columns}
              rows={rows}
              rowKey={(t) => String(t.id)}
              empty="No transactions match these filters."
              motionRows
            />
            {hasNextPage && (
              <div className="mt-4 flex justify-center">
                <button
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                  className="rounded-panel border border-line bg-carbon-2 px-4 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong disabled:opacity-50"
                >
                  {isFetchingNextPage ? 'Loading…' : `Load more (${total - rows.length} remaining)`}
                </button>
              </div>
            )}
          </>
        )}
      </Panel>
        </>
      )}

      <RecategorizeModal
        open={recatTarget !== null}
        transactionId={recatTarget?.id ?? null}
        merchant={recatTarget?.description ?? ''}
        currentCategory={recatTarget?.category ?? ''}
        onClose={() => setRecatTarget(null)}
      />
    </div>
  )
}
