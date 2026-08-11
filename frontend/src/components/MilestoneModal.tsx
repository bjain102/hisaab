import { useEffect, useState } from 'react'
import Modal from './Modal'
import Select from './Select'
import { useCards, useCreateMilestone } from '../api/hooks'
import { toast } from './Toast'

export default function MilestoneModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: cards } = useCards()
  const create = useCreateMilestone()
  const [cardLabel, setCardLabel] = useState('')
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [benefit, setBenefit] = useState('')
  const todayISO = () => new Date().toISOString().slice(0, 10)
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')

  useEffect(() => {
    if (open) {
      setCardLabel(cards?.[0] ?? '')
      setName('')
      setTarget('')
      setBenefit('')
      setWindowStart(todayISO())
      setWindowEnd('')
    }
  }, [open, cards])

  const handleSave = () => {
    const targetNum = parseFloat(target)
    if (!cardLabel || !name.trim() || !targetNum || !windowStart || !windowEnd) {
      toast('Card, name, target, and both window dates are required.', 'alert')
      return
    }
    if (windowEnd < windowStart) {
      toast('Window end must be on or after window start.', 'alert')
      return
    }
    create.mutate(
      {
        card_label: cardLabel, name: name.trim(), target_spend: targetNum,
        window_start: windowStart, window_end: windowEnd, benefit: benefit.trim(),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal open={open} title="Add milestone" onClose={onClose}>
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
          <span className="eyebrow">Milestone name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Annual fee waiver"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Target spend (₹)</span>
          <input
            type="number"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="300000"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Benefit (optional)</span>
          <input
            type="text"
            value={benefit}
            onChange={(e) => setBenefit(e.target.value)}
            placeholder="e.g. ₹5,000 fee waived"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="eyebrow">Window start</span>
            <input
              type="date"
              value={windowStart}
              onChange={(e) => setWindowStart(e.target.value)}
              className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink focus:border-brand-bright focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="eyebrow">Window end</span>
            <input
              type="date"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
              className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink focus:border-brand-bright focus:outline-none"
            />
          </label>
        </div>
        <p className="text-2xs text-ink-faint">
          Progress counts only spend within this window — net of refunds, excluding
          cashback, finance charges, and card-bill payments.
        </p>
      </div>
      <div className="mt-5 flex justify-end gap-2.5">
        <button onClick={onClose} className="btn-secondary">
          <span>Cancel</span>
        </button>
        <button onClick={handleSave} disabled={create.isPending} className="btn-primary disabled:opacity-50">
          <span>{create.isPending ? 'Adding…' : 'Add milestone'}</span>
        </button>
      </div>
    </Modal>
  )
}
