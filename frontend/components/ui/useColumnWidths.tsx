'use client'
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Excel-style column resizing, with the widths remembered per table.
 *
 * Two decisions worth knowing:
 *
 * Widths are measured from the browser's own layout on first render rather than
 * guessed. A table that jumped to arbitrary widths the moment resizing was
 * added would be a worse table than the one it replaced.
 *
 * They persist in localStorage under `storageKey`. A width that reset on every
 * navigation would be pointless — the whole reason to widen a keyword column is
 * that you are about to read a lot of keywords, across several visits. It is
 * localStorage rather than the URL deliberately: this is a per-person display
 * preference, and putting it in the URL would push it onto whoever a link is
 * shared with, on top of bloating every link.
 */
const MIN_WIDTH = 56

export function useColumnWidths(storageKey: string, columnCount: number) {
  const [widths, setWidths] = useState<number[] | null>(null)
  const theadRef = useRef<HTMLTableSectionElement | null>(null)
  const drag = useRef<{ index: number; startX: number; startWidth: number } | null>(null)

  // Restore before first paint where possible, so there is no visible reflow.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`colw:${storageKey}`)
      if (!raw) return
      const saved = JSON.parse(raw)
      // Column sets change as features are added; a stale array would map
      // widths onto the wrong columns, so it is discarded rather than patched.
      if (Array.isArray(saved) && saved.length === columnCount) setWidths(saved)
    } catch {
      /* corrupt or unavailable storage must never break the table */
    }
  }, [storageKey, columnCount])

  /** Adopt whatever the browser laid out, so dragging starts from reality. */
  const measure = useCallback(() => {
    const row = theadRef.current?.querySelector('tr')
    if (!row) return null
    const cells = Array.from(row.children) as HTMLElement[]
    if (cells.length !== columnCount) return null
    return cells.map(c => Math.max(MIN_WIDTH, Math.round(c.getBoundingClientRect().width)))
  }, [columnCount])

  const persist = useCallback((next: number[]) => {
    setWidths(next)
    try {
      localStorage.setItem(`colw:${storageKey}`, JSON.stringify(next))
    } catch { /* private mode, quota — resizing still works for this session */ }
  }, [storageKey])

  const onHandleDown = useCallback((index: number) => (e: React.PointerEvent) => {
    // The handle sits inside a sortable header. Without this, every resize
    // would also toggle the sort — which is what made an earlier attempt
    // unusable.
    e.preventDefault()
    e.stopPropagation()
    const base = widths ?? measure()
    if (!base) return
    drag.current = { index, startX: e.clientX, startWidth: base[index] }
    if (!widths) setWidths(base)

    const move = (ev: PointerEvent) => {
      const d = drag.current
      if (!d) return
      const next = [...(base as number[])]
      next[d.index] = Math.max(MIN_WIDTH, d.startWidth + (ev.clientX - d.startX))
      setWidths(next)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      // Persist once, on release — writing on every pointermove would hammer
      // localStorage synchronously and stutter the drag.
      setWidths(cur => { if (cur) persist(cur); return cur })
      drag.current = null
    }
    document.body.style.cursor = 'col-resize'
    // Otherwise the drag selects the header text of every column it crosses.
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }, [widths, measure, persist])

  const reset = useCallback(() => {
    setWidths(null)
    try { localStorage.removeItem(`colw:${storageKey}`) } catch { /* ignore */ }
  }, [storageKey])

  /**
   * A drag handle for column `index`. Render it inside that column's <th>,
   * which must be positioned (the wrapper below adds `relative`).
   */
  const handle = (index: number) => (
    <span
      onPointerDown={onHandleDown(index)}
      onClick={e => e.stopPropagation()}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize column"
      title="Drag to resize"
      className="absolute top-0 right-0 h-full w-2 cursor-col-resize select-none
                 hover:bg-blue-300/60 active:bg-blue-400/70"
    />
  )

  /** Spread onto each <th> so the handle can anchor to its right edge. */
  const thProps = { className: 'relative' }

  const colGroup = widths ? (
    <colgroup>
      {widths.map((w, i) => <col key={i} style={{ width: `${w}px` }} />)}
    </colgroup>
  ) : null

  return {
    theadRef,
    colGroup,
    handle,
    thProps,
    reset,
    /** Fixed layout only once widths exist, so the natural layout is the start. */
    tableStyle: widths ? ({ tableLayout: 'fixed' as const, width: '100%' }) : undefined,
    isCustomised: widths !== null,
  }
}
