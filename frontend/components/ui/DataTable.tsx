'use client'
import { useState, useMemo } from 'react'
import { Pagination } from './Pagination'
import { LoadingState } from './LoadingState'
import { EmptyState } from './EmptyState'

export type SortDir = 'asc' | 'desc'

export interface Column<T> {
  header: string
  /** Render the cell content */
  cell: (row: T) => React.ReactNode
  /** Return a comparable value for sorting; omit to disable sorting */
  sortValue?: (row: T) => string | number | null | undefined
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  pageSize?: number
  loading?: boolean
  emptyTitle?: string
  emptyDescription?: string
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  pageSize = 25,
  loading = false,
  emptyTitle = 'No records found',
  emptyDescription,
  className = '',
}: DataTableProps<T>) {
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [page, setPage] = useState(1)

  const sorted = useMemo(() => {
    if (sortCol === null || !columns[sortCol]?.sortValue) return rows
    const sv = columns[sortCol].sortValue!
    return [...rows].sort((a, b) => {
      const va = sv(a) ?? ''
      const vb = sv(b) ?? ''
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [rows, sortCol, sortDir, columns])

  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize
    return sorted.slice(start, start + pageSize)
  }, [sorted, page, pageSize])

  // Reset to page 1 when rows change
  useMemo(() => { setPage(1) }, [rows.length])

  const toggleSort = (idx: number) => {
    if (!columns[idx]?.sortValue) return
    if (sortCol === idx) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(idx)
      setSortDir('asc')
    }
  }

  if (loading) return <LoadingState />
  if (!rows.length) return <EmptyState title={emptyTitle} description={emptyDescription} />

  return (
    <div className={`overflow-hidden ${className}`}>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  scope="col"
                  onClick={() => toggleSort(i)}
                  className={`px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap select-none ${
                    col.sortValue ? 'cursor-pointer hover:text-gray-700' : ''
                  } ${col.className ?? ''}`}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    {col.sortValue && sortCol === i && (
                      <span className="text-blue-500">
                        {sortDir === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                    {col.sortValue && sortCol !== i && (
                      <span className="text-gray-300">↕</span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-100">
            {paginated.map(row => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={`transition-colors ${
                  onRowClick ? 'cursor-pointer hover:bg-blue-50' : ''
                }`}
              >
                {columns.map((col, i) => (
                  <td key={i} className={`px-4 py-3 ${col.className ?? ''}`}>
                    {col.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={pageSize} total={sorted.length} onChange={setPage} />
    </div>
  )
}
