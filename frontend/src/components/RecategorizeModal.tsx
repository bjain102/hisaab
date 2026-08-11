import { useEffect, useState } from 'react'
import Modal from './Modal'
import Select from './Select'
import { useBlastRadius, useCategories, useRecategorize } from '../api/hooks'
import { formatINR } from '../lib/format'

export default function RecategorizeModal({
  open,
  transactionId,
  merchant,
  currentCategory,
  onClose,
}: {
  open: boolean
  transactionId: number | null
  merchant: string
  currentCategory: string
  onClose: () => void
}) {
  const { data: categories } = useCategories()
  const recategorize = useRecategorize()
  const [category, setCategory] = useState(currentCategory)
  const [learn, setLearn] = useState(true)
  // Blast-radius preview (task 4.3): how many transactions "learn" would restamp.
  const { data: blast } = useBlastRadius(merchant, open && learn)

  // Reset to the transaction's current category each time the modal opens for
  // a (possibly different) row — legacy resets the select on every open too.
  useEffect(() => {
    if (open) {
      setCategory(currentCategory)
      setLearn(true)
    }
  }, [open, currentCategory])

  const handleSave = () => {
    if (transactionId === null) return
    recategorize.mutate(
      { id: transactionId, category, learn, merchant },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal open={open} title="Recategorize transaction" onClose={onClose}>
      <p className="mb-4 truncate text-sm text-ink-mute" title={merchant}>
        {merchant}
      </p>
      <Select
        label="Category"
        value={category}
        onChange={setCategory}
        options={(categories ?? []).map((c) => ({ value: c, label: c }))}
        className="w-full [&>select]:w-full"
      />
      <label className="mt-4 flex items-start gap-2.5 text-sm text-ink-mute">
        <input
          type="checkbox"
          checked={learn}
          onChange={(e) => setLearn(e.target.checked)}
          className="mt-0.5 accent-brand-bright"
        />
        <span>Apply to all similar transactions and remember for future imports</span>
      </label>
      {learn && blast && blast.count > 0 && (
        <p className="mt-2 text-2xs text-ink-faint">
          Confirming this merchant restamps <span className="text-ink">{blast.count}</span> transaction
          {blast.count === 1 ? '' : 's'} ({formatINR(blast.total)} of spend)
          {blast.categories.length > 1 && ` — currently spread across ${blast.categories.length} categories`}.
          Manual pins are left untouched.
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2.5">
        <button onClick={onClose} className="btn-secondary">
          <span>Cancel</span>
        </button>
        <button onClick={handleSave} disabled={recategorize.isPending} className="btn-primary disabled:opacity-50">
          <span>{recategorize.isPending ? 'Saving…' : 'Save'}</span>
        </button>
      </div>
    </Modal>
  )
}
