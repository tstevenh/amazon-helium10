import { cn } from '@/lib/cn'

/**
 * The heading block at the top of a screen.
 *
 * text-xl, not text-2xl-bold. Every screen here is a work surface, and a 24px
 * bold title above a dense table competes with the data it introduces. The
 * subtitle carries the actual orientation, so it gets body contrast rather than
 * the decorative gray it had.
 */
export function PageHeader({
  title, subtitle, actions, className,
}: {
  title: string
  subtitle?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('mb-5 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink text-balance">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-0.5 max-w-[75ch] text-sm text-ink-muted">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
