# DESIGN.md

The visual system for PPC OS. Strategy and users live in [PRODUCT.md](PRODUCT.md).

## Theme

Light only. The scene that decides it: a bright office, mid-afternoon, hour three
of reading dense numeric tables. One palette also means one place for a contrast
bug to hide instead of two.

Colour strategy: **Restrained** — tinted neutrals plus one accent, which is the
floor for product surfaces.

## Colour

Tokens live in `frontend/app/globals.css` as bare OKLCH **channels** (`L C H`),
not finished colours, so Tailwind can inject an alpha for `bg-accent/10` and
`ring-accent/20`. An opaque `var(--accent)` cannot take an opacity modifier —
that is how the first version failed to compile. Raw CSS wraps them:
`oklch(var(--accent))`. `tailwind.config.js` only names them; no value is defined
in two places.

OKLCH because a lightness ramp in OKLCH is perceptually even. Hex ramps sag in
the greens and spike in the blues, which is why hand-picked greys never line up.

### Surfaces

| Token | Use |
|---|---|
| `canvas` | app background |
| `surface` | cards, tables, panels |
| `surface-sunken` | table headers, inset areas |
| `surface-hover` | row and control hover |
| `sidebar` | the second neutral layer |

Neutrals carry 0.004–0.008 chroma toward the accent hue (265) so the surface
belongs to the accent. Explicitly **not** warm: the cream / sand / paper
near-white is the current default reflex and wrong for a data surface besides.

### Ink

Measured against `surface`:

| Token | Ratio | Use |
|---|---|---|
| `ink` | 16.1:1 | body, headings, data |
| `ink-muted` | 7.4:1 | labels, secondary copy |
| `ink-subtle` | 4.6:1 | hints, placeholders — the AA floor |
| `ink-faint` | 3.1:1 | **never body.** ≥18px or decorative rules only |

That last row is the discipline that keeps this readable at hour three. Light
grey "for elegance" is the most common way a data UI becomes unusable.

### Accent and status

`accent` is indigo (`0.520 0.176 268`), not Tailwind's blue-600, because blue
already means *info* in the status vocabulary and green / amber / red are spoken
for. Used for primary actions, current selection and focus. Never decoration.

Status is `ok` / `warn` / `danger` / `info`, each with a `-tint` for backgrounds.
**Status is never colour alone** — every badge and notice carries the word and an
icon, because this app gets screenshotted into WhatsApp threads and read by people
who may not distinguish red from green.

## Typography

One family, the system sans. Fixed rem scale, not `clamp()`: users view at
consistent DPI and a fluid heading that shrinks inside a panel looks worse.

Ratio ≈1.15 (`2xs` 11px → `2xl` 24px). This surface has many type roles, so wide
contrast between steps reads as noise. Page titles are `text-xl font-semibold`;
nothing is `font-bold`.

`font-variant-numeric: tabular-nums` on all table cells and `.tabular`. Every
number here sits in a column that gets compared with the one above it.

## Components

`frontend/components/ui/`. One vocabulary; if Save looks different on two screens,
one is wrong.

| Component | Notes |
|---|---|
| `Button` | 5 variants × 5 sizes, all seven states. Spinner keeps the label so width does not shift mid-click. |
| `Badge` | Tinted, never saturated fill — twenty solid pills is a table nobody can scan. |
| `Notice` | 4 tones, lucide icon, optional dismiss. Replaced 20 hand-rolled strips. |
| `Card` + parts | Deliberately thin. Cards are the lazy answer to hierarchy; **nested cards are always wrong.** |
| `Input` / `Select` / `Textarea` / `Label` / `FormField` | Native `<select>`, not Radix: the pickers hold hundreds of options and get type-ahead and the mobile wheel free. |
| `Table` parts | Hairline row rules only. No zebra, no column rules — at 25 rows × 9 numeric columns both fight the data. |
| `StatBar` | One strip, not a grid of stat cards. |
| `SegmentedControl` | Radio semantics, for one setting with N positions. |
| `Drawer` | Radix Dialog: focus trap, restoration, scroll lock. |
| `RowMenu` / `MenuItem` | Radix DropdownMenu in a portal, so a table's `overflow-x-auto` cannot clip it. |
| `Skeleton` / `TableSkeleton` | Skeletons, not centred spinners. |

Icons: **lucide only, 16px, stroke 1.75.** No emoji anywhere — there were 48, and
they render differently per OS, sit off the baseline and cannot be styled.

## Layout

Sticky light header (h-14) + sticky sidebar (w-52) + unconstrained main column.
No max-width cap on content: these tables run to 15 numeric columns and a centred
1152px column forced them to scroll sideways while empty space sat beside them.

Wide tables scroll inside **one** `overflow-x-auto` container. Never two nested —
the outer clips the inner. The page body must never scroll sideways.

Semantic z-scale: `dropdown` → `sticky` → `overlay` → `modal` → `toast` →
`tooltip`. Never a raw 999.

## Motion

150–250ms, `ease-out` (quart). Motion conveys state only: hover, focus, panel
entry, menu open. No page-load choreography — users load into a task.

`prefers-reduced-motion: reduce` is honoured globally in `globals.css`, not
per-component.

## Bans, specific to this codebase

- Raw Tailwind palette classes (`bg-gray-200`, `text-blue-600`). Nothing matches
  `(bg|text|border|divide|ring)-(gray|blue|green|…)-\d00` today; keep it that way.
- Emoji in UI.
- Stat-card grids. Use `StatBar`.
- Nested cards, and cards around tables.
- More than one primary action per row. Use `RowMenu`.
- `ink-faint` on body copy.
- Two names for one screen: the nav label and the page title must match.
