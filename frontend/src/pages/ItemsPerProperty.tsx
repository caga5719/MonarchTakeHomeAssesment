import { useEffect, useState, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { getItemsPerProperty, type ItemsPerPropertyEntry } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import DataTable, { type Column } from '../components/DataTable'

const COLORS = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
]

const fmtFull = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

const fmt = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const columns: Column<ItemsPerPropertyEntry>[] = [
  { key: 'property_code', label: 'Property Code', sortable: true },
  { key: 'item_count', label: 'Line Items', sortable: true, align: 'right' },
  { key: 'invoice_count', label: 'Invoices', sortable: true, align: 'right' },
  {
    key: 'total_spend',
    label: 'Total Spend Before Tax',
    sortable: true,
    align: 'right',
    render: row => fmtFull(row.total_spend),
  },
]

export default function ItemsPerProperty() {
  const [data, setData] = useState<ItemsPerPropertyEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [propertySearch, setPropertySearch] = useState('')

  useEffect(() => {
    getItemsPerProperty()
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const filteredData = useMemo(() => {
    const term = propertySearch.trim().toUpperCase()
    return term ? data.filter(r => r.property_code.toUpperCase().includes(term)) : data
  }, [data, propertySearch])

  if (loading) return <LoadingSpinner />
  if (error) return <p className="error-msg">Failed to load: {error}</p>

  // Top 25 for the chart (horizontal bars get crowded fast)
  const chartData = data.slice(0, 25)

  return (
    <div className="page">
      <h1 className="page-title">Items Per Property</h1>

      <div className="section-card">
        <h2 className="chart-title">Top 25 Properties by Spend</h2>
        <ResponsiveContainer width="100%" height={Math.max(320, chartData.length * 28)}>
          <BarChart
            layout="vertical"
            data={chartData}
            margin={{ top: 8, right: 80, left: 64, bottom: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
            <XAxis type="number" tickFormatter={fmt} tick={{ fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="property_code"
              width={56}
              tick={{ fontSize: 12, fontFamily: 'monospace' }}
            />
            <Tooltip
              formatter={(v, _name, props) => [
                `${fmtFull(typeof v === 'number' ? v : 0)} · ${(props as { payload?: ItemsPerPropertyEntry }).payload?.item_count ?? 0} items`,
                'Spend',
              ]}
              labelFormatter={l => String(l)}
            />
            <Bar dataKey="total_spend" name="Spend" radius={[0, 4, 4, 0]}>
              {chartData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="section-card">
        <h2 className="chart-title">All Properties</h2>
        <div className="filter-bar">
          <input
            className="filter-input filter-input-sm"
            type="text"
            placeholder="Property code"
            value={propertySearch}
            onChange={e => setPropertySearch(e.target.value)}
          />
          {propertySearch && (
            <button className="filter-clear" onClick={() => setPropertySearch('')}>Clear</button>
          )}
        </div>
        <DataTable
          columns={columns}
          data={filteredData}
          rowKey={r => r.property_code}
          emptyMessage="No properties match."
        />
      </div>
    </div>
  )
}
