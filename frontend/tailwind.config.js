/** @type {import('tailwindcss').Config} */
//
// Tokens live in app/globals.css as CSS variables; this file only teaches
// Tailwind their names. Two sources of truth for a colour is how a palette
// drifts, so nothing here defines a value.
//
// The old config was `theme: { extend: {} }`, which meant every screen reached
// for raw `gray-200` / `blue-600`. That is why the interface had no palette to
// speak of — there was nothing to reach for.
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './context/**/*.{js,ts,jsx,tsx}',
    './hooks/**/*.{js,ts,jsx,tsx}',
    './lib/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        canvas:  'oklch(var(--canvas) / <alpha-value>)',
        surface: {
          DEFAULT: 'oklch(var(--surface) / <alpha-value>)',
          sunken:  'oklch(var(--surface-sunken) / <alpha-value>)',
          hover:   'oklch(var(--surface-hover) / <alpha-value>)',
        },
        sidebar: 'oklch(var(--sidebar) / <alpha-value>)',
        ink: {
          DEFAULT: 'oklch(var(--ink) / <alpha-value>)',
          muted:   'oklch(var(--ink-muted) / <alpha-value>)',
          subtle:  'oklch(var(--ink-subtle) / <alpha-value>)',
          faint:   'oklch(var(--ink-faint) / <alpha-value>)',
        },
        hairline: 'oklch(var(--hairline) / <alpha-value>)',
        line: {
          DEFAULT: 'oklch(var(--border) / <alpha-value>)',
          strong:  'oklch(var(--border-strong) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'oklch(var(--accent) / <alpha-value>)',
          hover:   'oklch(var(--accent-hover) / <alpha-value>)',
          ink:     'oklch(var(--accent-ink) / <alpha-value>)',
          weak:    'oklch(var(--accent-weak) / <alpha-value>)',
          edge:    'oklch(var(--accent-edge) / <alpha-value>)',
        },
        ok:     { DEFAULT: 'oklch(var(--ok) / <alpha-value>)',     tint: 'oklch(var(--ok-tint) / <alpha-value>)' },
        warn:   { DEFAULT: 'oklch(var(--warn) / <alpha-value>)',   tint: 'oklch(var(--warn-tint) / <alpha-value>)' },
        danger: { DEFAULT: 'oklch(var(--danger) / <alpha-value>)', tint: 'oklch(var(--danger-tint) / <alpha-value>)',
                  hover: 'oklch(var(--danger-hover) / <alpha-value>)' },
        info:   { DEFAULT: 'oklch(var(--info) / <alpha-value>)',   tint: 'oklch(var(--info-tint) / <alpha-value>)' },
      },
      // Radius, shadow and z-index are NOT colours, so they keep the plain
      // var() form; wrapping them in oklch() would be nonsense.
      borderRadius: {
        DEFAULT: 'var(--radius)',
        sm: 'calc(var(--radius) - 2px)',
        md: 'var(--radius)',
        lg: 'calc(var(--radius) + 2px)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
      },
      zIndex: {
        dropdown: 'var(--z-dropdown)',
        sticky:   'var(--z-sticky)',
        overlay:  'var(--z-overlay)',
        modal:    'var(--z-modal)',
        toast:    'var(--z-toast)',
        tooltip:  'var(--z-tooltip)',
      },
      fontSize: {
        // Fixed rem, not clamp. Product UI is viewed at consistent DPI, and a
        // fluid heading that shrinks inside a panel looks worse, not better.
        // Ratio ~1.15 — this surface has many type roles, so wide contrast
        // between steps would read as noise.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        xs:    ['0.75rem',   { lineHeight: '1.125rem' }],
        sm:    ['0.8125rem', { lineHeight: '1.25rem' }],
        base:  ['0.875rem',  { lineHeight: '1.375rem' }],
        md:    ['0.9375rem', { lineHeight: '1.5rem' }],
        lg:    ['1.0625rem', { lineHeight: '1.625rem' }],
        xl:    ['1.25rem',   { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem',    { lineHeight: '2rem' }],
      },
      transitionTimingFunction: {
        // ease-out-quart. Motion here only ever conveys state, so it should
        // arrive quickly and settle — no bounce, no elastic.
        out: 'cubic-bezier(0.25, 1, 0.5, 1)',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
