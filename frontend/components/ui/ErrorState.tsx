interface ErrorStateProps {
  error: string
  onRetry?: () => void
}
export function ErrorState({ error, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      <div className="rounded-full bg-red-100 p-3">
        <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
      </div>
      <div>
        <p className="text-sm font-medium text-gray-900">Something went wrong</p>
        <p className="text-sm text-red-600 mt-1">{error}</p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="btn-secondary mt-1">
          Try again
        </button>
      )}
    </div>
  )
}
