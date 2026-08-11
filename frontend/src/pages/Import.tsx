import { useRef, useState } from 'react'
import PageHeader from '../shell/PageHeader'
import Panel from '../components/Panel'
import Select from '../components/Select'
import CardProfileModal from '../components/CardProfileModal'
import EmptyState from '../components/EmptyState'
import { toast } from '../components/Toast'
import {
  useCardProfiles,
  useDedupCandidates,
  useDeleteCardProfile,
  useDeleteStatement,
  useDeleteTransaction,
  useDeleteAllStatements,
  useStatements,
  useUploadStatement,
  useUploadStatementsBulk,
} from '../api/hooks'
import type { BulkUploadResult, UploadResult } from '../api/types'
import { formatINR } from '../lib/format'

const BANKS = [
  { value: '', label: 'Select bank…' },
  { value: 'amex', label: 'American Express' },
  { value: 'hdfc', label: 'HDFC Bank' },
  { value: 'icici', label: 'ICICI Bank' },
  { value: 'axis', label: 'Axis Bank' },
  { value: 'kotak', label: 'Kotak Mahindra Bank' },
  { value: 'idfc', label: 'IDFC First Bank' },
]

const PDF_CAPABLE = new Set(['idfc', 'icici', 'axis', 'kotak', 'hdfc', 'amex'])

export default function Import() {
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [bank, setBank] = useState('')
  const [cardLabel, setCardLabel] = useState('')
  const [password, setPassword] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [bulkResult, setBulkResult] = useState<BulkUploadResult | null>(null)
  const [pendingUpload, setPendingUpload] = useState<{ file: File; card: string; cardLabel: string; password?: string } | null>(null)
  // The File objects a bulk run used, kept so an overlap rejection can be
  // retried with force — the response only carries filenames, and a File
  // can't be reconstructed from one.
  const [pendingBulkFiles, setPendingBulkFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: profiles } = useCardProfiles()
  const deleteProfile = useDeleteCardProfile()
  const { data: statements } = useStatements()
  const deleteStatement = useDeleteStatement()
  const deleteAllStatements = useDeleteAllStatements()
  const { data: dedupCandidates } = useDedupCandidates()
  const deleteTransaction = useDeleteTransaction()
  const upload = useUploadStatement()
  const uploadBulk = useUploadStatementsBulk()

  const handleCardLabelChange = (label: string) => {
    setCardLabel(label)
    const profile = profiles?.find((p) => p.label === label)
    if (profile) setBank(profile.bank)
  }

  const clearFileInput = () => {
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  /** One entry point for both the drop zone and the browse dialog. Routes to
   *  the single or bulk endpoint by COUNT, so the existing one-file flow (with
   *  its force-import retry) is untouched — a bulk retry would have to ask
   *  per-file which to force, which is a different interaction. */
  const handleFiles = (files: File[]) => {
    const named = (f: File) => f.name.toLowerCase()
    if (!bank) {
      setResult({ success: false, error: 'Select a bank first.' } as UploadResult)
      return
    }
    if (!cardLabel) {
      setResult({ success: false, error: 'Select a saved card or add one above.' } as UploadResult)
      return
    }
    const bad = files.filter((f) => !named(f).endsWith('.pdf') && !named(f).endsWith('.csv'))
    if (bad.length) {
      setResult({
        success: false,
        error: `Only .csv or .pdf files — skipped: ${bad.map((f) => f.name).join(', ')}`,
      } as UploadResult)
      return
    }
    if (files.length === 0) return

    setResult(null)
    setBulkResult(null)

    if (files.length === 1) {
      const file = files[0]
      const payload = {
        file, card: bank, cardLabel,
        password: named(file).endsWith('.pdf') ? password : undefined,
      }
      setPendingUpload(payload)
      upload.mutate(payload, { onSuccess: setResult })
    } else {
      setPendingUpload(null)
      setPendingBulkFiles(files)
      uploadBulk.mutate(
        { files, card: bank, cardLabel, password: password || undefined },
        { onSuccess: setBulkResult },
      )
    }
    clearFileInput()
  }

  const handleForceImport = () => {
    if (!pendingUpload) return
    upload.mutate({ ...pendingUpload, force: true }, { onSuccess: setResult })
  }

  /** Force-retry only the files a bulk run rejected for period OVERLAP.
   *  Deliberately narrow: hash-duplicate rejections are never retried, because
   *  `force` doesn't bypass those anyway — that's F4's design, an identical
   *  file is always a mistake. */
  const handleBulkForceOverlaps = () => {
    if (!bulkResult) return
    const overlapped = new Set(
      bulkResult.results.filter((r) => !r.ok && r.overlap).map((r) => r.filename),
    )
    const retry = pendingBulkFiles.filter((f) => overlapped.has(f.name))
    if (!retry.length) return
    uploadBulk.mutate(
      { files: retry, card: bank, cardLabel, password: password || undefined, force: true },
      { onSuccess: setBulkResult },
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Cards"
        title="Import"
        sub="Bring in a statement. Parsed and stored locally."
      />

      <Panel
        title="Your cards"
        meta={
          <button onClick={() => setProfileModalOpen(true)} className="btn-primary !px-3 !py-1 !text-2xs">
            <span>+ Add card</span>
          </button>
        }
      >
        {!profiles || profiles.length === 0 ? (
          <p className="text-sm text-ink-faint">No cards saved yet. Add one to get started.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {profiles.map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-2 rounded-[14px] border border-line bg-carbon-2 px-3 py-1.5"
              >
                <div>
                  <div className="text-sm text-ink">{p.label}</div>
                  <div className="text-2xs text-ink-faint uppercase">
                    {p.bank} · {p.variant} · ****{p.last4}
                  </div>
                </div>
                <button
                  onClick={() =>
                    deleteProfile.mutate(p.id, {
                      onError: (err) => toast(err instanceof Error ? err.message : 'Delete failed.', 'alert'),
                    })
                  }
                  aria-label={`Delete ${p.label}`}
                  className="text-ink-faint transition-colors duration-150 hover:text-alert"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <span className="eyebrow">Bank</span>
            <Select label="Bank" value={bank} onChange={setBank} options={BANKS} className="w-full [&>select]:w-full" />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="eyebrow">Card (select saved card)</span>
            <Select
              label="Card"
              value={cardLabel}
              onChange={handleCardLabelChange}
              options={[
                { value: '', label: '— pick a card or add one above —' },
                ...(profiles ?? []).map((p) => ({ value: p.label, label: p.label })),
              ]}
              className="w-full [&>select]:w-full"
            />
          </div>
          {PDF_CAPABLE.has(bank) && (
            <label className="flex flex-col gap-1.5">
              <span className="eyebrow">PDF password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Statement password (e.g. DOB or PAN)"
                autoComplete="off"
                className="rounded-panel border border-line bg-carbon-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-bright focus:outline-none"
              />
              <span className="text-2xs text-ink-faint">Used only in-memory to unlock. Never stored.</span>
            </label>
          )}
        </div>

        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            if (e.dataTransfer.files.length) handleFiles(Array.from(e.dataTransfer.files))
          }}
          className={`mt-5 flex cursor-pointer flex-col items-center gap-1 rounded-panel border border-dashed px-6 py-10 text-center transition-colors duration-150 ${
            dragOver ? 'border-brand-bright bg-brand/10' : 'border-line hover:border-line-strong'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.pdf"
            multiple
            hidden
            onChange={(e) => e.target.files?.length && handleFiles(Array.from(e.target.files))}
          />
          <span className="text-2xl text-ink-faint">↑</span>
          <p className="text-sm text-ink">
            Drop statements here, or <span className="text-brand-bright underline">browse</span>
          </p>
          <p className="text-2xs text-ink-faint">
            .csv or .pdf — select several to import a whole back-catalogue for this card
          </p>
        </div>

        {(upload.isPending || uploadBulk.isPending) && (
          <p className="mt-4 text-sm text-ink-mute">Importing…</p>
        )}
        {result && <UploadResultPanel result={result} onForceImport={handleForceImport} />}
        {bulkResult && (
          <BulkResultPanel result={bulkResult} onForceOverlaps={handleBulkForceOverlaps} />
        )}
      </Panel>

      <Panel
        title="Import history"
        meta={
          statements && statements.length > 0 ? (
            <button
              onClick={() => {
                const n = statements.length
                // Two-step on purpose: this is the only control in the app that
                // can destroy every import at once, and it sits one click from
                // the per-statement Delete buttons.
                if (!confirm(`Delete ALL ${n} import${n === 1 ? '' : 's'} and every transaction they brought in?\n\nA database backup is taken first.`)) return
                if (!confirm('Really delete everything? This cannot be undone from the UI.')) return
                deleteAllStatements.mutate(undefined, {
                  onSuccess: (r) =>
                    r.error
                      ? toast(r.error, 'alert')
                      : toast(
                          `Deleted ${r.statements_deleted} import(s), ${r.transactions_deleted} transaction(s).` +
                            (r.backup ? ` Backup: ${r.backup}` : ''),
                          'good',
                        ),
                })
              }}
              disabled={deleteAllStatements.isPending}
              className="rounded-panel border border-line px-2 py-1 text-2xs text-ink-mute transition-colors duration-150 hover:border-alert/50 hover:text-alert disabled:opacity-50"
            >
              {deleteAllStatements.isPending ? 'Deleting…' : 'Delete all imports'}
            </button>
          ) : undefined
        }
      >
        {!statements || statements.length === 0 ? (
          <EmptyState title="No imports yet." />
        ) : (
          <div className="flex flex-col">
            {statements.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-4 border-b border-line py-2.5 last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-ink">{s.card_label}</div>
                  <div className="truncate text-2xs text-ink-faint">{s.filename || '—'}</div>
                </div>
                <span className="figure shrink-0 text-xs text-ink-mute">{s.txn_count} txns</span>
                <span className="shrink-0 text-2xs text-ink-faint">{(s.imported_at || '').slice(0, 10)}</span>
                <button
                  onClick={() => {
                    if (confirm('Delete this statement? Its transactions will be removed too.')) {
                      deleteStatement.mutate(s.id)
                    }
                  }}
                  className="shrink-0 rounded-panel border border-line px-2 py-1 text-2xs text-ink-mute transition-colors duration-150 hover:border-alert/50 hover:text-alert"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {dedupCandidates &&
        (dedupCandidates.overlapping_statements.length > 0 || dedupCandidates.duplicate_groups.length > 0) && (
          <Panel
            title="Duplicate cleanup"
            meta={<span className="text-2xs text-ink-faint">Review only — nothing is deleted automatically.</span>}
          >
            <div className="flex flex-col gap-5">
              {dedupCandidates.overlapping_statements.length > 0 && (
                <div>
                  <p className="eyebrow mb-2">Overlapping statements</p>
                  <div className="flex flex-col gap-2">
                    {dedupCandidates.overlapping_statements.map((p) => (
                      <div
                        key={`${p.id1}-${p.id2}`}
                        className="rounded-panel border border-sector-yellow/20 bg-sector-yellow/5 px-3 py-2 text-xs text-ink-mute"
                      >
                        <span className="text-ink">{p.card_label}</span>: statement #{p.id1} ({p.start1} to{' '}
                        {p.end1}, {p.n1} txns) overlaps #{p.id2} ({p.start2} to {p.end2}, {p.n2} txns).{' '}
                        <button
                          onClick={() => {
                            if (confirm(`Delete statement #${p.id1} and its transactions?`)) deleteStatement.mutate(p.id1)
                          }}
                          className="text-brand-bright underline"
                        >
                          delete #{p.id1}
                        </button>{' '}
                        ·{' '}
                        <button
                          onClick={() => {
                            if (confirm(`Delete statement #${p.id2} and its transactions?`)) deleteStatement.mutate(p.id2)
                          }}
                          className="text-brand-bright underline"
                        >
                          delete #{p.id2}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {dedupCandidates.duplicate_groups.length > 0 && (
                <div>
                  <p className="eyebrow mb-2">
                    Duplicate transactions ({dedupCandidates.duplicate_groups.length} group
                    {dedupCandidates.duplicate_groups.length === 1 ? '' : 's'})
                  </p>
                  <div className="flex flex-col gap-2">
                    {dedupCandidates.duplicate_groups.map((g) => (
                      <div
                        key={g.transactions[0].id}
                        className="rounded-panel border border-line bg-carbon-2 px-3 py-2"
                      >
                        <div className="text-xs text-ink-mute">
                          {g.transactions[0].date} · {g.transactions[0].description} ·{' '}
                          <span className="figure">{formatINR(g.transactions[0].amount)}</span> ·{' '}
                          {g.transactions[0].card_label} · appears {g.count}×
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-2">
                          {g.transactions.map((t) => (
                            <button
                              key={t.id}
                              onClick={() => {
                                if (confirm(`Delete transaction #${t.id}?`)) deleteTransaction.mutate(t.id)
                              }}
                              className="rounded-chip border border-line px-2 py-0.5 text-2xs text-ink-mute transition-colors duration-150 hover:border-alert/50 hover:text-alert"
                            >
                              delete #{t.id}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Panel>
        )}

      <CardProfileModal open={profileModalOpen} onClose={() => setProfileModalOpen(false)} />
    </div>
  )
}

/** Per-file outcomes for a bulk run.
 *
 *  Always a LIST, never a single summary line: a batch that half-succeeded is
 *  the normal case (re-importing a back-catalogue trips hash-dedup on files
 *  already loaded), and "8 of 12 imported" without naming the other 4 would
 *  leave the owner unable to tell a duplicate from a parse failure.
 */
function BulkResultPanel({
  result,
  onForceOverlaps,
}: {
  result: BulkUploadResult
  onForceOverlaps: () => void
}) {
  if (result.error) {
    return (
      <div className="mt-4 rounded-panel border border-alert/40 bg-alert/10 px-3.5 py-2.5 text-sm text-alert">
        {result.error}
      </div>
    )
  }
  const allOk = result.failed === 0
  const overlapCount = result.results.filter((r) => !r.ok && r.overlap).length
  return (
    <div
      className={`mt-4 rounded-panel border px-3.5 py-2.5 text-sm ${
        allOk
          ? 'border-sector-green/30 bg-sector-green/10 text-sector-green'
          : 'border-sector-yellow/40 bg-sector-yellow/10 text-sector-yellow'
      }`}
    >
      <p>
        {result.card}: {result.succeeded} of {result.files} file
        {result.files === 1 ? '' : 's'} imported · {result.imported} transaction
        {result.imported === 1 ? '' : 's'}
        {result.failed > 0 && ` · ${result.failed} skipped`}
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {result.results.map((r) => (
          <li key={r.filename} className="flex items-start gap-2 text-2xs">
            <span className={`shrink-0 ${r.ok ? 'text-sector-green' : 'text-ink-faint'}`}>
              {r.ok ? '✓' : '—'}
            </span>
            <span className="min-w-0 flex-1 text-ink-mute">
              <span className="text-ink">{r.filename}</span>
              {r.ok ? (
                <>
                  {' · '}
                  {r.imported} txns
                  {r.reconciled === true && ' · totals reconcile ✓'}
                  {r.reconciled === false && ' · ⚠ totals mismatch'}
                </>
              ) : (
                <> · {r.error}</>
              )}
            </span>
          </li>
        ))}
      </ul>
      {overlapCount > 0 && (
        <button
          onClick={onForceOverlaps}
          className="mt-2.5 rounded-panel border border-sector-yellow/50 px-2.5 py-1 text-2xs text-sector-yellow transition-colors duration-150 hover:bg-sector-yellow/20"
        >
          Force import the {overlapCount} overlapping file{overlapCount === 1 ? '' : 's'}
        </button>
      )}
    </div>
  )
}

function UploadResultPanel({ result, onForceImport }: { result: UploadResult; onForceImport: () => void }) {
  if (!result.success) {
    return (
      <div className="mt-4 rounded-panel border border-alert/40 bg-alert/10 px-3.5 py-2.5 text-sm text-alert">
        <p>{result.error || 'Import failed.'}</p>
        {result.overlap && (
          <button
            onClick={onForceImport}
            className="mt-2 rounded-panel border border-alert/50 px-2.5 py-1 text-2xs text-alert transition-colors duration-150 hover:bg-alert/20"
          >
            Force import anyway
          </button>
        )}
      </div>
    )
  }
  const parts = [`${result.imported} parsed`]
  if (result.reconciled === true) parts.push('totals reconcile ✓')
  else if (result.reconciled === false) parts.push('⚠ totals mismatch')
  if (result.skipped_candidates !== null && result.skipped_candidates !== undefined) {
    parts.push(`${result.skipped_candidates} unparsed line${result.skipped_candidates === 1 ? '' : 's'}`)
  }
  return (
    <div className="mt-4 rounded-panel border border-sector-green/30 bg-sector-green/10 px-3.5 py-2.5 text-sm text-sector-green">
      <p>
        Imported for {result.card}: {parts.join(' · ')}
      </p>
      {result.totals?.tad !== null && result.totals?.tad !== undefined && (
        <p className="mt-1 text-2xs text-ink-faint">Statement total amount due: {formatINR(result.totals.tad)}</p>
      )}
    </div>
  )
}
