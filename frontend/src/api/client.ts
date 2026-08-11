import type {
  BlastRadius,
  BulkUploadResult,
  CardProfile,
  DedupCandidates,
  DeleteAllResult,
  GapReport,
  GuidanceRow,
  Merchant,
  Milestone,
  RatesSummary,
  ReconciliationRow,
  Reward,
  RewardHistoryPoint,
  RewardProgram,
  RewardValueType,
  ReviewQueueGroup,
  Statement,
  Summary,
  SummaryFilters,
  Transaction,
  TransactionFilters,
  TransactionPage,
  UploadResult,
} from './types'

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const url = qs.size > 0 ? `${path}?${qs}` : path
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`)
  return resp.json() as Promise<T>
}

// ── Paise boundary (migration v2, ADR-005) ────────────────────────────────
// The wire carries money as integer paise; the entire frontend works in
// rupees. These helpers are the ONLY place the conversion happens.

const toRupees = (paise: number): number => paise / 100

type SummaryWire = Omit<Summary, 'by_category' | 'by_card' | 'monthly_trend' | 'monthly_by_category' | 'top_merchants'> & {
  by_category: Summary['by_category']
  by_card: Summary['by_card']
  monthly_trend: Summary['monthly_trend']
  monthly_by_category: Summary['monthly_by_category']
  top_merchants: Summary['top_merchants']
}

function mapSummary(wire: SummaryWire): Summary {
  return {
    ...wire,
    total_spend: toRupees(wire.total_spend),
    category_sum: toRupees(wire.category_sum),
    gross_debits: toRupees(wire.gross_debits),
    refund_credits: toRupees(wire.refund_credits),
    cashback_total: toRupees(wire.cashback_total),
    trust: wire.trust, // already a 0-1 fraction, not money
    trusted_spend: toRupees(wire.trusted_spend),
    by_category: wire.by_category.map((r) => ({
      ...r,
      total: toRupees(r.total),
      gross_debits: toRupees(r.gross_debits),
      refunds: toRupees(r.refunds),
    })),
    // count/upi_count are counts, NOT money — they must not pass through toRupees.
    by_card: wire.by_card.map((r) => ({
      ...r,
      total: toRupees(r.total),
      gross_debits: toRupees(r.gross_debits),
      upi_total: toRupees(r.upi_total),
    })),
    by_channel: {
      upi: { count: wire.by_channel.upi.count, total: toRupees(wire.by_channel.upi.total) },
      card: { count: wire.by_channel.card.count, total: toRupees(wire.by_channel.card.total) },
    },
    monthly_trend: wire.monthly_trend.map((r) => ({ ...r, total: toRupees(r.total) })),
    monthly_by_category: wire.monthly_by_category.map((r) => ({ ...r, total: toRupees(r.total) })),
    top_merchants: wire.top_merchants.map((r) => ({ ...r, total: toRupees(r.total) })),
  }
}

export async function fetchSummary(filters: SummaryFilters): Promise<Summary> {
  const wire = await get<SummaryWire>('/api/summary', filters)
  return mapSummary(wire)
}

export function fetchCards(): Promise<string[]> {
  return get<string[]>('/api/cards')
}

export function fetchCategories(): Promise<string[]> {
  return get<string[]>('/api/categories')
}

type TransactionWire = Omit<Transaction, 'amount'> & { amount_paise: number }

export async function fetchTransactions(filters: TransactionFilters): Promise<TransactionPage> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const url = qs.size > 0 ? `/api/transactions?${qs}` : '/api/transactions'
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`/api/transactions failed: ${resp.status}`)
  const wireRows = (await resp.json()) as TransactionWire[]
  const rows: Transaction[] = wireRows.map(({ amount_paise, ...rest }) => ({
    ...rest,
    amount: toRupees(amount_paise),
  }))
  const total = Number(resp.headers.get('X-Total-Count') ?? rows.length)
  return { rows, total }
}

export function recategorize(payload: {
  id: number
  category: string
  learn: boolean
  merchant: string
}): Promise<{ success: boolean }> {
  return fetch('/api/recategorize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
}

// ── Review queue + merchants (task 4.3) ───────────────────────────────────
export async function fetchReviewQueue(): Promise<ReviewQueueGroup[]> {
  const wire = await get<ReviewQueueGroup[]>('/api/review_queue')
  return wire.map((g) => ({ ...g, total: toRupees(g.total) }))
}

export function confirmMerchant(payload: {
  merchant: string
  category: string
}): Promise<{ success: boolean; merchant_id: number; restamped: number }> {
  return fetch('/api/review_queue/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
}

export async function fetchBlastRadius(merchant: string): Promise<BlastRadius> {
  const wire = await get<BlastRadius>('/api/blast_radius', { merchant })
  return { ...wire, total: toRupees(wire.total) }
}

export function fetchMerchants(): Promise<Merchant[]> {
  return get<Merchant[]>('/api/merchants')
}

export function mergeMerchants(payload: {
  from_id: number
  into_id: number
}): Promise<{ success: boolean }> {
  return fetch('/api/merchants/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
}

export function fetchCardProfiles(): Promise<CardProfile[]> {
  return get<CardProfile[]>('/api/card_profiles')
}

export async function createCardProfile(payload: {
  bank: string
  variant: string
  last4: string
}): Promise<{ success?: boolean; label?: string; error?: string }> {
  const resp = await fetch('/api/card_profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return resp.json()
}

export async function deleteCardProfile(id: number): Promise<{ success: boolean }> {
  const resp = await fetch(`/api/card_profiles/${id}`, { method: 'DELETE' })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.error || 'Delete failed')
  return data
}

export function fetchStatements(): Promise<Statement[]> {
  return get<Statement[]>('/api/statements')
}

export function deleteStatement(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/statements/${id}`, { method: 'DELETE' }).then((r) => r.json())
}

/** Wipe every import. The confirm token is required by the server — it's sent
 *  here rather than being implied by the call so the destructive intent is
 *  visible at the call site, not buried in a URL. */
export function deleteAllStatements(): Promise<DeleteAllResult> {
  return fetch('/api/statements/all', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: 'DELETE ALL' }),
  }).then((r) => r.json())
}

type DuplicateTransactionWire = Omit<DedupCandidates['duplicate_groups'][number]['transactions'][number], 'amount'> & {
  amount_paise: number
}

export async function fetchDedupCandidates(): Promise<DedupCandidates> {
  const wire = await get<Omit<DedupCandidates, 'duplicate_groups'> & {
    duplicate_groups: { count: number; transactions: DuplicateTransactionWire[] }[]
  }>('/api/dedup_candidates')
  return {
    overlapping_statements: wire.overlapping_statements,
    duplicate_groups: wire.duplicate_groups.map((g) => ({
      count: g.count,
      transactions: g.transactions.map(({ amount_paise, ...rest }) => ({ ...rest, amount: toRupees(amount_paise) })),
    })),
  }
}

export function deleteTransaction(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/transactions/${id}`, { method: 'DELETE' }).then((r) => r.json())
}

export async function uploadStatement(payload: {
  file: File
  card: string
  cardLabel: string
  password?: string
  force?: boolean
}): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', payload.file)
  formData.append('card', payload.card)
  formData.append('card_label', payload.cardLabel)
  if (payload.password) formData.append('password', payload.password)
  if (payload.force) formData.append('force', 'true')
  const resp = await fetch('/api/upload', { method: 'POST', body: formData })
  return resp.json()
}

/** Import many statements for ONE card. Per-card because `card` picks the
 *  parser and `password` unlocks the PDFs — both are issuer properties, not
 *  file properties. Per-file outcomes come back in `results`. */
export async function uploadStatementsBulk(payload: {
  files: File[]
  card: string
  cardLabel: string
  password?: string
  force?: boolean
}): Promise<BulkUploadResult> {
  const formData = new FormData()
  for (const f of payload.files) formData.append('files', f)
  formData.append('card', payload.card)
  formData.append('card_label', payload.cardLabel)
  if (payload.password) formData.append('password', payload.password)
  if (payload.force) formData.append('force', 'true')
  const resp = await fetch('/api/upload_bulk', { method: 'POST', body: formData })
  return resp.json()
}

type MilestoneWire = {
  id: number
  card_label: string
  name: string
  target_paise: number
  window_start: string
  window_end: string
  benefit: string | null
  progress_paise: number
}

export async function fetchMilestones(): Promise<Milestone[]> {
  const wire = await get<MilestoneWire[]>('/api/milestones')
  return wire.map((m) => ({
    id: m.id, card_label: m.card_label, name: m.name, benefit: m.benefit,
    window_start: m.window_start, window_end: m.window_end,
    target_spend: toRupees(m.target_paise), progress: toRupees(m.progress_paise),
  }))
}

export function createMilestone(payload: {
  card_label: string
  name: string
  target_spend: number
  window_start: string
  window_end: string
  benefit?: string
}): Promise<{ success: boolean }> {
  return fetch('/api/milestones', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
}

export function deleteMilestone(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/milestones/${id}`, { method: 'DELETE' }).then((r) => r.json())
}

// value_type on the wire stays 'points'/'cashback_inr'/'balance_inr' (the API
// already translates its internal '..._paise' names back to this domain
// vocabulary) — only the numeric value needs the paise->rupee conversion,
// and only for the two INR-denominated types.
function toRewardValue(value: number, valueType: RewardValueType): number {
  return valueType === 'points' ? value : toRupees(value)
}

export async function fetchRewards(): Promise<Reward[]> {
  const wire = await get<Reward[]>('/api/rewards')
  return wire.map((r) => ({ ...r, value: toRewardValue(r.value, r.value_type) }))
}

export async function fetchRewardHistory(cardLabel: string): Promise<RewardHistoryPoint[]> {
  const wire = await get<RewardHistoryPoint[]>('/api/rewards/history', { card_label: cardLabel })
  return wire.map((p) => ({ ...p, value: toRewardValue(p.value, p.value_type) }))
}

export function upsertReward(payload: {
  card_label: string
  label: string
  value: number
  value_type: RewardValueType
}): Promise<{ success: boolean }> {
  return fetch('/api/rewards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
}

// ── Reward programs (task 5.2) — read-only view of what rewards/seed.py has
// seeded from ccyamls/*.yaml. See rewards/seed.py's docstring for why editing
// happens via YAML + re-seeding, not through this app.
type RewardProgramWire = {
  id: number
  card_label: string
  name: string
  earn_currency: 'points' | 'cashback_inr'
  annual_fee_paise: number
  valid_from: string
  valid_to: string | null
  earn_rule_count: number
  bonus_rule_count: number
  default_route_name: string | null
  default_route_centipaise: number | null
}

export async function fetchRewardPrograms(): Promise<RewardProgram[]> {
  const wire = await get<RewardProgramWire[]>('/api/reward_programs')
  return wire.map(({ annual_fee_paise, default_route_centipaise, ...rest }) => ({
    ...rest,
    annual_fee: toRupees(annual_fee_paise),
    default_route_value_per_point: default_route_centipaise === null ? null : default_route_centipaise / 10000,
  }))
}

// ── Effective rates + reconciliation (task 5.4) ───────────────────────────
type RatesSummaryWire = {
  from_date: string
  to_date: string
  blended_rate: number | null
  net_value_paise: number
  spend_paise: number
  by_card: {
    card_label: string
    spend_paise: number
    net_value_paise: number
    rate: number | null
    recon_status: RatesSummary['by_card'][number]['recon_status']
  }[]
}

export async function fetchRatesSummary(params: {
  from_date: string
  to_date: string
  card?: string
}): Promise<RatesSummary> {
  const wire = await get<RatesSummaryWire>('/api/rewards/rates_summary', params)
  return {
    from_date: wire.from_date,
    to_date: wire.to_date,
    blended_rate: wire.blended_rate,
    net_value: toRupees(wire.net_value_paise),
    spend: toRupees(wire.spend_paise),
    by_card: wire.by_card.map((c) => ({
      card_label: c.card_label,
      spend: toRupees(c.spend_paise),
      net_value: toRupees(c.net_value_paise),
      rate: c.rate,
      recon_status: c.recon_status,
    })),
  }
}

export function fetchReconciliation(): Promise<ReconciliationRow[]> {
  // units stay unconverted (compared against reward_balances value_minor)
  return get<ReconciliationRow[]>('/api/rewards/reconciliation')
}

// ── Gap report + forward guidance (task 5.5) ──────────────────────────────
type GapRowWire = {
  month: string
  category: string
  spend_paise: number
  txn_count: number
  actual_value_paise: number
  actual_rate: number | null
  actual_cards: { card_label: string; spend_paise: number }[]
  best_card: string
  best_value_paise: number
  best_rate: number | null
  best_headroom_value_paise: number | null
  loss_paise: number
}

type GapReportWire = {
  months: { month: string; total_loss_paise: number; rows: GapRowWire[] }[]
  trust: number
  caveats: string[]
}

export async function fetchGapReport(): Promise<GapReport> {
  const wire = await get<GapReportWire>('/api/rewards/gaps')
  return {
    trust: wire.trust,
    caveats: wire.caveats,
    months: wire.months.map((m) => ({
      month: m.month,
      total_loss: toRupees(m.total_loss_paise),
      rows: m.rows.map((r) => ({
        month: r.month,
        category: r.category,
        spend: toRupees(r.spend_paise),
        txn_count: r.txn_count,
        actual_value: toRupees(r.actual_value_paise),
        actual_rate: r.actual_rate,
        actual_cards: r.actual_cards.map((c) => ({ card_label: c.card_label, spend: toRupees(c.spend_paise) })),
        best_card: r.best_card,
        best_value: toRupees(r.best_value_paise),
        best_rate: r.best_rate,
        best_headroom: r.best_headroom_value_paise === null ? null : toRupees(r.best_headroom_value_paise),
        loss: toRupees(r.loss_paise),
      })),
    })),
  }
}

type GuidanceWire = {
  category: string
  card_label: string
  trailing_spend_paise: number
  trailing_rate: number | null
  headroom_value_paise: number | null
}

export async function fetchGuidance(): Promise<GuidanceRow[]> {
  const wire = await get<GuidanceWire[]>('/api/rewards/guidance')
  return wire.map((g) => ({
    category: g.category,
    card_label: g.card_label,
    trailing_spend: toRupees(g.trailing_spend_paise),
    trailing_rate: g.trailing_rate,
    headroom: g.headroom_value_paise === null ? null : toRupees(g.headroom_value_paise),
  }))
}
