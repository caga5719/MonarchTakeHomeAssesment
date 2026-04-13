import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getInvoices, getInvoice,
  type InvoiceListItem, type InvoiceDetail, type LineItemDetail,
} from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const fmtCurrency = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })

const fmtDate = (s: string | null) => (s ? s.slice(0, 10) : '—')

function isMismatch(item: LineItemDetail, invoiceGLCode: number | null) {
  return (
    item.assigned_gl_code != null &&
    invoiceGLCode != null &&
    item.assigned_gl_code !== invoiceGLCode &&
    !item.needs_review
  )
}

function LineItemsPanel({
  invoiceNumber,
  invoiceGLCode,
}: {
  invoiceNumber: string
  invoiceGLCode: number | null
}) {
  const [detail, setDetail] = useState<InvoiceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getInvoice(invoiceNumber)
      .then(setDetail)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [invoiceNumber])

  if (loading) return <div className="panel-loading"><div className="spinner" /></div>
  if (error) return <div className="panel-error">Failed to load: {error}</div>
  if (!detail || detail.line_items.length === 0)
    return <div className="panel-empty">No line items found.</div>

  return (
    <div className="line-items-panel">
      <div className="panel-meta-wrapper">
        <span className="panel-meta-label">Order Overview</span>
        <div className="panel-meta">
          <span><strong>PO #</strong> {detail.po_number ?? '—'}</span>
          <span><strong>Purchaser:</strong> {detail.purchaser ?? '—'}</span>
          <span><strong>Invoice GL Code:</strong> {detail.invoice_gl_code ? `${detail.invoice_gl_code} — ${detail.invoice_gl_desc ?? ''}` : '—'}</span>
          {detail.tax != null && <span><strong>Tax:</strong> {fmtCurrency(detail.tax)}</span>}
        </div>
      </div>
      <div className="table-wrap">
        <table className="data-table nested-table li-table">
          <colgroup>
            <col style={{ width: '40px' }} />    {/* # */}
            <col style={{ width: '22%' }} />      {/* Description */}
            <col style={{ width: '110px' }} />    {/* ASIN */}
            <col style={{ width: '48px' }} />     {/* Qty */}
            <col style={{ width: '90px' }} />     {/* Unit Price */}
            <col style={{ width: '90px' }} />     {/* Subtotal */}
            <col style={{ width: '30%' }} />      {/* AI-Assigned GL */}
          </colgroup>
          <thead>
            <tr>
              <th style={{ textAlign: 'center' }}>#</th>
              <th>Description</th>
              <th style={{ textAlign: 'center' }}>ASIN</th>
              <th style={{ textAlign: 'center' }}>Qty</th>
              <th style={{ textAlign: 'center' }}>Unit Price</th>
              <th style={{ textAlign: 'center' }}>Subtotal</th>
              <th style={{ textAlign: 'center' }}>AI-Assigned Line Item GL Code</th>
            </tr>
          </thead>
          <tbody>
            {detail.line_items.map(item => {
              const mismatch = isMismatch(item, invoiceGLCode)
              return (
                <tr key={item.id} className={mismatch ? 'row-mismatch' : ''}>
                  <td className="mono" style={{ textAlign: 'center' }}>{item.line_number ?? '—'}</td>
                  <td className="li-desc">{item.description}</td>
                  <td className="mono li-nowrap" style={{ textAlign: 'center' }}>{item.asin ?? '—'}</td>
                  <td className="li-nowrap" style={{ textAlign: 'center' }}>{item.quantity ?? '—'}</td>
                  <td className="li-nowrap" style={{ textAlign: 'center' }}>{fmtCurrency(item.unit_price)}</td>
                  <td className="li-nowrap" style={{ textAlign: 'center' }}>{fmtCurrency(item.subtotal)}</td>
                  <td className="li-gl-cell" style={{ textAlign: 'center' }}>
                    {item.needs_review ? (
                      <span className="badge badge-review" title={item.classification_note ?? ''}>
                        Needs Review
                      </span>
                    ) : item.assigned_gl_code != null ? (
                      <>
                        <span className={`mono${mismatch ? ' gl-mismatch-inline' : ''}`}>{item.assigned_gl_code}</span>
                        {item.assigned_gl_desc && (
                          <span className="gl-desc-small"> {item.assigned_gl_desc}</span>
                        )}
                      </>
                    ) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function InvoiceExplorer() {
  const [invoices, setInvoices] = useState<InvoiceListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 25

  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [propertyFilter, setPropertyFilter] = useState('')
  const [glFilter, setGlFilter] = useState('')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  // Debounce search input
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleSearch = (val: string) => {
    setSearch(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(val)
      setPage(1)
    }, 300)
  }

  const fetchInvoices = useCallback(() => {
    setLoading(true)
    setError(null)
    const params: Parameters<typeof getInvoices>[0] = {
      page,
      page_size: PAGE_SIZE,
    }
    if (debouncedSearch) params.search = debouncedSearch
    if (propertyFilter) params.property = propertyFilter
    if (glFilter) params.gl = parseInt(glFilter, 10)

    getInvoices(params)
      .then(r => { setInvoices(r.items); setTotal(r.total) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [page, debouncedSearch, propertyFilter, glFilter])

  useEffect(() => { fetchInvoices() }, [fetchInvoices])

  // Reset page when filters change
  useEffect(() => { setPage(1) }, [propertyFilter, glFilter])

  function toggleRow(id: number) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="page">
      <h1 className="page-title">Invoice Explorer</h1>

      <div className="section-card info-card">
        <p>
          Browse and search all processed invoices. Click any row to expand it and view its individual line items with AI-assigned GL classifications.
        </p>
        <p style={{ marginTop: '0.6rem' }}>
          <strong>Status</strong> — <span className="badge badge-ok">OK</span> invoices have a recognized property code and fully classified line items.{' '}
          <span className="badge badge-review">Needs Review</span> invoices have an unrecognized property code and require manual resolution before line items can be classified.
        </p>
        <p style={{ marginTop: '0.6rem' }}>
          <strong>AI-Assigned GL</strong> — each line item is independently classified by Claude AI based on its description, regardless of the invoice-level GL code.{' '}
          <span className="badge badge-review">Needs Review</span> on a line item means the AI could not confidently assign a GL code; hover the badge to see the reason.
        </p>
        <p style={{ marginTop: '0.6rem' }}>
          <strong>Row highlighting</strong> — line items highlighted in <span style={{ background: '#fffbeb', padding: '0.1rem 0.4rem', borderRadius: '3px', fontSize: '0.82rem', border: '1px solid #fde68a' }}>amber</span> indicate that the AI-assigned GL differs from the invoice-level GL code, suggesting the buyer's original coding may not match the item's actual category.
        </p>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <input
          className="filter-input"
          type="text"
          placeholder="Search invoice #, property, or purchaser…"
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
        <input
          className="filter-input filter-input-sm"
          type="text"
          placeholder="Property code"
          value={propertyFilter}
          onChange={e => { setPropertyFilter(e.target.value.toUpperCase()); setPage(1) }}
        />
        <input
          className="filter-input filter-input-sm"
          type="number"
          placeholder="GL code"
          value={glFilter}
          onChange={e => { setGlFilter(e.target.value); setPage(1) }}
        />
        {(debouncedSearch || propertyFilter || glFilter) && (
          <button
            className="filter-clear"
            onClick={() => {
              setSearch('')
              setDebouncedSearch('')
              setPropertyFilter('')
              setGlFilter('')
              setPage(1)
            }}
          >
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <p className="error-msg">Failed to load: {error}</p>
      ) : (
        <>
          <div className="section-card" style={{ padding: 0 }}>
            <div className="table-result-count">
              {total.toLocaleString()} invoice{total !== 1 ? 's' : ''}
              {(debouncedSearch || propertyFilter || glFilter) ? ' matched' : ' total'}
            </div>
            {invoices.length === 0 ? (
              <p className="empty-msg" style={{ padding: '1.5rem' }}>No invoices match the current filters.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th></th>
                      <th style={{ textAlign: 'center' }}>Invoice #</th>
                      <th style={{ textAlign: 'center' }}>Date</th>
                      <th style={{ textAlign: 'center' }}>Property</th>
                      <th style={{ textAlign: 'center' }}>Purchaser</th>
                      <th style={{ textAlign: 'center' }}>Invoice GL Code</th>
                      <th style={{ textAlign: 'center' }}>Total</th>
                      <th style={{ textAlign: 'center' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map(inv => {
                      const open = expanded.has(inv.id)
                      return (
                        <>
                          <tr
                            key={inv.id}
                            className="expandable-row"
                            onClick={() => toggleRow(inv.id)}
                          >
                            <td className="expand-toggle">{open ? '▾' : '▸'}</td>
                            <td className="mono" style={{ textAlign: 'center' }}>{inv.invoice_number}</td>
                            <td className="mono" style={{ textAlign: 'center' }}>{fmtDate(inv.invoice_date)}</td>
                            <td style={{ textAlign: 'center' }}>{inv.property_code ?? '—'}</td>
                            <td style={{ textAlign: 'center' }}>{inv.purchaser ?? '—'}</td>
                            <td className="mono" style={{ textAlign: 'center' }}>
                              {inv.invoice_gl_code != null
                                ? `${inv.invoice_gl_code}${inv.invoice_gl_desc ? ` — ${inv.invoice_gl_desc}` : ''}`
                                : '—'}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              {fmtCurrency(inv.total_amount)}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              {inv.needs_review
                                ? <span className="badge badge-review">Needs Review</span>
                                : <span className="badge badge-ok">OK</span>}
                            </td>
                          </tr>
                          {open && (
                            <tr key={`${inv.id}-detail`} className="expanded-content">
                              <td colSpan={8}>
                                <LineItemsPanel
                                  invoiceNumber={inv.invoice_number}
                                  invoiceGLCode={inv.invoice_gl_code}
                                />
                              </td>
                            </tr>
                          )}
                        </>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="page-btn"
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
              >
                ← Prev
              </button>
              <span className="page-info">
                Page {page} of {totalPages}
              </span>
              <button
                className="page-btn"
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
