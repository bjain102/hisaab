// Rewards "intelligence" (effective rates, reconciliation, gap report,
// forward guidance — Phase 5, M10) is archived: paused pending a rework,
// not deleted. Flip this back on to restore it. Static reward balances and
// milestones (read straight from statements) are unaffected — they never
// depended on this flag.
export const REWARDS_INTELLIGENCE_ENABLED = false
