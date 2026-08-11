// DOMAIN shapes (rupees). Since migration v2 the API wire carries money as
// INTEGER PAISE; client.ts converts paise -> rupees ONCE at the fetch
// boundary, so every component and formatter stays in rupee-domain and the
// types below describe the post-conversion shape.
//
// Not yet converted on the wire (later migrations own them):
//   - milestones.target_spend / current_spend  (rupees until v5)
//   - upload result totals/tad                 (parser rupee floats, unchanged)
//
// rewards.value: wire carries paise for 'cashback_inr'/'balance_inr' (points
// stay a raw integer) since migration v4 — client.ts converts once here,
// same boundary pattern as v2's money fields.

export type CategoryRow = {
  category: string
  total: number
  gross_debits: number
  refunds: number
  count: number
}

/** Which rail a spend rode: UPI-on-credit-card vs a normal card auth. */
export type PaymentChannel = 'upi' | 'card'

/** Debit-only — a refund rode no rail. `total` is rupees post-boundary. */
export type ChannelAggregate = { count: number; total: number }

export type CardRow = {
  card_label: string
  /** NET of refunds. */
  total: number
  /** Debit count. */
  count: number
  /** Debit-only gross — the honest denominator for an average ticket, since
   *  `total` nets out refunds that were never part of any single charge. */
  gross_debits: number
  upi_count: number
  upi_total: number
}

export type MonthPoint = {
  month: string // 'YYYY-MM'
  total: number
}

export type MonthCategoryPoint = {
  month: string
  category: string
  total: number // signed: refund-heavy categories can net negative
}

export type MerchantRow = {
  name: string
  total: number
  count: number
  confirmed: boolean
}

export type ReviewQueueGroup = {
  merchant: string
  sample: string
  count: number
  total: number
  suggested_category: string
}

export type BlastRadius = {
  count: number
  total: number
  categories: string[]
}

export type Merchant = {
  id: number
  canonical_name: string
  category: string
  status: 'confirmed' | 'suggested'
  alias_count: number
  txn_count: number
}

export type Summary = {
  total_spend: number
  category_sum: number
  gross_debits: number
  refund_credits: number
  cashback_total: number
  cashback_count: number
  trust: number
  trusted_spend: number
  by_category: CategoryRow[]
  by_card: CardRow[]
  /** Both keys are always present and zero-filled, so callers need no guard. */
  by_channel: Record<PaymentChannel, ChannelAggregate>
  monthly_trend: MonthPoint[]
  monthly_by_category: MonthCategoryPoint[]
  top_merchants: MerchantRow[]
}

export type SummaryFilters = {
  from_date: string
  to_date: string
  card?: string
}

export type Transaction = {
  id: number
  date: string
  description: string
  amount: number
  type: 'debit' | 'credit'
  category: string
  bank_category: string | null
  card_label: string
  is_cashback: number
  created_at: string
}

export type TransactionFilters = {
  search?: string
  card?: string
  category?: string
  type?: string
  sort?: string
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
}

export type TransactionPage = {
  rows: Transaction[]
  total: number
}

export type CardProfile = {
  id: number
  bank: string
  variant: string
  last4: string
  label: string
  created_at: string
}

export type Statement = {
  id: number
  card_label: string
  filename: string | null
  format: 'pdf' | 'csv'
  period_start: string
  period_end: string
  txn_count: number
  imported_at: string
}

export type OverlappingStatementPair = {
  card_label: string
  id1: number
  start1: string
  end1: string
  n1: number
  id2: number
  start2: string
  end2: string
  n2: number
}

export type DuplicateTransaction = {
  id: number
  date: string
  description: string
  amount: number
  type: 'debit' | 'credit'
  category: string
  card_label: string
  statement_id: number | null
}

export type DuplicateGroup = {
  count: number
  transactions: DuplicateTransaction[]
}

export type DedupCandidates = {
  overlapping_statements: OverlappingStatementPair[]
  duplicate_groups: DuplicateGroup[]
}

export type StatementTotals = {
  debits: number | null
  credits: number | null
  tad: number | null
}

export type StatementPeriod = {
  start: string
  end: string
}

export type UploadResult = {
  success: boolean
  imported: number
  card: string
  skipped_candidates: number | null
  period: StatementPeriod | null
  totals: StatementTotals | null
  reconciled: boolean | null
  error?: string
  overlap?: boolean
}

/** One file's outcome inside a bulk import. `ok` is per-FILE; the batch itself
 *  succeeds as long as it ran, so a mixed result is normal, not an error. */
export type BulkUploadFileResult = {
  filename: string
  ok: boolean
  imported?: number
  period?: StatementPeriod | null
  reconciled?: boolean | null
  error?: string
  overlap?: boolean
}

export type BulkUploadResult = {
  success: boolean
  card: string
  files: number
  succeeded: number
  failed: number
  imported: number
  results: BulkUploadFileResult[]
  error?: string
}

export type DeleteAllResult = {
  success: boolean
  statements_deleted: number
  transactions_deleted: number
  /** Filename of the pre-delete snapshot, or null when there was nothing to back up. */
  backup: string | null
  error?: string
}

export type Milestone = {
  id: number
  card_label: string
  name: string
  target_spend: number
  progress: number
  window_start: string
  window_end: string
  benefit: string | null
}

export type RewardValueType = 'points' | 'cashback_inr' | 'balance_inr'

export type Reward = {
  id: number
  card_label: string
  label: string
  value: number
  value_type: RewardValueType
  source: 'statement' | 'manual'
  as_of: string
}

export type RewardHistoryPoint = {
  as_of: string
  label: string
  value: number
  value_type: RewardValueType
  source: 'statement' | 'manual'
}

// Effective rates + reconciliation (task 5.4, M10 Job 2). All rupee fields
// converted from paise at the client boundary; `rate` is a fraction (0.08 =
// 8%). Reconciliation units are raw points/paise-of-cashback, unconverted
// (they're compared against reward_balances, which stores value_minor).
export type ReconStatus =
  | 'ok'
  | 'mismatch'
  | 'redemption_suspected'
  | 'insufficient_history'

export type CardRateSummary = {
  card_label: string
  spend: number // rupees
  net_value: number // rupees
  rate: number | null // fraction; null when spend is 0
  recon_status: ReconStatus
}

export type RatesSummary = {
  from_date: string
  to_date: string
  blended_rate: number | null
  net_value: number // rupees
  spend: number // rupees
  by_card: CardRateSummary[]
}

export type ReconciliationRow = {
  card_label: string
  status: ReconStatus
  snapshots: number
  window_start: string | null
  window_end: string | null
  modeled_units: number | null
  actual_delta_units: number | null
  tolerance_units: number | null
}

// Gap report + forward guidance (task 5.5, M10 Job 3). Rupees at the client
// boundary; rates are fractions. `best_headroom` / `headroom` null = the
// winning rule is uncapped.
export type GapRow = {
  month: string
  category: string
  spend: number
  txn_count: number
  actual_value: number
  actual_rate: number | null
  actual_cards: { card_label: string; spend: number }[]
  best_card: string
  best_value: number
  best_rate: number | null
  best_headroom: number | null
  loss: number
}

export type GapMonth = {
  month: string
  total_loss: number
  rows: GapRow[]
}

export type GapReport = {
  months: GapMonth[]
  trust: number
  caveats: string[]
}

export type GuidanceRow = {
  category: string
  card_label: string
  trailing_spend: number
  trailing_rate: number | null
  headroom: number | null
}

// Read-only view of what rewards/seed.py has seeded from ccyamls/*.yaml
// (task 5.2). Rules themselves are edited via the YAML files + re-seeding,
// not through this app — see rewards/seed.py's docstring for why.
export type RewardProgram = {
  id: number
  card_label: string
  name: string
  earn_currency: 'points' | 'cashback_inr'
  annual_fee: number // rupees, converted from annual_fee_paise
  valid_from: string
  valid_to: string | null
  earn_rule_count: number
  bonus_rule_count: number
  default_route_name: string | null
  default_route_value_per_point: number | null // rupees, converted from centipaise
}
