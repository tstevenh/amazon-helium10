import { cn } from '@/lib/cn'

/**
 * Loading placeholder.
 *
 * Skeletons rather than a centred spinner: a spinner tells you to wait, a
 * skeleton tells you what is arriving and stops the layout jumping when it does.
 * The pulse is opacity-only so it survives prefers-reduced-motion sensibly.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn('animate-pulse rounded bg-surface-sunken', className)}
      {...props}
    />
  )
}

/** Table-shaped skeleton, so the page does not reflow when rows land. */
export function TableSkeleton({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="p-3 space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton
              key={c}
              className={cn('h-4', c === 0 ? 'flex-[2]' : 'flex-1')}
              // Slight offset per row so it reads as content loading rather
              // than one block flashing.
              style={{ animationDelay: `${(r * cols + c) * 18}ms` }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
