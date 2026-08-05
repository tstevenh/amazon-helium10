interface FilterOption {
  label: string
  value: string
}

export interface FilterConfig {
  key: string
  label: string
  /** Current selected value */
  value: string
  /** Called with the new value when selection changes */
  onChange: (value: string) => void
  options: FilterOption[]
}

interface FilterBarProps {
  filters?: FilterConfig[]
}

export function FilterBar({ filters = [] }: FilterBarProps) {
  if (!filters.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {filters.map(f => (
        <div key={f.key}>
          <select
            value={f.value ?? ''}
            onChange={e => f.onChange(e.target.value)}
            className="input py-1.5 text-sm"
            aria-label={f.label}
          >
            {f.options.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}
