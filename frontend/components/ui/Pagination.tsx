interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}
export function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (totalPages <= 1) return null
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, total)

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-hairline sm:px-6">
      <p className="text-sm text-ink-muted">
        Showing <span className="font-medium">{start}</span>–<span className="font-medium">{end}</span>{' '}
        of <span className="font-medium">{total}</span>
      </p>
      <div className="flex gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="btn-secondary px-2 py-1 text-xs disabled:opacity-40"
        >
          ‹ Prev
        </button>
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          let p: number
          if (totalPages <= 7) {
            p = i + 1
          } else if (page <= 4) {
            p = i + 1
          } else if (page >= totalPages - 3) {
            p = totalPages - 6 + i
          } else {
            p = page - 3 + i
          }
          return (
            <button
              key={p}
              onClick={() => onChange(p)}
              className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                p === page
                  ? 'bg-accent text-white'
                  : 'btn-secondary'
              }`}
            >
              {p}
            </button>
          )
        })}
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className="btn-secondary px-2 py-1 text-xs disabled:opacity-40"
        >
          Next ›
        </button>
      </div>
    </div>
  )
}
