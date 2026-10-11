import { useState } from 'react'

// Autosave for one admin-page section (#273). Every save goes live on the
// board as soon as the server writes it (the app hot-reloads
// scoreboard.toml), so typed fields wait for a pause or a blur rather than
// saving per keystroke: a half-typed value would briefly apply, or fail
// validation and flash an error, and the file sits on the SD card's boot
// partition. Clicks (checkboxes, selects, row buttons) save at once.

/** How long a typed field waits after the last keystroke before saving. */
export const TYPING_DELAY_MS = 1000
/** How long "Undo" stays offered after a save lands. */
export const UNDO_WINDOW_MS = 10000
/** How long "Reverted" stays up after an Undo lands. */
const REVERTED_SHOWN_MS = 3000

export type AutosaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'reverted' | 'error'

// Stable across renders: the WebSocket's onmessage closure is created once
// and calls these, so they can't close over render-time state.
export interface AutosaveHandlers<T> {
  /** A local edit. ``delayMs`` 0 saves now; otherwise it waits for a pause. */
  edit(value: T, delayMs?: number): void
  /** Save any pending edit now (a blur, or Enter in the form). */
  flush(): void
  /** Re-save the values from before the last save. */
  undo(): void
  /** The section's config, on connect or echoed after a save. */
  receiveConfig(value: T): void
  receiveSaved(): void
  receiveError(message: string): void
  /** The socket dropped: unacknowledged saves count as unsent again. */
  connectionLost(): void
  /** The socket is back: send anything that never reached the server. */
  retryUnsent(): void
}

export interface AutosaveState<T> {
  value: T | null
  /** Back to ``idle`` once the Undo window (or "Reverted") has passed. */
  status: AutosaveStatus
  error: string | null
  canUndo: boolean
  /** ``Date.now()`` of the last local edit, so the page can show the newest. */
  changedAt: number
}

interface InFlight<T> {
  value: T
  undo: boolean
}

/**
 * ``[state, handlers]`` for one section. ``handlers`` keeps one identity for
 * the page's lifetime, so an effect can list it without re-running.
 */
export function useAutosave<T>(
  send: (value: T) => boolean,
  notConnected: string,
): [AutosaveState<T>, AutosaveHandlers<T>] {
  const [value, setValue] = useState<T | null>(null)
  const [status, setStatus] = useState<AutosaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [canUndo, setCanUndo] = useState(false)
  const [changedAt, setChangedAt] = useState(0)
  const [handlers] = useState<AutosaveHandlers<T>>(() => {
    let current: T | null = null
    // What the server last confirmed holding.
    let confirmed: T | null = null
    // Edited locally, not yet sent.
    let dirty = false
    // Sent, waiting for "saved"/"error"; the server answers in order.
    let inFlight: InFlight<T>[] = []
    // What Undo goes back to: the confirmed value when this burst of edits
    // began, so it reverts the whole burst, not just its last keystroke.
    let burstBase: T | null = null
    let undoTarget: T | null = null
    let nextIsUndo = false
    let saveTimer: ReturnType<typeof setTimeout> | undefined
    let fadeTimer: ReturnType<typeof setTimeout> | undefined

    const dropUndo = () => {
      clearTimeout(fadeTimer)
      undoTarget = null
      setCanUndo(false)
    }

    // Leaves ``shown`` up for ``ms``, then goes quiet unless something newer
    // replaced it in the meantime.
    const fadeAfter = (shown: AutosaveStatus, ms: number) => {
      clearTimeout(fadeTimer)
      fadeTimer = setTimeout(() => {
        undoTarget = null
        setCanUndo(false)
        setStatus((now) => (now === shown ? 'idle' : now))
      }, ms)
    }

    const flush = () => {
      clearTimeout(saveTimer)
      if (!dirty || current === null) return
      if (!send(current)) {
        setStatus('error')
        setError(notConnected)
        return // still dirty: retryUnsent() sends it after a reconnect
      }
      dirty = false
      inFlight.push({ value: current, undo: nextIsUndo })
      nextIsUndo = false
      setStatus('saving')
      setError(null)
    }

    const edit = (next: T, delayMs = 0) => {
      if (!dirty && inFlight.length === 0) burstBase = confirmed
      current = next
      dirty = true
      setValue(next)
      setChangedAt(Date.now())
      setStatus('pending')
      dropUndo()
      clearTimeout(saveTimer)
      if (delayMs <= 0) flush()
      else saveTimer = setTimeout(flush, delayMs)
    }

    return {
      edit,
      flush,
      undo() {
        if (undoTarget === null) return
        const target = undoTarget
        nextIsUndo = true
        edit(target)
      },
      receiveConfig(next) {
        // A newer local edit is still on its way; this echo would clobber it.
        if (dirty || inFlight.length > 0) return
        current = next
        confirmed = next
        setValue(next)
      },
      receiveSaved() {
        const done = inFlight.shift()
        if (!done) return
        confirmed = done.value
        if (dirty || inFlight.length > 0) return // more of this burst to come
        if (done.undo) {
          dropUndo()
          setStatus('reverted')
          fadeAfter('reverted', REVERTED_SHOWN_MS)
          return
        }
        setStatus('saved')
        undoTarget = burstBase
        setCanUndo(undoTarget !== null)
        fadeAfter('saved', UNDO_WINDOW_MS)
      },
      receiveError(message) {
        inFlight.shift()
        setStatus('error')
        setError(message)
        dropUndo()
      },
      connectionLost() {
        if (inFlight.length > 0) dirty = true
        inFlight = []
      },
      retryUnsent() {
        if (dirty) flush()
      },
    }
  })

  return [{ value, status, error, canUndo, changedAt }, handlers]
}
