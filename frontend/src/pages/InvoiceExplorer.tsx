import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getInvoices, getInvoice,
  type InvoiceListItem, type InvoiceDetail, type LineItemDetail,
} from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const fmtCurrency = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

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
      <div className="panel-meta">
        <span>PO #{detail.po_number ?? '—'}</span>
        <span>Purchaser: {detail.purchaser ?? '—'}</span>
        <span>Invoice GL: {detail.invoice_gl_code ? `${detail.invoice_gl_code} — ${detail.invoice_gl_desc ?? ''}` : '—'}</span>
        {detail.subtotal != null && <span>Subtotal: {fmtCurrency(detail.subtotal)}</span>}
        {detail.tax != null && <span>Tax: {fmtCurrency(detail.tax)}</span>}
      </div>
      <div className="table-wrap">
        <table className="data-table nested-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Description</th>
              <th>ASIN</th>
              <th style={{ textAlign: 'right' }}>Qty</th>
              <th style={{ textAlign: 'right' }}>Unit Price</th>
              <th style={{ textAlign: 'right' }}>Subtotal</th>
              <th>Invoice GL</th>
              <th>AI-Assigned GL</th>
            </tr>
          </thead>
          <tbody>
            {detail.line_items.map(item => {
              const mismatch = isMismatch(item, invoiceGLCode)
              return (
                <tr key={item.id} className={mismatch ? 'row-mismatch' : ''}>
                  <td className="mono">{item.line_number ?? '—'}</td>
                  <td className="desc-cell">{item.description}</td>
                  <td className="mono">{item.asin ?? '—'}</td>
                  <td style={{ textAlign: 'right' }}>{item.quantity ?? '—'}</td>
                  <td style={{ textAlign: 'right' }}>{fmtCurrency(item.unit_price)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtCurrency(item.subtotal)}</td>
                  <td className="mono">
                    {invoiceGLCode ?? '—'}
                  </td>
                  <td>
                    {item.needs_review ? (
                      <span className="badge badge-review" title={item.classification_note ?? ''}>
                        Needs Review
                      </span>
                    ) : item.assigned_gl_code != null ? (
                      <span className={mismatch ? 'gl-mismatch-inline' : ''}>
                        <span className="mono">{item.assigned_gl_code}</span>
                        {item.assigned_gl_desc && (
                          <span className="gl-desc-small"> {item.assigned_gl_desc}</span>
                        )}
                      </span>
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
                      <th>Invoice #</th>
                      <th>Date</th>
                      <th>Property</th>
                      <th>Purchaser</th>
                      <th>Invoice GL</th>
                      <th style={{ textAlign: 'right' }}>Total</th>
                      <th>Status</th>
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
                            <td className="mono">{inv.invoice_number}</td>
                            <td className="mono">{fmtDate(inv.invoice_date)}</td>
                            <td>{inv.property_code ?? '—'}</td>
                            <td>{inv.purchaser ?? '—'}</td>
                            <td className="mono">
                              {inv.invoice_gl_code != null
                                ? `${inv.invoice_gl_code}${inv.invoice_gl_desc ? ` — ${inv.invoice_gl_desc}` : ''}`
                                : '—'}
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              {fmtCurrency(inv.total_amount)}
                            </td>
                            <td>
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
