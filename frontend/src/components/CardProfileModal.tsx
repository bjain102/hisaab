import { useState } from 'react'
import Modal from './Modal'
import Select from './Select'
import { useCreateCardProfile } from '../api/hooks'
import { toast } from './Toast'

const BANKS = [
  { value: 'amex', label: 'American Express' },
  { value: 'hdfc', label: 'HDFC Bank' },
  { value: 'icici', label: 'ICICI Bank' },
  { value: 'axis', label: 'Axis Bank' },
  { value: 'kotak', label: 'Kotak Mahindra Bank' },
  { value: 'idfc', label: 'IDFC First Bank' },
]

export default function CardProfileModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [bank, setBank] = useState('amex')
  const [variant, setVariant] = useState('')
  const [last4, setLast4] = useState('')
  const create = useCreateCardProfile()

  const preview = bank && variant && last4 ? `${bank.toUpperCase()}-${variant}-${last4}` : ''
  const validLast4 = /^\d{4}$/.test(last4)

  const handleSave = () => {
    if (!bank || !variant.trim() || !validLast4) {
      toast('Fill in all fields — last 4 must be exactly 4 digits.', 'alert')
      return
    }
    create.mutate(
      { bank, variant: variant.trim(), last4 },
      {
        onSuccess: (data) => {
          if (data.error) {
            toast(data.error, 'alert')
            return
          }
          setVariant('')
          setLast4('')
          onClose()
        },
      },
    )
  }

  return (
    <Modal open={open} title="Add card" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <Select label="Bank" value={bank} onChange={setBank} options={BANKS} className="w-full [&>select]:w-full" />
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Card variant / nickname</span>
          <input
            type="text"
            value={variant}
            onChange={(e) => setVariant(e.target.value)}
            placeholder="e.g. Swiggy, Tata Neu, MyZone, WOW"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="eyebrow">Last 4 digits</span>
          <input
            type="text"
            value={last4}
            maxLength={4}
            onChange={(e) => setLast4(e.target.value.replace(/\D/g, ''))}
            placeholder="1234"
            className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
          />
        </label>
        {preview && <p className="text-xs text-ink-faint">Label will be: {preview}</p>}
      </div>
      <div className="mt-5 flex justify-end gap-2.5">
        <button onClick={onClose} className="btn-secondary">
          <span>Cancel</span>
        </button>
        <button onClick={handleSave} disabled={create.isPending} className="btn-primary disabled:opacity-50">
          <span>{create.isPending ? 'Adding…' : 'Add card'}</span>
        </button>
      </div>
    </Modal>
  )
}
