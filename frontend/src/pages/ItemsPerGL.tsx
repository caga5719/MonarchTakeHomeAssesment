import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { getItemsPerGL, type ItemsPerGLEntry, type GLLineItemDetail } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const COLORS = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
]

const fmtFull = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function truncate(s: string, max = 26) {
  return s.length > max ? s.slice(0, max) + '…' : s
}

function LineItemRows({ items }: { items: GLLineItemDetail[] }) {
  return (
    <table className="data-table nested-table">
      <thead>
        <tr>
          <th style={{ textAlign: 'center' }}>Invoice #</th>
          <th style={{ textAlign: 'center' }}>Property</th>
          <th style={{ textAlign: 'center' }}>Description</th>
          <th style={{ textAlign: 'center' }}>Subtotal</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, i) => (
          <tr key={i}>
            <td className="mono" style={{ textAlign: 'center' }}>{item.invoice_number}</td>
            <td style={{ textAlign: 'center' }}>{item.property_code ?? '—'}</td>
            <td className="desc-cell" style={{ textAlign: 'center' }}>{item.description}</td>
            <td style={{ textAlign: 'center' }}>
              {item.subtotal != null ? fmtFull(item.subtotal) : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function ItemsPerGL() {
  const [data, setData] = useState<ItemsPerGLEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [codeSearch, setCodeSearch] = useState('')
  const [descSearch, setDescSearch] = useState('')

  useEffect(() => {
    getItemsPerGL()
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner />
  if (error) return <p className="error-msg">Failed to load: {error}</p>

  const filtered = data.filter(r => {
    if (codeSearch && !String(r.gl_code).includes(codeSearch.trim())) return false
    if (descSearch && !r.gl_desc.toLowerCase().includes(descSearch.trim().toLowerCase())) return false
    return true
  })

  const top15 = [...data].sort((a, b) => b.item_count - a.item_count).slice(0, 15)

  function toggle(code: number) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(code) ? next.delete(code) : next.add(code)
      return next
    })
  }

  return (
    <div className="page">
      <h1 className="page-title">Items Per GL Category</h1>

      <div className="section-card">
        <h2 className="chart-title">Top 15 GL Categories by Item Count</h2>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={top15} margin={{ top: 8, right: 16, left: 16, bottom: 80 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="gl_desc"
              tickFormatter={s => truncate(s, 22)}
              angle={-40}
              textAnchor="end"
              interval={0}
              tick={{ fontSize: 11 }}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(v, _name, props) => [
                `${v ?? 0} items (${fmtFull((props as { payload?: ItemsPerGLEntry }).payload?.total_spend ?? 0)})`,
                'Count',
              ]}
              labelFormatter={l => String(l)}
            />
            <Bar dataKey="item_count" name="Items" radius={[4, 4, 0, 0]}>
              {top15.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="section-card">
        <h2 className="chart-title">All GL Categories — click a row to expand line items</h2>
        <div className="filter-bar">
          <input
            className="filter-input filter-input-sm"
            type="text"
            placeholder="GL code…"
            value={codeSearch}
            onChange={e => setCodeSearch(e.target.value)}
          />
          <input
            className="filter-input"
            type="text"
            placeholder="GL description…"
            value={descSearch}
            onChange={e => setDescSearch(e.target.value)}
          />
          {(codeSearch || descSearch) && (
            <button className="filter-clear" onClick={() => { setCodeSearch(''); setDescSearch('') }}>Clear</button>
          )}
        </div>
        {filtered.length === 0 && (
          <p className="empty-msg" style={{ padding: '1rem' }}>No GL categories match.</p>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th></th>
                <th>GL Code</th>
                <th>Description</th>
                <th style={{ textAlign: 'right' }}>Items</th>
                <th style={{ textAlign: 'right' }}>Total Spend Before Tax</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(row => {
                const open = expanded.has(row.gl_code)
                return (
                  <>
                    <tr
                      key={row.gl_code}
                      className="expandable-row"
                      onClick={() => toggle(row.gl_code)}
                    >
                      <td className="expand-toggle">{open ? '▾' : '▸'}</td>
                      <td className="mono">{row.gl_code}</td>
                      <td>{row.gl_desc}</td>
                      <td style={{ textAlign: 'right' }}>{row.item_count.toLocaleString()}</td>
                      <td style={{ textAlign: 'right' }}>{fmtFull(row.total_spend)}</td>
                    </tr>
                    {open && (
                      <tr key={`${row.gl_code}-items`} className="expanded-content">
                        <td colSpan={5}>
                          <LineItemRows items={row.items} />
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
