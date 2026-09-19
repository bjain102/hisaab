import { useState } from 'react'
import PageHeader from '../shell/PageHeader'
import Panel from '../components/Panel'
import EmptyState from '../components/EmptyState'
import MilestoneModal from '../components/MilestoneModal'
import RewardBalanceModal from '../components/RewardBalanceModal'
import RewardSparkline from '../components/RewardSparkline'
import {
  useDeleteMilestone,
  useGapReport,
  useGuidance,
  useMilestones,
  useRatesSummary,
  useReconciliation,
  useRewardHistory,
  useRewardPrograms,
  useRewards,
} from '../api/hooks'
import type { GapRow, ReconciliationRow, ReconStatus, Reward, RewardValueType } from '../api/types'
import { formatINR, formatMonthLabel, formatPercent, formatRate } from '../lib/format'
import { REWARDS_INTELLIGENCE_ENABLED } from '../lib/features'

const RECON_LABEL: Record<ReconStatus, { text: string; cls: string }> = {
  ok: { text: 'reconciles', cls: 'border-sector-green/30 text-sector-green' },
  mismatch: { text: 'mismatch', cls: 'border-alert/40 text-alert' },
  redemption_suspected: { text: 'redemption suspected', cls: 'border-series-amber/40 text-series-amber' },
  insufficient_history: { text: 'not yet reconciled', cls: 'border-line text-ink-faint' },
}

function rewardValueDisplay(r: Reward): string {
  if (r.value_type === 'cashback_inr' || r.value_type === 'balance_inr') return formatINR(r.value)
  return `${r.value.toLocaleString('en-IN')} pts`
}

function RewardCard({ reward: r, onEdit }: { reward: Reward; onEdit: () => void }) {
  const { data: history } = useRewardHistory(r.card_label)

  return (
    <div className="rounded-[14px] border border-line bg-carbon-2 px-4.5 py-4 transition-transform duration-200 hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink">{r.card_label}</div>
          <div className="text-xs text-ink-mute">{r.label}</div>
        </div>
        <div className="figure text-lg text-series-amber">{rewardValueDisplay(r)}</div>
      </div>
      {history && history.length > 1 && (
        <div className="mt-2">
          <RewardSparkline history={history} />
        </div>
      )}
      <div className="mt-2 flex items-center gap-2 text-2xs text-ink-faint">
        <span
          className={`rounded-full border px-2 py-0.5 uppercase ${
            r.source === 'manual'
              ? 'border-sector-yellow/30 text-sector-yellow'
              : 'border-line text-ink-faint'
          }`}
        >
          {r.source === 'manual' ? 'manual' : 'from statement'}
        </span>
        <span>as of {r.as_of}</span>
        <button onClick={onEdit} className="ml-auto text-brand-bright underline">
          edit
        </button>
      </div>
    </div>
  )
}

/** The spec's target sentence: "₹18,400 on Food & Drinks went on HDFC Tata
 * Neu (1.5% effective); HDFC Swiggy had ₹410 of headroom at 5% — you lost
 * ₹340." Every number is traceable: spend/actual from the category's real
 * transactions and accruals, best-card from the cap-aware counterfactual. */
function GapSentence({ row: r }: { row: GapRow }) {
  const actualCard = r.actual_cards[0]?.card_label ?? '—'
  const others = r.actual_cards.length - 1
  return (
    <div className="rounded-panel border border-line bg-carbon-2 px-3 py-2 text-sm text-ink-mute">
      <span className="figure text-ink">{formatINR(r.spend)}</span> on{' '}
      <span className="text-ink">{r.category}</span> went on {actualCard}
      {others > 0 && ` (+${others} more)`}
      {r.actual_rate !== null && ` (${formatRate(r.actual_rate)} effective)`}
      {'; '}
      <span className="text-ink">{r.best_card}</span>
      {r.best_rate !== null && ` at ${formatRate(r.best_rate)}`}
      {r.best_headroom !== null && ` with ${formatINR(r.best_headroom)} headroom`}
      {' — you lost '}
      <span className="figure text-alert">{formatINR(r.loss)}</span>
    </div>
  )
}

/** Stands in for the gap report, effective rates, reconciliation, and card
 * rules panels while REWARDS_INTELLIGENCE_ENABLED is off. Nothing was
 * deleted — engine.py, reports.py, gaps.py, and their endpoints are intact
 * and re-enable by flipping the one flag in lib/features.ts. */
function ArchivedIntelligenceNotice() {
  return (
    <div className="flex flex-col gap-1.5 rounded-panel border border-dashed border-line bg-carbon-1/50 px-4 py-3.5">
      <span className="eyebrow">Rewards intelligence — archived</span>
      <p className="text-sm text-ink-mute">
        Gap report, effective rates, reconciliation, and card rules are paused pending a rework —
        not deleted. Reward balances and milestones below are unaffected.
      </p>
    </div>
  )
}

export default function Rewards() {
  const [milestoneModalOpen, setMilestoneModalOpen] = useState(false)
  const [rewardModal, setRewardModal] = useState<{
    cardLabel: string
    label: string
    value: string
    valueType: RewardValueType
  } | null>(null)
  const [rewardModalOpen, setRewardModalOpen] = useState(false)

  const { data: rewards } = useRewards()
  const { data: milestones } = useMilestones()
  const { data: rewardPrograms } = useRewardPrograms({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const { data: rates } = useRatesSummary(
    { from_date: '2000-01-01', to_date: '2099-12-31' },
    { enabled: REWARDS_INTELLIGENCE_ENABLED },
  )
  const { data: reconciliation } = useReconciliation({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const { data: gapReport } = useGapReport({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const { data: guidance } = useGuidance({ enabled: REWARDS_INTELLIGENCE_ENABLED })
  const deleteMilestone = useDeleteMilestone()

  // Latest complete month headlines the report; the running month is still
  // moving and is labelled as such.
  const currentMonth = new Date().toISOString().slice(0, 7)
  const completeMonths = gapReport?.months.filter((m) => m.month < currentMonth) ?? []
  const gapMonth = completeMonths.length > 0 ? completeMonths[completeMonths.length - 1] : null
  const maxLoss = Math.max(...completeMonths.map((m) => m.total_loss), 1)

  // Latest reconciliation cycle per card (rows arrive chronological per card).
  const latestRecon = new Map<string, ReconciliationRow>()
  reconciliation?.forEach((row) => latestRecon.set(row.card_label, row))

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Cards"
        title="Rewards"
        sub="Reward balances and spend-target milestones."
      />

      {REWARDS_INTELLIGENCE_ENABLED ? (
        <Panel
          title="Gap report — left on table"
          meta={
            gapReport && (
              <span className="text-2xs text-ink-faint">
                computed on {formatPercent(gapReport.trust)} confirmed spend · cap-aware counterfactual
              </span>
            )
          }
        >
          {!gapMonth ? (
            <EmptyState title="Needs a complete month of confirmed spend with seeded card rules." />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex items-baseline gap-3">
                <span className="figure text-2xl text-alert">{formatINR(gapMonth.total_loss)}</span>
                <span className="text-sm text-ink-mute">
                  lost in {formatMonthLabel(gapMonth.month)} by using the wrong card
                </span>
              </div>

              {/* Top-3 gaps, each the spec's target sentence */}
              <div className="flex flex-col gap-2">
                {gapMonth.rows.filter((r) => r.loss > 0).slice(0, 3).map((r) => (
                  <GapSentence key={r.category} row={r} />
                ))}
                {gapMonth.rows.every((r) => r.loss === 0) && (
                  <p className="text-sm text-sector-green">
                    Every category was already on its best card this month.
                  </p>
                )}
              </div>

              {/* 6-month loss trend */}
              <div>
                <div className="mb-1 text-2xs uppercase text-ink-faint">Monthly loss trend</div>
                <div className="flex items-end gap-2">
                  {completeMonths.map((m) => (
                    <div key={m.month} className="flex flex-col items-center gap-1">
                      <span className="figure text-2xs text-ink-mute">{formatINR(m.total_loss)}</span>
                      <div
                        className="w-10 rounded-t bg-alert/60"
                        style={{ height: `${Math.max(4, (m.total_loss / maxLoss) * 48)}px` }}
                      />
                      <span className="text-2xs text-ink-faint">{formatMonthLabel(m.month)}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Forward guidance */}
              {guidance && guidance.length > 0 && (
                <div>
                  <div className="mb-1 text-2xs uppercase text-ink-faint">This cycle — use</div>
                  <div className="flex flex-wrap gap-2">
                    {guidance.map((g) => (
                      <span
                        key={g.category}
                        className="rounded-chip border border-line bg-carbon-2 px-2 py-1 text-xs text-ink-mute"
                      >
                        {g.category} → <span className="text-ink">{g.card_label}</span>
                        {g.trailing_rate !== null && (
                          <span className="text-series-amber"> {formatRate(g.trailing_rate)}</span>
                        )}
                        {g.headroom !== null && (
                          <span className="text-ink-faint"> · {formatINR(g.headroom)} headroom left</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* v1 caveats, on the report itself (spec M10) */}
              {gapReport && (
                <ul className="flex list-disc flex-col gap-0.5 pl-4 text-2xs text-ink-faint">
                  {gapReport.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Panel>
      ) : (
        <ArchivedIntelligenceNotice />
      )}

      <Panel
        title="Rewards & points balance"
        meta={
          <button
            onClick={() => {
              setRewardModal(null)
              setRewardModalOpen(true)
            }}
            className="btn-primary !px-3 !py-1 !text-2xs"
          >
            <span>+ Add / edit</span>
          </button>
        }
      >
        {!rewards || rewards.length === 0 ? (
          <p className="text-sm text-ink-faint">
            No rewards data yet. Import a PDF statement to populate, or add manually.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {rewards.map((r) => (
              <RewardCard
                key={r.id}
                reward={r}
                onEdit={() => {
                  setRewardModal({
                    cardLabel: r.card_label,
                    label: r.label,
                    value: String(r.value),
                    valueType: r.value_type,
                  })
                  setRewardModalOpen(true)
                }}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Milestones"
        meta={
          <button onClick={() => setMilestoneModalOpen(true)} className="btn-primary !px-3 !py-1 !text-2xs">
            <span>+ Add milestone</span>
          </button>
        }
      >
        {!milestones || milestones.length === 0 ? (
          <EmptyState title="No milestones yet. Add one to track fee waivers or reward targets." />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {milestones.map((m) => {
              const pct = Math.min(100, (m.progress / m.target_spend) * 100)
              const complete = pct >= 100
              const openEnded = m.window_end === '9999-12-31'
              return (
                <div
                  key={m.id}
                  className="rounded-[14px] border border-line bg-carbon-2 px-4.5 py-4 transition-transform duration-200 hover:-translate-y-0.5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm text-ink">{m.name}</div>
                      <div className="text-2xs text-ink-faint uppercase">{m.card_label}</div>
                    </div>
                    <button
                      onClick={() => deleteMilestone.mutate(m.id)}
                      aria-label={`Delete ${m.name}`}
                      className="text-ink-faint transition-colors duration-150 hover:text-alert"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-chip bg-carbon-3">
                    <div
                      className={`h-full transition-[width] duration-500 ${complete ? 'bg-sector-green' : 'bg-series-amber'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="figure mt-1.5 flex justify-between text-xs text-ink-mute">
                    <span>{formatINR(m.progress)}</span>
                    <span>{formatINR(m.target_spend)}</span>
                  </div>
                  <div className="mt-1.5 text-2xs text-ink-faint">
                    {m.window_start} → {openEnded ? 'ongoing' : m.window_end}
                  </div>
                  {m.benefit && (
                    <div className="mt-2 text-xs text-ink-mute">
                      {complete ? '✓ Unlocked: ' : 'Reward: '}
                      {m.benefit}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Panel>

      {REWARDS_INTELLIGENCE_ENABLED && (
        <>
          <Panel
            title="Effective rates & reconciliation"
            meta={<span className="text-2xs text-ink-faint">net of fees & bonuses · modeled vs actual balance</span>}
          >
            {!rates || rates.by_card.length === 0 ? (
              <EmptyState title="No seeded card rules yet — effective rates appear once rules are seeded." />
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {rates.by_card.map((c) => {
                  const recon = latestRecon.get(c.card_label)
                  const status: ReconStatus = recon?.status ?? 'insufficient_history'
                  const meta = RECON_LABEL[status]
                  return (
                    <div key={c.card_label} className="rounded-panel border border-line bg-carbon-2 px-4 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-sm text-ink">{c.card_label}</div>
                        <div className="figure text-lg text-series-amber">
                          {c.rate !== null ? formatRate(c.rate) : '—'}
                        </div>
                      </div>
                      <div className="mt-1 text-2xs text-ink-faint">
                        {formatINR(c.net_value)} earned on {formatINR(c.spend)} spend
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-2xs">
                        <span className={`rounded-chip border px-1.5 py-0.5 uppercase ${meta.cls}`}>
                          {meta.text}
                        </span>
                        {recon && recon.modeled_units !== null && (
                          <span className="text-ink-faint">
                            modeled {recon.modeled_units} vs actual {recon.actual_delta_units} units
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Panel>

          <Panel title="Card rules" meta={<span className="text-2xs text-ink-faint">read-only — edit via ccyamls/*.yaml</span>}>
            {!rewardPrograms || rewardPrograms.length === 0 ? (
              <EmptyState title="No card rules seeded yet. Run `python -m rewards.seed` after adding a ccyamls/*.yaml file." />
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {rewardPrograms.map((p) => (
                  <div key={p.id} className="rounded-panel border border-line bg-carbon-2 px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm text-ink">{p.card_label}</div>
                        <div className="text-xs text-ink-mute">{p.name}</div>
                      </div>
                      {p.valid_to && (
                        <span className="rounded-chip border border-line px-1.5 py-0.5 text-2xs uppercase text-ink-faint">
                          closed
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-2xs text-ink-faint">
                      {p.valid_from} → {p.valid_to ?? 'present'}
                    </div>
                    <div className="mt-1.5 text-xs text-ink-mute">
                      Annual fee: {formatINR(p.annual_fee)}
                    </div>
                    <div className="mt-1.5 text-xs text-ink-mute">
                      {p.earn_rule_count} earn rule{p.earn_rule_count === 1 ? '' : 's'}
                      {p.bonus_rule_count > 0 && `, ${p.bonus_rule_count} bonus rule${p.bonus_rule_count === 1 ? '' : 's'}`}
                    </div>
                    {p.default_route_name && (
                      <div className="mt-1.5 text-2xs text-ink-faint">
                        Default route: {p.default_route_name}
                        {p.default_route_value_per_point != null &&
                          ` (₹${p.default_route_value_per_point.toFixed(2)}/pt)`}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </>
      )}

      <MilestoneModal open={milestoneModalOpen} onClose={() => setMilestoneModalOpen(false)} />
      <RewardBalanceModal
        open={rewardModalOpen}
        initial={rewardModal}
        onClose={() => setRewardModalOpen(false)}
      />
    </div>
  )
}
