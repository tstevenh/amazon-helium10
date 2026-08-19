'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronsUpDown, ChevronUp, Columns3 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Pagination } from './Pagination'
import { useColumnWidths } from './useColumnWidths'
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
  /** Column index to sort by on first render. Omit for API order. */
  defaultSortCol?: number
  /** Direction for defaultSortCol. */
  defaultSortDir?: SortDir
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  /**
   * Destination for this row. When given, the FIRST column is rendered as a
   * real <a href>, so right-click -> "Open in new tab" and cmd/ctrl-click
   * work. onRowClick alone cannot do that: a click handler on <tr> is
   * invisible to the browser's link affordances, and a PPC manager comparing
   * several campaigns has to navigate back and forth instead of opening tabs.
   */
  rowHref?: (row: T) => string
  /**
   * Controlled sort. Supply all three to lift sort state out of this
   * component — the campaigns screen keeps it in the URL so Back restores it.
   * Omit them and the table manages its own sort as before.
   */
  sortCol?: number | null
  sortDir?: SortDir
  onSortChange?: (col: number | null, dir: SortDir) => void
  /**
   * Enables Excel-style column resizing, remembered under this key.
   * Omit it and the table behaves exactly as before.
   */
  resizeKey?: string
  pageSize?: number
  loading?: boolean
  emptyTitle?: string
  emptyDescription?: string
  className?: string
}

export function DataTable<T>({
  defaultSortCol,
  defaultSortDir,
  columns,
  rows,
  rowKey,
  onRowClick,
  rowHref,
  sortCol: sortColProp,
  sortDir: sortDirProp,
  onSortChange,
  resizeKey,
  pageSize = 25,
  loading = false,
  emptyTitle = 'No records found',
  emptyDescription,
  className = '',
}: DataTableProps<T>) {
  // Default sort matters: an operator opening a table should see the rows
  // that need attention, not whatever order the API happened to return.
  const [ownSortCol, setOwnSortCol] = useState<number | null>(defaultSortCol ?? null)
  const [ownSortDir, setOwnSortDir] = useState<SortDir>(defaultSortDir ?? 'asc')
  // Controlled when the parent passes a handler; otherwise self-managed.
  const controlled = onSortChange !== undefined
  const sortCol = controlled ? (sortColProp ?? null) : ownSortCol
  const sortDir = controlled ? (sortDirProp ?? 'asc') : ownSortDir
  const [page, setPage] = useState(1)
  // Declared before the early returns below: a hook after them would run on
  // some renders and not others, which is the crash this file has seen before.
  const cols = useColumnWidths(resizeKey ?? 'unused', columns.length)

  const sorted = useMemo(() => {
    if (sortCol === null || !columns[sortCol]?.sortValue) return rows
    const sv = columns[sortCol].sortValue!
    return [...rows].sort((a, b) => {
      const ra = sv(a)
      const rb = sv(b)

      // Money and metrics arrive from the API as numeric STRINGS ('8.97'),
      // so a plain < / > comparison sorts them alphabetically: "8.97" beats
      // "27.71" because '8' > '2'. Compare numerically whenever both sides
      // look like numbers, and fall back to text for real strings.
      const na = typeof ra === 'number' ? ra : (ra == null || ra === '' ? NaN : Number(ra))
      const nb = typeof rb === 'number' ? rb : (rb == null || rb === '' ? NaN : Number(rb))
      const bothNumeric = !Number.isNaN(na) && !Number.isNaN(nb)

      if (bothNumeric) {
        if (na < nb) return sortDir === 'asc' ? -1 : 1
        if (na > nb) return sortDir === 'asc' ? 1 : -1
        return 0
      }

      const va = ra ?? ''
      const vb = rb ?? ''
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
    const [nextCol, nextDir]: [number, SortDir] =
      sortCol === idx
        ? [idx, sortDir === 'asc' ? 'desc' : 'asc']
        : [idx, 'asc']
    if (controlled) {
      onSortChange!(nextCol, nextDir)
    } else {
      setOwnSortCol(nextCol)
      setOwnSortDir(nextDir)
    }
  }

  if (loading) return <LoadingState />
  if (!rows.length) return <EmptyState title={emptyTitle} description={emptyDescription} />

  return (
    <div className={`overflow-hidden ${className}`}>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm"
               style={resizeKey ? cols.tableStyle : undefined}>
          {resizeKey && cols.colGroup}
          <thead className="border-b border-hairline bg-surface-sunken" ref={resizeKey ? cols.theadRef : undefined}>
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  scope="col"
                  onClick={() => toggleSort(i)}
                  className={cn(
                    'group/th px-3 py-2 text-left text-xs font-medium text-ink-muted',
                    'whitespace-nowrap select-none',
                    col.sortValue && 'cursor-pointer hover:text-ink',
                    resizeKey && 'relative',
                    col.className,
                  )}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    {col.sortValue && (
                      sortCol === i ? (
                        sortDir === 'asc'
                          ? <ChevronUp size={13} strokeWidth={2.25} className="text-accent" aria-hidden />
                          : <ChevronDown size={13} strokeWidth={2.25} className="text-accent" aria-hidden />
                      ) : (
                        // Shown only on hover: eleven permanent double-chevrons
                        // is eleven pieces of chrome competing with the data.
                        <ChevronsUpDown
                          size={13} strokeWidth={2} aria-hidden
                          className="text-ink-faint opacity-0 transition-opacity group-hover/th:opacity-100"
                        />
                      )
                    )}
                  </span>
                  {/* Last column gets no handle: dragging it would widen the
                      table past its container with nothing to give back. */}
                  {resizeKey && i < columns.length - 1 && cols.handle(i)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline bg-surface">
            {paginated.map(row => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={cn(
                  'transition-colors duration-100 ease-out',
                  (onRowClick || rowHref) && 'cursor-pointer hover:bg-surface-hover',
                )}
              >
                {columns.map((col, i) => (
                  <td key={i}
                      className={cn('px-3 py-2 text-ink', resizeKey && 'truncate', col.className)}
                      title={resizeKey && typeof col.cell(row) === 'string'
                        ? String(col.cell(row)) : undefined}>
                    {i === 0 && rowHref ? (
                      // stopPropagation so the anchor does not also fire the
                      // row handler, which would navigate twice.
                      <Link
                        href={rowHref(row)}
                        onClick={e => e.stopPropagation()}
                        className="text-ink hover:text-accent hover:underline decoration-accent/40 underline-offset-2"
                      >
                        {col.cell(row)}
                      </Link>
                    ) : (
                      col.cell(row)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2 px-1">
        {resizeKey && cols.isCustomised ? (
          <button
            type="button"
            onClick={cols.reset}
            className="inline-flex items-center gap-1 text-xs text-ink-subtle hover:text-ink"
          >
            <Columns3 size={13} aria-hidden />
            Reset column widths
          </button>
        ) : <span />}
        <Pagination page={page} pageSize={pageSize} total={sorted.length} onChange={setPage} />
      </div>
    </div>
  )
}
