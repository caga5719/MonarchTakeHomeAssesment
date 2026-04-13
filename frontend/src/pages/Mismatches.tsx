import { useEffect, useState } from 'react'
import { getMismatches, getNeedsReview, type MismatchItem, type NeedsReviewItem } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const fmtCurrency = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

/** Returns 'same' | 'near' | 'far' based on how close the two GL codes are. */
function mismatchSeverity(invoiceGL: number | null, assignedGL: number): 'same' | 'near' | 'far' {
  if (invoiceGL == null) return 'far'
  // Same hundreds block = "near" (e.g., both 67xx)
  const invoiceFamily = Math.floor(invoiceGL / 100)
  const assignedFamily = Math.floor(assignedGL / 100)
  if (invoiceFamily === assignedFamily) return 'near'
  return 'far'
}

function SeverityBadge({ severity }: { severity: 'near' | 'far' }) {
  return severity === 'near'
    ? <span className="mismatch-badge mismatch-near">Same family</span>
    : <span className="mismatch-badge mismatch-far">Different family</span>
}

export default function Mismatches() {
  const [mismatches, setMismatches] = useState<MismatchItem[]>([])
  const [needsReview, setNeedsReview] = useState<NeedsReviewItem[]>([])
  const [totalLineItems, setTotalLineItems] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getMismatches(), getNeedsReview()])
      .then(([mm, nr]) => {
        setMismatches(mm)
        setNeedsReview(nr)
        // Approximate total: mismatches + needs_review gives a floor;
        // we'll show exact counts from what the API returns.
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner />
  if (error) return <p className="error-msg">Failed to load: {error}</p>

  const nearCount = mismatches.filter(m => mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code) === 'near').length
  const farCount = mismatches.filter(m => mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code) === 'far').length

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

      {/* Mismatch table */}
      <div className="section-card">
        <h2 className="chart-title">
          Reclassified Line Items ({mismatches.length.toLocaleString()})
        </h2>
        {mismatches.length === 0 ? (
          <p className="empty-msg">No mismatches found — all line items match their invoice GL code.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Property</th>
                  <th>Item Description</th>
                  <th>Invoice GL (Original)</th>
                  <th>AI-Assigned GL</th>
                  <th style={{ textAlign: 'right' }}>Subtotal</th>
                  <th>Severity</th>
                </tr>
              </thead>
              <tbody>
                {mismatches.map((m, i) => {
                  const severity = mismatchSeverity(m.invoice_gl_code, m.assigned_gl_code)
                  return (
                    <tr
                      key={i}
                      className={severity === 'near' ? 'row-mismatch-near' : 'row-mismatch-far'}
                    >
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
      </div>

      {/* Needs Review table */}
      {needsReview.length > 0 && (
        <div className="section-card">
          <h2 className="chart-title">
            Items Needing Human Review ({needsReview.length.toLocaleString()})
          </h2>
          <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1rem' }}>
            These line items could not be confidently assigned to any GL code by the AI.
            The note explains why. A human should assign the correct code.
          </p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Property</th>
                  <th>Description</th>
                  <th>Invoice GL (hint)</th>
                  <th>AI Note</th>
                </tr>
              </thead>
              <tbody>
                {needsReview.map(item => (
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
        </div>
      )}
    </div>
  )
}
