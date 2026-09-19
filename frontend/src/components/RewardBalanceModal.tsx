import { useEffect, useState } from 'react'
import Modal from './Modal'
import Select from './Select'
import { useCards, useUpsertReward } from '../api/hooks'
import type { RewardValueType } from '../api/types'
import { toast } from './Toast'

const VALUE_TYPES: { value: RewardValueType; label: string }[] = [
  { value: 'points', label: 'Points' },
  { value: 'cashback_inr', label: 'Cashback (₹)' },
  { value: 'balance_inr', label: 'Balance (₹)' },
]

/** One modal serves both add and edit — /api/rewards is an upsert keyed by
 * card_label, matching legacy exactly. Pass `initial` to pre-fill for edit. */
export default function RewardBalanceModal({
  open,
  onClose,
  initial,
}: {
  open: boolean
  onClose: () => void
  initial?: { cardLabel: string; label: string; value: string; valueType: RewardValueType } | null
}) {
  const { data: cards } = useCards()
  const upsert = useUpsertReward()
  const [cardLabel, setCardLabel] = useState('')
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const [valueType, setValueType] = useState<RewardValueType>('points')

  useEffect(() => {
    if (!open) return
    if (initial) {
      setCardLabel(initial.cardLabel)
      setLabel(initial.label)
      setValue(initial.value)
      setValueType(initial.valueType)
    } else {
      setCardLabel(cards?.[0] ?? '')
      setLabel('')
      setValue('')
      setValueType('points')
    }
  }, [open, initial, cards])

  const handleSave = () => {
    const valueNum = parseFloat(value)
    if (!cardLabel || !label.trim() || value === '') {
      toast('All fields required.', 'alert')
      return
    }
    upsert.mutate(
      { card_label: cardLabel, label: label.trim(), value: valueNum, value_type: valueType },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal open={open} title="Add / edit reward balance" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <span className="eyebrow">Card</span>
          <Select
            label="Card"
            value={cardLabel}
            onChange={setCardLabel}
            options={(cards ?? []).map((c) => ({ value: c, label: c }))}
            className="w-full [&>select]:w-full"
          />
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Reward name (e.g. NeuCoins, EDGE Points, Membership Rewards)</span>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. NeuCoins"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Current balance</span>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="0"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <div className="flex flex-col gap-1.5">
          <span className="eyebrow">Type</span>
          <Select
            label="Type"
            value={valueType}
            onChange={(v) => setValueType(v as RewardValueType)}
            options={VALUE_TYPES}
            className="w-full [&>select]:w-full"
          />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2.5">
        <button onClick={onClose} className="btn-secondary">
          <span>Cancel</span>
        </button>
        <button onClick={handleSave} disabled={upsert.isPending} className="btn-primary disabled:opacity-50">
          <span>{upsert.isPending ? 'Saving…' : 'Save'}</span>
        </button>
      </div>
    </Modal>
  )
}
