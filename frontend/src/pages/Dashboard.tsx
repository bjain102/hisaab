import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import PageHeader from '../shell/PageHeader'
import Panel from '../components/Panel'
import StatCard from '../components/StatCard'
import HeroSpendCard from '../components/HeroSpendCard'
import TrustDonut from '../components/TrustDonut'
import DeltaChip from '../components/DeltaChip'
import TimingTower from '../components/TimingTower'
import type { TowerRow } from '../components/TimingTower'
import Select from '../components/Select'
import DateRangePicker from '../components/DateRangePicker'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import MonthlyComposition from '../components/MonthlyComposition'
import { useCards, useGapReport, useGuidance, useRatesSummary, useSummary } from '../api/hooks'
import { dateRangeFor, currentMonthKey, RANGE_OPTIONS } from '../lib/dateRange'
import type { RangeKey } from '../lib/dateRange'
import type { ReconStatus } from '../api/types'
import {
  formatINR,
  formatINRCompact,
  formatINRSigned,
  formatMonthLabel,
  formatPercent,
  formatRate,
} from '../lib/format'
import { REWARDS_INTELLIGENCE_ENABLED } from '../lib/features'
import { transactionsUrl } from '../lib/drilldown'
import { categoryMovers } from '../lib/deltaMovers'

// Local date, not UTC — toISOString() shifts across midnight in any timezone
// ahead of UTC, which would make "today" wrong by a day for many users and,
// combined with the calendar's own local-time `today` modifier, disable
// today's cell instead of just outlining it.
const todayISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function Dashboard() {
  const [card, setCard] = useState('')
  const [range, setRange] = useState<RangeKey>('all')
  const [customFrom, setCustomFrom] = useState('2000-01-01')
  const [customTo, setCustomTo] = useState(todayISO)

  const { from, to } = useMemo(
    () => (range === 'custom' ? { from: customFrom, to: customTo } : dateRangeFor(range)),
    [range, customFrom, customTo],
  )
  const summary = useSummary({ from_date: from, to_date: to, card: card || undefined })
  const rates = useRatesSummary(
    { from_date: from, to_date: to, card: card || undefined },
    { enabled: REWARDS_INTELLIGENCE_ENABLED },
  )
  const gapReport = useGapReport({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const guidance = useGuidance({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const cards = useCards()

  const s = summary.data
  const r = rates.data

  // The gap hero shows the latest COMPLETE month (current month's loss is
  // still moving — same honesty rule as the vs-last-month delta).
  const gapMonth = useMemo(() => {
    const months = gapReport.data?.months.filter((m) => m.month < currentMonthKey())
    return months && months.length > 0 ? months[months.length - 1] : null
  }, [gapReport.data])

  // vs-last-month: last two COMPLETE months only. The month in progress is
  // excluded — comparing a full month against 13 days is the legacy
  // dashboard's "monthly average" mistake in new clothes.
  const delta = useMemo(() => {
    if (!s) return null
    const complete = s.monthly_trend.filter((m) => m.month < currentMonthKey())
    if (complete.length < 2) return null
    const last = complete[complete.length - 1]
    const prev = complete[complete.length - 2]
    const value = last.total - prev.total
    return {
      value,
      last: last.month,
      prev: prev.month,
      ...categoryMovers(s.monthly_by_category, prev.month, last.month, value),
    }
  }, [s])

  const rateByCard = useMemo(() => {
    const m = new Map<string, { rate: number | null; recon: ReconStatus }>()
    if (REWARDS_INTELLIGENCE_ENABLED) {
      r?.by_card.forEach((c) => m.set(c.card_label, { rate: c.rate, recon: c.recon_status }))
    }
    return m
  }, [r])

  const maxCard = s ? Math.max(...s.by_card.map((c) => c.total), 1) : 1
  const cardRows: TowerRow[] =
    s?.by_card.map((c) => {
      const rc = rateByCard.get(c.card_label)
      return {
        id: c.card_label,
        label: c.card_label,
        // Average ticket uses GROSS debits, not net: the typical size of an
        // actual charge, not one discounted by refunds it never carried.
        sublabel:
          c.count > 0
            ? `${c.count} txns · ${formatINR(c.gross_debits / c.count)} avg`
            : 'no debits in range',
        value: formatINR(c.total),
        share: c.total / maxCard,
        href: transactionsUrl({ from, to, card: c.card_label }),
        trailing: (
          <span className="figure flex items-center justify-end gap-2 text-xs">
            {rc && rc.rate !== null && (
              <span className="text-series-amber" title="Effective reward rate, net of fees & bonuses">
                {formatRate(rc.rate)}
              </span>
            )}
            {rc && <ReconBadge status={rc.recon} />}
            <UpiPill count={c.upi_count} of={c.count} />
            <span className="w-10 text-right text-ink-faint">
              {s.total_spend > 0 ? formatPercent(c.total / s.total_spend) : '—'}
            </span>
          </span>
        ),
      }
    }) ?? []

  const maxCat = s ? Math.max(...s.by_category.map((c) => c.total), 1) : 1
  const catRows: TowerRow[] =
    s?.by_category.slice(0, 8).map((c) => ({
      id: c.category,
      label: c.category,
      value: formatINR(c.total),
      share: c.total / maxCat,
      // Carries the dashboard's active card filter as well as the window, so
      // the filtered list reconciles with the row that was clicked.
      href: transactionsUrl({ from, to, card: card || undefined, category: c.category }),
      trailing: (
        <span className="figure w-10 text-right text-xs text-ink-faint">
          {s.category_sum > 0 ? formatPercent(c.total / s.category_sum) : '—'}
        </span>
      ),
    })) ?? []

  const maxMerchant = s ? Math.max(...s.top_merchants.map((m) => m.total), 1) : 1
  const merchantRows: TowerRow[] =
    s?.top_merchants.slice(0, 8).map((m) => ({
      id: m.name,
      label: m.name,
      value: formatINR(m.total),
      share: m.total / maxMerchant,
      href: transactionsUrl({ from, to, card: card || undefined, merchant: m.name }),
      // Merchant rows are canonical (aliases merged); /api/transactions can only
      // do a description LIKE, so the drill-down under-matches aliases and
      // over-matches substrings. Say so on the row rather than let the totals
      // quietly disagree.
      title: `Opens a description search for "${m.name}". Merchant rows are canonical (aliases merged), so a text search can't reproduce that grouping — the list total may differ from ${formatINR(m.total)}.`,
      trailing: m.confirmed ? (
        <span
          title="Confirmed merchant"
          className="rounded-chip border border-sector-green/30 bg-sector-green/10 px-1.5 py-0.5 text-2xs text-sector-green"
        >
          ✓
        </span>
      ) : undefined,
    })) ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        sub="Where your money actually goes — and what it pays back."
        actions={
          <>
            <Select
              label="Card"
              value={card}
              onChange={setCard}
              options={[
                { value: '', label: 'All cards' },
                ...(cards.data?.map((c) => ({ value: c, label: c })) ?? []),
              ]}
            />
            <Select
              label="Date range"
              value={range}
              onChange={(v) => setRange(v as RangeKey)}
              options={RANGE_OPTIONS}
            />
            {range === 'custom' && (
              <DateRangePicker
                from={customFrom}
                to={customTo}
                max={todayISO()}
                onChange={({ from: f, to: t }) => {
                  setCustomFrom(f)
                  setCustomTo(t)
                }}
              />
            )}
          </>
        }
      />

      {summary.isError ? (
        <EmptyState
          chip="API unreachable"
          title="Could not load the summary."
          blurb="Is Flask running on port 5000? Start it with: python app.py"
        />
      ) : (
        <>
          {/* Hero — 3 slots normally; rewards intelligence (rate + gap) adds
              2 more when re-enabled, see lib/features.ts. Archived widgets
              are omitted outright here, not shown as placeholders. */}
          <div
            className={`grid grid-cols-1 gap-3 ${
              REWARDS_INTELLIGENCE_ENABLED ? 'sm:grid-cols-2 xl:grid-cols-5' : 'sm:grid-cols-[1.3fr_1fr_1fr]'
            }`}
          >
            {s ? (
              <>
                <HeroSpendCard
                  value={s.total_spend}
                  refundCredits={s.refund_credits}
                  sparkline={s.monthly_trend.slice(-6)}
                />
                <StatCard
                  label="vs last month"
                  meta={
                    delta ? (
                      <span className="flex flex-col gap-2">
                        <span>
                          {formatMonthLabel(delta.last)} vs {formatMonthLabel(delta.prev)}, complete
                          months
                        </span>
                        {delta.movers.length > 0 && (
                          <>
                            <span className="flex flex-wrap items-center gap-1.5">
                              {delta.movers.slice(0, 3).map((m) => (
                                <span
                                  key={m.category}
                                  title={`${m.category}: ${formatINR(m.prev)} → ${formatINR(m.last)}`}
                                  className={`rounded-chip border px-2 py-1 text-2xs whitespace-nowrap ${
                                    m.delta > 0
                                      ? 'border-sector-yellow/30 text-sector-yellow'
                                      : 'border-sector-green/30 text-sector-green'
                                  }`}
                                >
                                  {m.category} {formatINRSigned(m.delta)}
                                </span>
                              ))}
                            </span>
                            {/* Never claim a complete decomposition: the trend
                                floors each month at zero while the per-category
                                figures stay signed, so they can disagree. */}
                            <span className="text-ink-faint">
                              {delta.reconciles
                                ? `top movers of ${delta.movedCount} categories that changed`
                                : `top movers of ${delta.movedCount} — a month floored at ₹0, so these don't sum to the headline`}
                            </span>
                          </>
                        )}
                      </span>
                    ) : (
                      'needs two complete months'
                    )
                  }
                >
                  {delta ? (
                    <DeltaChip value={delta.value} goodWhen="down" className="text-lg" />
                  ) : (
                    <span className="figure text-lg text-ink-faint">—</span>
                  )}
                </StatCard>
                {REWARDS_INTELLIGENCE_ENABLED && (
                  <StatCard
                    label="Effective reward rate"
                    meta={
                      r
                        ? `net of fees & bonuses on ${formatINR(r.spend)} spend`
                        : 'blended across cards, net of fees'
                    }
                  >
                    {r && r.blended_rate !== null ? (
                      <span className="figure text-lg text-series-amber">{formatRate(r.blended_rate)}</span>
                    ) : (
                      <span className="figure text-lg text-ink-faint">—</span>
                    )}
                  </StatCard>
                )}
                {REWARDS_INTELLIGENCE_ENABLED && (
                  <Link to="/rewards" className="contents">
                    <StatCard
                      label="Gap — left on table"
                      meta={
                        gapMonth
                          ? `in ${formatMonthLabel(gapMonth.month)} — best-card counterfactual, cap-aware`
                          : 'needs a complete month of confirmed spend'
                      }
                      className="cursor-pointer transition-colors duration-150 hover:border-alert/40"
                    >
                      {gapMonth ? (
                        <span className="figure text-lg text-alert">{formatINR(gapMonth.total_loss)}</span>
                      ) : (
                        <span className="figure text-lg text-ink-faint">—</span>
                      )}
                    </StatCard>
                  </Link>
                )}
                <TrustDonut pct={Math.round(s.trust * 100)} title="Category trust — % of spend confirmed or pinned" />
              </>
            ) : (
              <>
                <HeroSkeleton />
                <HeroSkeleton />
                {REWARDS_INTELLIGENCE_ENABLED && <HeroSkeleton />}
                {REWARDS_INTELLIGENCE_ENABLED && <HeroSkeleton />}
                <HeroSkeleton />
              </>
            )}
          </div>

          {REWARDS_INTELLIGENCE_ENABLED && guidance.data && guidance.data.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-panel border border-line bg-carbon-1 px-4 py-2.5">
              <span className="eyebrow shrink-0">This cycle</span>
              {guidance.data.slice(0, 5).map((g) => (
                <span
                  key={g.category}
                  className="rounded-chip border border-line bg-carbon-2 px-2 py-1 text-xs text-ink-mute"
                  title={`Trailing 3-month counterfactual: ${g.trailing_rate !== null ? formatRate(g.trailing_rate) : '—'} on ${formatINR(g.trailing_spend)} spend`}
                >
                  {g.category} → <span className="text-ink">{g.card_label}</span>
                  {g.headroom !== null && (
                    <span className="text-series-amber"> · {formatINR(g.headroom)} headroom</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {s && s.by_channel.upi.count + s.by_channel.card.count > 0 && (
            <Panel
              interactive
              title="Behaviour"
              meta={<span className="text-2xs text-ink-faint">UPI-on-credit-card vs card auth</span>}
            >
              <p className="mb-4 text-xs text-ink-faint">Same debits, two very different stories.</p>
              <div className="flex flex-col gap-3.5">
                <ChannelSplitBar
                  label="Transactions"
                  upi={s.by_channel.upi.count}
                  other={s.by_channel.card.count}
                  fmt={(n) => String(n)}
                />
                <ChannelSplitBar
                  label="Rupees"
                  upi={s.by_channel.upi.total}
                  other={s.by_channel.card.total}
                  fmt={formatINRCompact}
                />
              </div>
            </Panel>
          )}

          <Panel interactive title="Monthly composition" meta="net spend by category">
            {s ? (
              <MonthlyComposition trend={s.monthly_trend} byCategory={s.monthly_by_category} />
            ) : (
              <Skeleton shape="block" className="h-64" />
            )}
          </Panel>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Panel interactive title="By card" meta="share of net spend">
              {s ? <TimingTower rows={cardRows} /> : <TowerSkeleton />}
            </Panel>
            <Panel interactive title="Category breakdown" meta="net after refunds, ranked">
              {s ? <TimingTower rows={catRows} /> : <TowerSkeleton />}
            </Panel>
          </div>

          <Panel
            interactive
            title="Top merchants"
            meta="gross debits — canonical merchants (✓ confirmed) · click to search descriptions"
          >
            {s ? <TimingTower rows={merchantRows} /> : <TowerSkeleton />}
          </Panel>
        </>
      )}
    </div>
  )
}

// Reconciliation status (task 5.4): modeled earn vs actual reward-balance
// delta per statement cycle. A dot, not words, in the dense By-card row —
// hover for the meaning.
const RECON_META: Record<
  string,
  { dot: string; title: string }
> = {
  ok: { dot: 'bg-sector-green', title: 'Reconciles: modeled earn matches the actual balance change within tolerance' },
  mismatch: { dot: 'bg-alert', title: 'Mismatch: model under-earns vs the actual balance — a rules gap, parser gap, or missed devaluation' },
  redemption_suspected: { dot: 'bg-series-amber', title: 'Balance rose less than modeled — points were likely redeemed between snapshots' },
  insufficient_history: { dot: 'bg-ink-faint/40', title: 'Not enough balance snapshots yet to reconcile (needs a second statement)' },
}

function ReconBadge({ status }: { status: string }) {
  const meta = RECON_META[status] ?? RECON_META.insufficient_history
  return <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} title={meta.title} />
}

/** UPI share of one card's debits. A mini-bar plus the number: the bar is what
 *  makes "this is the card I live on" legible at a glance, without reading
 *  digits. Fixed width so the trailing column stays a rigid grid — rows must
 *  not get wider than one another as shares change. */
function UpiPill({ count, of }: { count: number; of: number }) {
  if (of === 0) return <span className="w-12" /> // hold the column
  const share = count / of
  return (
    <span
      className="flex w-12 items-center justify-end gap-1"
      title={`${count} of ${of} debits on this card were UPI-on-credit-card`}
    >
      <span className="h-1 w-4 overflow-hidden rounded-chip bg-carbon-2">
        <span
          className="block h-full bg-series-amber"
          style={{ width: `${Math.round(share * 100)}%` }}
        />
      </span>
      <span className={`figure text-2xs ${share > 0 ? 'text-ink-mute' : 'text-ink-faint'}`}>
        {formatPercent(share)}
      </span>
    </span>
  )
}

/** One split bar for the behaviour strip. Two of these stacked (transactions,
 *  rupees) is the whole point — the eye reads the gap between the two bars
 *  directly, which is the asymmetry a single number can't convey. */
function ChannelSplitBar({
  label,
  upi,
  other,
  fmt,
}: {
  label: string
  upi: number
  other: number
  fmt: (n: number) => string
}) {
  const total = upi + other
  const share = total > 0 ? upi / total : 0
  return (
    <span
      className="flex items-center gap-4 text-xs text-ink-mute"
      title={`${fmt(upi)} of ${fmt(total)} ${label.toLowerCase()} rode UPI`}
    >
      <span className="w-24 shrink-0 text-ink-faint">{label}</span>
      <span className="flex h-2.5 flex-1 overflow-hidden rounded-full bg-carbon-3">
        <span
          className="h-full rounded-full transition-[width] duration-700"
          style={{
            width: `${share * 100}%`,
            background: 'linear-gradient(90deg, var(--color-series-sky), var(--color-sector-green))',
          }}
        />
      </span>
      <span className="figure w-20 shrink-0 text-right text-ink">
        {formatPercent(share)} <span className="text-ink-faint">UPI</span>
      </span>
    </span>
  )
}

function HeroSkeleton() {
  return (
    <div className="flex flex-col gap-2 rounded-panel border border-line bg-carbon-1 px-4 py-3.5">
      <Skeleton shape="line" className="h-3 w-20" />
      <Skeleton shape="stat" className="h-7 w-32" />
    </div>
  )
}

function TowerSkeleton() {
  return (
    <div className="flex flex-col gap-3 py-1">
      <Skeleton shape="line" className="w-full" />
      <Skeleton shape="line" className="w-5/6" />
      <Skeleton shape="line" className="w-2/3" />
      <Skeleton shape="line" className="w-1/2" />
    </div>
  )
}
