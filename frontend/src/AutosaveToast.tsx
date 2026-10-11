import type { AutosaveState } from './autosave'

export interface AutosaveSection {
  label: string
  state: AutosaveState<unknown>
  onUndo: () => void
}

/**
 * One bar pinned to the bottom of the screen for whichever section was
 * edited last (#273): "Scoreboard saved ✓ · Undo". Pinned rather than at
 * the foot of each section, which on a phone sat a long scroll away from
 * the field you'd just changed.
 */
export function AutosaveToast({ sections }: { sections: AutosaveSection[] }) {
  const active = sections
    .filter((section) => section.state.status !== 'idle')
    .sort((a, b) => b.state.changedAt - a.state.changedAt)[0]
  if (!active) return null
  const { label, state, onUndo } = active

  let body
  switch (state.status) {
    case 'pending':
    case 'saving':
      body = <span className="text-body-secondary">Saving {label}…</span>
      break
    case 'saved':
      body = (
        <span className="text-success">
          {label} saved ✓
          {state.canUndo && (
            <>
              {' · '}
              <button
                type="button"
                className="btn btn-link btn-sm p-0 align-baseline"
                onClick={onUndo}
              >
                Undo
              </button>
            </>
          )}
        </span>
      )
      break
    case 'reverted':
      body = <span className="text-success">{label} reverted ✓</span>
      break
    default:
      body = (
        <span className="text-danger">
          {label}: {state.error}
        </span>
      )
  }

  return (
    <div
      className={[
        'position-fixed bottom-0 start-50 translate-middle-x mb-3',
        'px-3 py-2 rounded shadow bg-body-tertiary border text-nowrap',
      ].join(' ')}
      style={{ zIndex: 1080, maxWidth: 'calc(100vw - 2rem)' }}
      role="status"
      aria-live="polite"
    >
      {body}
    </div>
  )
}
