import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts'
import { getSummary, getGLSpend, type Summary, type GLSpendItem } from '../api'
import StatCard from '../components/StatCard'
import LoadingSpinner from '../components/LoadingSpinner'
import DataTable, { type Column } from '../components/DataTable'

const COLORS = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
]

const fmt = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const fmtFull = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function truncate(s: string, max = 28) {
  return s.length > max ? s.slice(0, max) + '…' : s
}

const RADIAN = Math.PI / 180

function renderPieLabel({
  cx, cy, midAngle, outerRadius, name,
}: {
  cx?: number
  cy?: number
  midAngle?: number
  outerRadius?: number
  name?: string
}) {
  if (cx == null || cy == null || midAngle == null || outerRadius == null) return null
  const radius = outerRadius + 30
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)
  return (
    <text
      x={x}
      y={y}
      fill="#475569"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      fontSize={11}
    >
      {truncate(name ?? '', 20)}
    </text>
  )
}


const columns: Column<GLSpendItem>[] = [
  { key: 'gl_code', label: 'GL Code', sortable: true },
  { key: 'gl_desc', label: 'Description', sortable: true },
  { key: 'item_count', label: 'Items', sortable: true, align: 'right' },
  {
    key: 'total_spend',
    label: 'Total Spend',
    sortable: true,
    align: 'right',
    render: row => fmtFull(row.total_spend),
  },
]

export default function GLSpend() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [data, setData] = useState<GLSpendItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getSummary(), getGLSpend()])
      .then(([s, d]) => { setSummary(s); setData(d) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner />
  if (error) return <p className="error-msg">Failed to load: {error}</p>

  const top15 = data.slice(0, 15)
  const pieData = data.slice(0, 10)
  const totalClassifiedSpend = data.reduce((sum, d) => sum + d.total_spend, 0)

  return (
    <div className="page">
      <h1 className="page-title">GL Spend Breakdown</h1>

      {summary && (
        <div className="stat-grid">
          <StatCard label="Total Invoices" value={summary.total_invoices.toLocaleString()} />
          <StatCard label="Classified Spend" value={fmtFull(summary.total_spend)} />
          <StatCard label="Unique GL Codes" value={data.length.toLocaleString()} />
          <StatCard label="Properties" value={summary.properties_count.toLocaleString()} />
          <StatCard
            label="Needs Review"
            value={summary.needs_review_count.toLocaleString()}
            sub="line items flagged by AI"
          />
        </div>
      )}

      <div className="chart-row">
        <div className="chart-card" style={{ flex: 2 }}>
          <h2 className="chart-title">Top 15 GL Categories by Spend</h2>
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={top15} margin={{ top: 8, right: 16, left: 16, bottom: 120 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="gl_desc"
                tickFormatter={s => truncate(s, 18)}
                angle={-65}
                textAnchor="end"
                interval={0}
                tick={{ fontSize: 11 }}
              />
              <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} width={80} />
              <Tooltip formatter={v => typeof v === 'number' ? fmtFull(v) : String(v ?? '')} labelFormatter={l => String(l)} />
              <Bar dataKey="total_spend" name="Spend" radius={[4, 4, 0, 0]}>
                {top15.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card" style={{ flex: 1 }}>
          <h2 className="chart-title">Spend Share (Top 10)</h2>
          <ResponsiveContainer width="100%" height={380}>
            <PieChart margin={{ top: 20, right: 110, bottom: 20, left: 110 }}>
              <Pie
                data={pieData}
                dataKey="total_spend"
                nameKey="gl_desc"
                cx="50%"
                cy="50%"
                outerRadius="70%"
                label={renderPieLabel}
                labelLine={true}
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !Array.isArray(payload) || payload.length === 0) return null
                  const entry = payload[0] as { value?: number }
                  if (typeof entry.value !== 'number') return null
                  const pct = totalClassifiedSpend > 0
                    ? ((entry.value / totalClassifiedSpend) * 100).toFixed(1)
                    : '0.0'
                  return (
                    <div className="pie-tooltip">
                      <div className="pie-tooltip-spend">{fmtFull(entry.value)}</div>
                      <div className="pie-tooltip-pct">{pct}% of classified spend</div>
                    </div>
                  )
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="section-card">
        <h2 className="chart-title">All GL Categories</h2>
        <DataTable
          columns={columns}
          data={data}
          rowKey={r => r.gl_code}
          emptyMessage="No classified line items yet."
        />
      </div>
    </div>
  )
}
