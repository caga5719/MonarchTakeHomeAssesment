import { useEffect, useState } from 'react'
import { getMismatches, getNeedsReview, type MismatchItem, type NeedsReviewItem } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtCurrency = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function mismatchSeverity(invoiceGL: number | null, assignedGL: number): 'near' | 'far' {
  if (invoiceGL == null) return 'far'
  return Math.floor(invoiceGL / 100) === Math.floor(assignedGL / 100) ? 'near' : 'far'
}

function SeverityBadge({ severity }: { severity: 'near' | 'far' }) {
  return severity === 'near'
    ? <span className="mismatch-badge mismatch-near">Same family</span>
    : <span className="mismatch-badge mismatch-far">Different family</span>
}

function sectionFilter<T extends { invoice_number: string; property_code: string | null }>(
  items: T[], invoice: string, property: string,
): T[] {
  const inv = invoice.trim().toLowerCase()
  const prop = property.trim().toLowerCase()
  return items.filter(item => {
    if (inv && !item.invoice_number.toLowerCase().includes(inv)) return false
    if (prop && !(item.property_code ?? '').toLowerCase().includes(prop)) return false
    return true
  })
}

// ── Generic sort ──────────────────────────────────────────────────────────────

type SortDir = 'asc' | 'desc'

function cmp(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0
  if (a == null) return 1   // nulls last
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b))
}

function sortRows<T>(rows: T[], key: keyof T | null, dir: SortDir): T[] {
  if (!key) return rows
  return [...rows].sort((a, b) => {
    const result = cmp(a[key], b[key])
    return dir === 'asc' ? result : -result
  })
}

// ── SortableHeader ────────────────────────────────────────────────────────────

function SortableHeader<K extends string>({
  label, col, active, dir, onSort, style,
}: {
  label: string
  col: K
  active: K | null
  dir: SortDir
  onSort: (col: K) => void
  style?: React.CSSProperties
}) {
  const isActive = active === col
  return (
    <th
      className="sortable-th"
      style={style}
      onClick={() => onSort(col)}
    >
      {label}
      <span className="sort-indicator">
        {isActive ? (dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}
      </span>
    </th>
  )
}

// ── Types for sort keys ───────────────────────────────────────────────────────

type MmKey = keyof MismatchItem | 'severity'
type NrKey = keyof NeedsReviewItem

// ── Component ─────────────────────────────────────────────────────────────────

export default function Mismatches() {
  const [mismatches, setMismatches] = useState<MismatchItem[]>([])
  const [needsReview, setNeedsReview] = useState<NeedsReviewItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [mismatchesOpen, setMismatchesOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)

  // Per-section search
  const [mmInvoice, setMmInvoice] = useState('')
  const [mmProperty, setMmProperty] = useState('')
  const [nrInvoice, setNrInvoice] = useState('')
  const [nrProperty, setNrProperty] = useState('')

  // Per-section sort — mismatches table
  const [mmSortKey, setMmSortKey] = useState<MmKey | null>(null)
  const [mmSortDir, setMmSortDir] = useState<SortDir>('asc')

  // Per-section sort — needs-review table
  const [nrSortKey, setNrSortKey] = useState<NrKey | null>(null)
  const [nrSortDir, setNrSortDir] = useState<SortDir>('asc')

  useEffect(() => {
    Promise.all([getMismatches(), getNeedsReview()])
      .then(([mm, nr]) => { setMismatches(mm); setNeedsReview(nr) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner />
  if (error) return <p className="error-msg">Failed to load: {error}</p>

  const nearCount = mismatches.filter(m => mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code) === 'near').length
  const farCount  = mismatches.filter(m => mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code) === 'far').length

  // Filter then sort — mismatches
  const filteredMismatches = sectionFilter(mismatches, mmInvoice, mmProperty)
  const sortedMismatches = mmSortKey === 'severity'
    ? [...filteredMismatches].sort((a, b) => {
        const sa = mismatchSeverity(a.invoice_gl_code, a.assigned_gl_code)
        const sb = mismatchSeverity(b.invoice_gl_code, b.assigned_gl_code)
        const result = sa.localeCompare(sb)
        return mmSortDir === 'asc' ? result : -result
      })
    : sortRows(filteredMismatches, mmSortKey as keyof MismatchItem | null, mmSortDir)

  // Filter then sort — needs review
  const filteredReview = sectionFilter(needsReview, nrInvoice, nrProperty)
  const sortedReview = sortRows(filteredReview, nrSortKey, nrSortDir)

  function handleMmSort(col: MmKey) {
    if (mmSortKey === col) setMmSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setMmSortKey(col); setMmSortDir('asc') }
  }

  function handleNrSort(col: NrKey) {
    if (nrSortKey === col) setNrSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setNrSortKey(col); setNrSortDir('asc') }
  }

  return (
    <div className="page">
      <h1 className="page-title">GL Mismatches</h1>

      {/* Intro */}
      <div className="section-card info-card">
        <p>
          Each invoice carries a <strong>header-level GL code</strong> chosen by the buyer at purchase time.
          The AI classifier assigns a GL code <em>independently</em> to each line item based on its description.
          When the two codes differ, it may indicate a miscoding by the buyer, a multi-category invoice,
          or an edge case worth reviewing.
        </p>
        <p style={{ marginTop: '0.6rem' }}>
          Color coding: <span className="mismatch-badge mismatch-near">Same family</span> means
          both codes share the same hundreds block (e.g., 67xx vs 67xx) — a minor reclassification.{' '}
          <span className="mismatch-badge mismatch-far">Different family</span> means the AI assigned
          a code in a different range — a more significant reclassification worth investigating.
        </p>
      </div>

      {/* Summary stats */}
      <div className="stat-grid" style={{ marginBottom: '1.5rem' }}>
        <div className="stat-card">
          <div className="stat-label">Total Mismatches</div>
          <div className="stat-value">{mismatches.length.toLocaleString()}</div>
          <div className="stat-sub">line items reclassified by AI</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Same Family</div>
          <div className="stat-value" style={{ color: '#d97706' }}>{nearCount.toLocaleString()}</div>
          <div className="stat-sub">minor reclassification (same GL family)</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Different Family</div>
          <div className="stat-value" style={{ color: '#dc2626' }}>{farCount.toLocaleString()}</div>
          <div className="stat-sub">significant reclassification</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Needs Review</div>
          <div className="stat-value" style={{ color: '#7c3aed' }}>{needsReview.length.toLocaleString()}</div>
          <div className="stat-sub">items AI couldn't confidently classify</div>
        </div>
      </div>

      {/* ── Needs Review — collapsible ─────────────────────────────────────── */}
      {needsReview.length > 0 && (
        <div className="section-card">
          <button
            className="collapsible-header"
            onClick={() => setReviewOpen(o => !o)}
            aria-expanded={reviewOpen}
          >
            <span className="chart-title" style={{ margin: 0 }}>
              Items Needing Human Review ({needsReview.length.toLocaleString()})
            </span>
            <span className="collapse-chevron">{reviewOpen ? '▲' : '▼'}</span>
          </button>

          {reviewOpen && (
            <>
              <p style={{ color: '#64748b', fontSize: '0.85rem', margin: '0.75rem 0 0.75rem' }}>
                These line items could not be confidently assigned to any GL code by the AI.
                The note explains why. A human should assign the correct code.
              </p>

              <div className="section-filter-bar">
                <input className="filter-input" type="text" placeholder="Search invoice #…"
                  value={nrInvoice} onChange={e => setNrInvoice(e.target.value)} />
                <input className="filter-input" type="text" placeholder="Search property…"
                  value={nrProperty} onChange={e => setNrProperty(e.target.value)} />
                {(nrInvoice || nrProperty) && (
                  <button className="filter-clear" onClick={() => { setNrInvoice(''); setNrProperty('') }}>Clear</button>
                )}
                <span className="section-filter-count">
                  {filteredReview.length.toLocaleString()} of {needsReview.length.toLocaleString()}
                </span>
              </div>

              {filteredReview.length === 0 ? (
                <p className="empty-msg">No items match the current filters.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <SortableHeader label="Invoice #"         col="invoice_number"    active={nrSortKey} dir={nrSortDir} onSort={handleNrSort} />
                        <SortableHeader label="Property"          col="property_code"     active={nrSortKey} dir={nrSortDir} onSort={handleNrSort} />
                        <SortableHeader label="Description"       col="description"       active={nrSortKey} dir={nrSortDir} onSort={handleNrSort} />
                        <SortableHeader label="Invoice GL (hint)" col="invoice_gl_code"   active={nrSortKey} dir={nrSortDir} onSort={handleNrSort} />
                        <SortableHeader label="AI Note"           col="classification_note" active={nrSortKey} dir={nrSortDir} onSort={handleNrSort} />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedReview.map(item => (
                        <tr key={item.id} className="row-needs-review">
                          <td className="mono">{item.invoice_number}</td>
                          <td>{item.property_code ?? '—'}</td>
                          <td className="desc-cell">{item.description}</td>
                          <td className="mono">
                            {item.invoice_gl_code != null
                              ? <>{item.invoice_gl_code}<span className="gl-desc-small"> {item.invoice_gl_desc}</span></>
                              : '—'}
                          </td>
                          <td className="note-cell">{item.classification_note ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Reclassified Line Items — collapsible ──────────────────────────── */}
      <div className="section-card">
        <button
          className="collapsible-header"
          onClick={() => setMismatchesOpen(o => !o)}
          aria-expanded={mismatchesOpen}
        >
          <span className="chart-title" style={{ margin: 0 }}>
            Reclassified Line Items ({mismatches.length.toLocaleString()})
          </span>
          <span className="collapse-chevron">{mismatchesOpen ? '▲' : '▼'}</span>
        </button>

        {mismatchesOpen && (
          mismatches.length === 0 ? (
            <p className="empty-msg" style={{ marginTop: '0.75rem' }}>
              No mismatches found — all line items match their invoice GL code.
            </p>
          ) : (
            <>
              <div className="section-filter-bar">
                <input className="filter-input" type="text" placeholder="Search invoice #…"
                  value={mmInvoice} onChange={e => setMmInvoice(e.target.value)} />
                <input className="filter-input" type="text" placeholder="Search property…"
                  value={mmProperty} onChange={e => setMmProperty(e.target.value)} />
                {(mmInvoice || mmProperty) && (
                  <button className="filter-clear" onClick={() => { setMmInvoice(''); setMmProperty('') }}>Clear</button>
                )}
                <span className="section-filter-count">
                  {sortedMismatches.length.toLocaleString()} of {mismatches.length.toLocaleString()}
                </span>
              </div>

              {sortedMismatches.length === 0 ? (
                <p className="empty-msg">No items match the current filters.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <SortableHeader label="Invoice #"           col="invoice_number"   active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                        <SortableHeader label="Property"            col="property_code"    active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                        <SortableHeader label="Item Description"    col="line_item_desc"   active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                        <SortableHeader label="Invoice GL (Original)" col="invoice_gl_code" active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                        <SortableHeader label="AI-Assigned GL"      col="assigned_gl_code" active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                        <SortableHeader label="Subtotal"            col="subtotal"         active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} style={{ textAlign: 'right' }} />
                        <SortableHeader label="Severity"            col="severity"         active={mmSortKey} dir={mmSortDir} onSort={handleMmSort} />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedMismatches.map((m, i) => {
                        const severity = mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code)
                        return (
                          <tr key={i} className={severity === 'near' ? 'row-mismatch-near' : 'row-mismatch-far'}>
                            <td className="mono">{m.invoice_number}</td>
                            <td>{m.property_code ?? '—'}</td>
                            <td className="desc-cell">{m.line_item_desc}</td>
                            <td className="mono">
                              {m.invoice_gl_code != null
                                ? <>{m.invoice_gl_code}<span className="gl-desc-small"> {m.invoice_gl_desc}</span></>
                                : '—'}
                            </td>
                            <td className="mono">
                              {m.assigned_gl_code}
                              <span className="gl-desc-small"> {m.assigned_gl_desc}</span>
                            </td>
                            <td style={{ textAlign: 'right' }}>{fmtCurrency(m.subtotal)}</td>
                            <td><SeverityBadge severity={severity} /></td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )
        )}
      </div>
    </div>
  )
}
