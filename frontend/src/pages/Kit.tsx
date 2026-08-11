import { useState } from 'react'
import PageHeader from '../shell/PageHeader'
import Panel from '../components/Panel'
import StatCard from '../components/StatCard'
import AnimatedNumber from '../components/AnimatedNumber'
import DeltaChip from '../components/DeltaChip'
import TimingTower from '../components/TimingTower'
import type { TowerRow } from '../components/TimingTower'
import DataTable from '../components/DataTable'
import Select from '../components/Select'
import Modal from '../components/Modal'
import { toast } from '../components/Toast'
import EmptyState from '../components/EmptyState'
import Skeleton from '../components/Skeleton'

// Synthetic demo data only — the kit never touches real figures.
const towerA: TowerRow[] = [
  { id: 'alpha', label: 'CARD ALPHA', value: '₹1,00,000', share: 1, trailing: <DeltaChip value={12500} /> },
  { id: 'bravo', label: 'CARD BRAVO', value: '₹82,400', share: 0.82, trailing: <DeltaChip value={-9100} /> },
  { id: 'charlie', label: 'CARD CHARLIE', value: '₹41,000', share: 0.41, trailing: <DeltaChip value={0} /> },
  { id: 'delta', label: 'CARD DELTA', value: '₹12,750', share: 0.13 },
]
const towerB: TowerRow[] = [towerA[1], towerA[3], towerA[0], towerA[2]]

type DemoRow = { merchant: string; category: string; amount: string }
const tableRows: DemoRow[] = [
  { merchant: 'Sample Grocer', category: 'Grocery', amount: '₹1,234.00' },
  { merchant: 'Sample Airline', category: 'Travel', amount: '₹45,600.00' },
  { merchant: 'Sample Cafe', category: 'Food & Drinks', amount: '₹410.50' },
]

export default function Kit() {
  const [tick, setTick] = useState(123456.78)
  const [reordered, setReordered] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [range, setRange] = useState('ytd')

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Internal"
        title="Component kit"
        sub="Every component in every state. Synthetic data only."
      />

      <Panel title="Stat cards" meta="hero row anatomy">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Net spend" meta="after refunds">
            <AnimatedNumber value={tick} className="text-xl" />
          </StatCard>
          <StatCard label="vs last month" meta="lower is better">
            <DeltaChip value={-13507} className="text-base" />
          </StatCard>
          <StatCard label="Gap — left on table" reserved={{ phase: 'Phase 5', note: 'Lights up with the rewards engine.' }} />
          <StatCard label="Category trust" reserved={{ phase: 'Phase 4', note: 'Lights up with merchant review.' }} />
        </div>
        <button
          onClick={() => setTick((v) => (v > 200000 ? 123456.78 : v + 98765.43))}
          className="mt-4 rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
        >
          Re-spring the number
        </button>
      </Panel>

      <Panel title="Timing tower" meta="the signature — FLIP reorder">
        <TimingTower rows={reordered ? towerB : towerA} leaderBarClass="bg-sector-purple" />
        <button
          onClick={() => setReordered((r) => !r)}
          className="mt-4 rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
        >
          Swap positions
        </button>
      </Panel>

      <Panel title="Delta chips" meta="sector semantics">
        <div className="flex flex-wrap items-center gap-3">
          <DeltaChip value={12340} goodWhen="up" />
          <DeltaChip value={12340} goodWhen="down" />
          <DeltaChip value={-8120} goodWhen="down" />
          <DeltaChip value={0} />
        </div>
      </Panel>

      <Panel title="Primary button" meta="brand navy — rare chrome accent, never on repeated rows">
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-primary">
            <span>Import statement</span>
          </button>
          <button className="btn-primary">
            <span>Confirm merchant</span>
          </button>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Data table">
          <DataTable<DemoRow>
            columns={[
              { key: 'm', header: 'Merchant', cell: (r) => r.merchant },
              { key: 'c', header: 'Category', cell: (r) => r.category },
              { key: 'a', header: 'Amount', align: 'right', numeric: true, cell: (r) => r.amount },
            ]}
            rows={tableRows}
            rowKey={(r) => r.merchant}
          />
        </Panel>

        <Panel title="Controls">
          <div className="flex flex-wrap items-center gap-3">
            <Select
              label="Date range"
              value={range}
              onChange={setRange}
              options={[
                { value: 'ytd', label: 'Year to date' },
                { value: 'all', label: 'All time' },
                { value: '3m', label: 'Last 3 months' },
              ]}
            />
            <button
              onClick={() => setModalOpen(true)}
              className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
            >
              Open modal
            </button>
            <button
              onClick={() => toast('Imported 34 transactions', 'good')}
              className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
            >
              Good toast
            </button>
            <button
              onClick={() => toast('Statement period overlaps an existing import', 'alert')}
              className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-line-strong"
            >
              Alert toast
            </button>
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Loading" meta="skeletons">
          <div className="flex flex-col gap-3">
            <Skeleton shape="stat" />
            <Skeleton shape="line" />
            <Skeleton shape="block" className="h-24" />
          </div>
        </Panel>

        <Panel title="Empty state">
          <EmptyState
            chip="No data"
            title="No transactions in this range."
            blurb="Import a statement in the legacy UI to see figures here."
          />
        </Panel>
      </div>

      <Modal open={modalOpen} title="Recategorize" onClose={() => setModalOpen(false)}>
        <p className="text-sm text-ink-mute">
          Modal body demo. Escape or backdrop click closes it.
        </p>
      </Modal>
    </div>
  )
}
