import { useState } from 'react'

export interface Column<T> {
  key: keyof T | string
  label: string
  sortable?: boolean
  render?: (row: T) => React.ReactNode
  align?: 'left' | 'right' | 'center'
}

interface DataTableProps<T extends object> {
  columns: Column<T>[]
  data: T[]
  rowKey: (row: T) => string | number
  emptyMessage?: string
}

type SortDir = 'asc' | 'desc'

export default function DataTable<T extends object>({
  columns,
  data,
  rowKey,
  emptyMessage = 'No data.',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  function handleSort(key: string) {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = sortKey
    ? [...data].sort((a, b) => {
        const av = (a as Record<string, unknown>)[sortKey]
        const bv = (b as Record<string, unknown>)[sortKey]
        if (av == null && bv == null) return 0
        if (av == null) return 1
        if (bv == null) return -1
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    : data

  if (data.length === 0) {
    return <p className="empty-msg">{emptyMessage}</p>
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map(col => (
              <th
                key={String(col.key)}
                style={{ textAlign: col.align ?? 'left', cursor: col.sortable ? 'pointer' : 'default' }}
                onClick={col.sortable ? () => handleSort(String(col.key)) : undefined}
              >
                {col.label}
                {col.sortable && sortKey === String(col.key) && (
                  <span className="sort-arrow">{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => (
            <tr key={rowKey(row)}>
              {columns.map(col => (
                <td key={String(col.key)} style={{ textAlign: col.align ?? 'left' }}>
                  {col.render
                    ? col.render(row)
                    : String((row as Record<string, unknown>)[String(col.key)] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
