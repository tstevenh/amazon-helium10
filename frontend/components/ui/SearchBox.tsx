interface SearchBoxProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}
export function SearchBox({ value, onChange, placeholder = 'Search…', className = '' }: SearchBoxProps) {
  return (
    <div className={`relative ${className}`}>
      <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-subtle pointer-events-none"
        fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z" />
      </svg>
      <input
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="input pl-8 w-full"
      />
    </div>
  )
}
