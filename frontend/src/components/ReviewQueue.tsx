import { useState } from 'react'
import Select from './Select'
import EmptyState from './EmptyState'
import Skeleton from './Skeleton'
import { toast } from './Toast'
import { useCategories, useConfirmMerchant, useReviewQueue } from '../api/hooks'
import type { ReviewQueueGroup } from '../api/types'
import { formatINR } from '../lib/format'

/**
 * ADR-009 review queue (task 4.3): the non-confirmed, non-manual spend grouped
 * by normalized merchant and sorted by spend. One click per group confirms a
 * merchant + category, restamping every matching transaction and moving the
 * dashboard trust meter. Highest-spend merchants first so the owner buys the
 * most trust for the least clicks.
 */
export default function ReviewQueue() {
  const { data: queue, isLoading } = useReviewQueue()

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton shape="line" className="w-full" />
        <Skeleton shape="line" className="w-5/6" />
        <Skeleton shape="line" className="w-2/3" />
      </div>
    )
  }
  if (!queue || queue.length === 0) {
    return (
      <EmptyState
        title="Nothing left to review."
        blurb="Every merchant's spend is confirmed or manually pinned. Trust meter should read high on the dashboard."
      />
    )
  }

  return (
    <div className="flex flex-col">
      {queue.map((g) => (
        <QueueRow key={g.merchant} group={g} />
      ))}
    </div>
  )
}

function QueueRow({ group }: { group: ReviewQueueGroup }) {
  const { data: categories } = useCategories()
  const confirm = useConfirmMerchant()
  const [category, setCategory] = useState(group.suggested_category)

  const handleConfirm = () => {
    confirm.mutate(
      { merchant: group.merchant, category },
      {
        onSuccess: (res) =>
          toast(`Confirmed — ${res.restamped} transaction${res.restamped === 1 ? '' : 's'} restamped.`, 'good'),
        onError: () => toast('Confirm failed.', 'alert'),
      },
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-ink" title={group.sample}>
          {group.merchant}
        </div>
        <div className="truncate text-2xs text-ink-faint">
          e.g. {group.sample} · {group.count} txn{group.count === 1 ? '' : 's'}
        </div>
      </div>
      <span className="figure shrink-0 text-sm text-ink-mute">{formatINR(group.total)}</span>
      <Select
        label="Category"
        value={category}
        onChange={setCategory}
        options={(categories ?? []).map((c) => ({ value: c, label: c }))}
      />
      <button
        onClick={handleConfirm}
        disabled={confirm.isPending}
        className="btn-primary !px-3 !py-1.5 !text-xs disabled:opacity-50"
      >
        <span>{confirm.isPending ? 'Confirming…' : 'Confirm'}</span>
      </button>
    </div>
  )
}
