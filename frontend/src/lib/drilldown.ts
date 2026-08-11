/**
 * Dashboard → Transactions drill-down URLs.
 *
 * Param names are the /api/transactions param names verbatim (card, category,
 * type, from_date, to_date, search). The Transactions page feeds them almost
 * straight through, so a translation layer would only be somewhere for the two
 * vocabularies to drift apart.
 *
 * `from_date`/`to_date` are ALWAYS emitted, even for the all-time range. A
 * drill-down that dropped the dashboard's window would land on a list that
 * cannot reconcile with the row that was clicked, which is the entire point of
 * the interaction.
 *
 * `type=debit` is likewise always emitted: every panel linking here ranks
 * SPEND. So the resulting list totals the panel's GROSS debits, while the
 * By-card and Category panels show figures NET of refunds — the two differ by
 * exactly the refunds the panel subtracted (each category row already carries
 * its own `refunds` figure).
 */
export type DrilldownTarget = {
  from: string
  to: string
  card?: string
  category?: string
  /** Canonical merchant name → a description LIKE search. Approximate — see
   *  the caveat the Top-merchants panel puts on the row itself. */
  merchant?: string
}

export function transactionsUrl(t: DrilldownTarget): string {
  const qs = new URLSearchParams({ from_date: t.from, to_date: t.to, type: 'debit' })
  if (t.card) qs.set('card', t.card)
  if (t.category) qs.set('category', t.category)
  if (t.merchant) qs.set('search', t.merchant)
  return `/transactions?${qs}`
}
