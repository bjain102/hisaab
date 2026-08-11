import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmMerchant,
  createCardProfile,
  createMilestone,
  deleteCardProfile,
  deleteMilestone,
  deleteStatement,
  deleteAllStatements,
  deleteTransaction,
  fetchBlastRadius,
  fetchCardProfiles,
  fetchCards,
  fetchCategories,
  fetchDedupCandidates,
  fetchGapReport,
  fetchGuidance,
  fetchMerchants,
  fetchMilestones,
  fetchRatesSummary,
  fetchReconciliation,
  fetchRewardHistory,
  fetchRewardPrograms,
  fetchRewards,
  fetchReviewQueue,
  fetchStatements,
  fetchSummary,
  fetchTransactions,
  mergeMerchants,
  recategorize,
  upsertReward,
  uploadStatement,
  uploadStatementsBulk,
} from './client'
import type { SummaryFilters, TransactionFilters } from './types'

const TRANSACTIONS_PAGE_SIZE = 50

export function useSummary(filters: SummaryFilters) {
  return useQuery({
    queryKey: ['summary', filters],
    queryFn: () => fetchSummary(filters),
  })
}

export function useCards() {
  return useQuery({ queryKey: ['cards'], queryFn: fetchCards })
}

export function useCategories() {
  return useQuery({ queryKey: ['categories'], queryFn: fetchCategories })
}

/** Paged via "Load more" — TanStack's infinite-query accumulates pages for us;
 * offset is derived from how many rows are already loaded (pageParam). */
export function useTransactions(filters: Omit<TransactionFilters, 'limit' | 'offset'>) {
  return useInfiniteQuery({
    queryKey: ['transactions', filters],
    queryFn: ({ pageParam }) =>
      fetchTransactions({ ...filters, limit: TRANSACTIONS_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.rows.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })
}

function invalidateCategorization(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['transactions'] })
  queryClient.invalidateQueries({ queryKey: ['summary'] })
  queryClient.invalidateQueries({ queryKey: ['review-queue'] })
  queryClient.invalidateQueries({ queryKey: ['merchants'] })
}

export function useRecategorize() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: recategorize,
    onSuccess: () => invalidateCategorization(queryClient),
  })
}

// ── Review queue + merchants (task 4.3) ───────────────────────────────────
export function useReviewQueue() {
  return useQuery({ queryKey: ['review-queue'], queryFn: fetchReviewQueue })
}

export function useConfirmMerchant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: confirmMerchant,
    onSuccess: () => invalidateCategorization(queryClient),
  })
}

export function useBlastRadius(merchant: string, enabled: boolean) {
  return useQuery({
    queryKey: ['blast-radius', merchant],
    queryFn: () => fetchBlastRadius(merchant),
    enabled: enabled && !!merchant,
  })
}

export function useMerchants() {
  return useQuery({ queryKey: ['merchants'], queryFn: fetchMerchants })
}

export function useMergeMerchants() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: mergeMerchants,
    onSuccess: () => invalidateCategorization(queryClient),
  })
}

export function useCardProfiles() {
  return useQuery({ queryKey: ['card-profiles'], queryFn: fetchCardProfiles })
}

export function useCreateCardProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createCardProfile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['card-profiles'] }),
  })
}

export function useDeleteCardProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCardProfile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['card-profiles'] }),
  })
}

export function useStatements() {
  return useQuery({ queryKey: ['statements'], queryFn: fetchStatements })
}

export function useDeleteStatement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteStatement,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['statements'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
      queryClient.invalidateQueries({ queryKey: ['dedup-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['rewards'] })
      queryClient.invalidateQueries({ queryKey: ['reward-history'] })
    },
  })
}

export function useDedupCandidates() {
  return useQuery({ queryKey: ['dedup-candidates'], queryFn: fetchDedupCandidates })
}

export function useDeleteTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteTransaction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dedup-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
    },
  })
}

export function useMilestones() {
  return useQuery({ queryKey: ['milestones'], queryFn: fetchMilestones })
}

export function useCreateMilestone() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createMilestone,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['milestones'] }),
  })
}

export function useDeleteMilestone() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteMilestone,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['milestones'] }),
  })
}

export function useRewards() {
  return useQuery({ queryKey: ['rewards'], queryFn: fetchRewards })
}

export function useRewardHistory(cardLabel: string) {
  return useQuery({
    queryKey: ['reward-history', cardLabel],
    queryFn: () => fetchRewardHistory(cardLabel),
    enabled: !!cardLabel,
  })
}

export function useUpsertReward() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: upsertReward,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rewards'] })
      queryClient.invalidateQueries({ queryKey: ['reward-history'] })
    },
  })
}

export function useRewardPrograms(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['reward-programs'],
    queryFn: fetchRewardPrograms,
    enabled: options?.enabled,
  })
}

export function useRatesSummary(
  params: { from_date: string; to_date: string; card?: string },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: ['rates-summary', params],
    queryFn: () => fetchRatesSummary(params),
    enabled: options?.enabled,
  })
}

export function useReconciliation(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['reconciliation'],
    queryFn: fetchReconciliation,
    enabled: options?.enabled,
  })
}

export function useGapReport(options?: { enabled?: boolean }) {
  return useQuery({ queryKey: ['gap-report'], queryFn: fetchGapReport, enabled: options?.enabled })
}

export function useGuidance(options?: { enabled?: boolean }) {
  return useQuery({ queryKey: ['guidance'], queryFn: fetchGuidance, enabled: options?.enabled })
}

/** Every cache an import invalidates. Shared by the single and bulk upload
 *  hooks so a new import surface can't refresh a different subset — and so
 *  the key list only has to be corrected in one place. */
function invalidateAfterImport(queryClient: ReturnType<typeof useQueryClient>) {
  // 'statements', NOT the pre-3.7 'import-batches' — that table (and its query
  // key) was renamed when import_batches was dropped, but this invalidation
  // wasn't updated, so the Import history list silently never refreshed after
  // an upload until the page was reloaded.
  queryClient.invalidateQueries({ queryKey: ['statements'] })
  queryClient.invalidateQueries({ queryKey: ['transactions'] })
  queryClient.invalidateQueries({ queryKey: ['summary'] })
  queryClient.invalidateQueries({ queryKey: ['dedup-candidates'] })
  queryClient.invalidateQueries({ queryKey: ['rewards'] })
  queryClient.invalidateQueries({ queryKey: ['reward-history'] })
}

export function useUploadStatement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: uploadStatement,
    onSuccess: (data) => {
      if (data.success) invalidateAfterImport(queryClient)
    },
  })
}

export function useUploadStatementsBulk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: uploadStatementsBulk,
    // Unconditional: a batch where SOME files imported still changed the DB,
    // and `success` here means "the batch ran", not "every file landed".
    onSuccess: () => invalidateAfterImport(queryClient),
  })
}

export function useDeleteAllStatements() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteAllStatements,
    onSuccess: () => invalidateAfterImport(queryClient),
  })
}
