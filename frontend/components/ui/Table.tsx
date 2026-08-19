import * as React from 'react'
import { cn } from '@/lib/cn'

/**
 * Table primitives.
 *
 * Rows are separated by a hairline and nothing else: no zebra striping, no
 * vertical rules. At 25 rows of nine numeric columns, striping fights the
 * numbers for attention and column rules turn the table into a grid of cells
 * rather than a set of comparable values.
 *
 * The header is sunken rather than bordered-and-bold, so it reads as chrome and
 * the data reads as content.
 */
export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full text-sm', className)} {...props} />
}

export function THead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn('border-b border-hairline bg-surface-sunken', className)}
      {...props}
    />
  )
}

export function TBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('divide-y divide-hairline', className)} {...props} />
}

export function TR({
  className, interactive, selected, ...props
}: React.HTMLAttributes<HTMLTableRowElement> & { interactive?: boolean; selected?: boolean }) {
  return (
    <tr
      data-selected={selected || undefined}
      className={cn(
        'transition-colors duration-100 ease-out',
        interactive && 'cursor-pointer hover:bg-surface-hover',
        // Selection is a tint, not the accent at full strength — twenty selected
        // rows should still be readable as rows.
        selected && 'bg-accent-weak hover:bg-accent-weak',
        className,
      )}
      {...props}
    />
  )
}

export function TH({
  className, numeric, sortable, ...props
}: React.ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean; sortable?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        'px-3 py-2 text-xs font-medium text-ink-muted whitespace-nowrap select-none',
        numeric ? 'text-right' : 'text-left',
        sortable && 'cursor-pointer hover:text-ink',
        className,
      )}
      {...props}
    />
  )
}

export function TD({
  className, numeric, ...props
}: React.TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      className={cn(
        'px-3 py-2 text-ink',
        numeric ? 'text-right tabular' : 'text-left',
        className,
      )}
      {...props}
    />
  )
}

/** Horizontal scroll container. Wide tables scroll here, never the page body. */
export function TableScroll({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('w-full overflow-x-auto', className)} {...props} />
}
