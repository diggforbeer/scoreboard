import { useEffect, useRef, useState } from 'react'

// Python WebSocket server (nhl_scoreboard.ws_server, run separately for now:
// `python -m nhl_scoreboard.ws_server`). See its own docstring for the
// message protocol and what's been ported over so far (#178).
const WS_URL = 'ws://localhost:8765/'

// Mirrors config.py's VALID_ROTATION_SCREENS -- hardcoded here rather than
// asked of the server, same "one section's worth of evidence isn't enough
// to generalise yet" call the backend docstring makes.
const ROTATION_SCREENS = ['countdown_preview', 'standings', 'clock', 'matchup'] as const
const ROTATION_MAX_ROWS = 8

type ConnectionState = 'connecting' | 'open' | 'closed'
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface AudioConfig {
  enabled: boolean
  device: string
  horn_dir: string
}

interface RotationRow {
  screen: string
  seconds: number
}

interface UpdateConfig {
  installed: string
  latest: string
  checked_at: string
  error: string
  reason: string
  available: boolean
  applicable: boolean
  last_apply: string
}

type ServerMessage =
  | { type: 'version'; value: string }
  | { type: 'config'; section: 'audio'; data: AudioConfig }
  | { type: 'config'; section: 'rotation'; data: RotationRow[] }
  | { type: 'config'; section: 'update'; data: UpdateConfig }
  | { type: 'saved'; section: string }
  | { type: 'error'; section?: string; message: string }
  | { type: 'checking' }
  | { type: 'applying' }
  | { type: 'rebooting' }

function connectionBadge(state: ConnectionState) {
  const variant = state === 'open' ? 'success' : state === 'connecting' ? 'secondary' : 'danger'
  return <span className={`badge text-bg-${variant}`}>{state}</span>
}

function saveFeedback(status: SaveStatus, error: string | null) {
  if (status === 'saved') return <span className="text-success">Saved.</span>
  if (status === 'error') return <span className="text-danger">{error}</span>
  return null
}

function App() {
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [version, setVersion] = useState<string | null>(null)

  const [audio, setAudio] = useState<AudioConfig | null>(null)
  const [audioSaveStatus, setAudioSaveStatus] = useState<SaveStatus>('idle')
  const [audioSaveError, setAudioSaveError] = useState<string | null>(null)

  const [rotation, setRotation] = useState<RotationRow[] | null>(null)
  const [rotationSaveStatus, setRotationSaveStatus] = useState<SaveStatus>('idle')
  const [rotationSaveError, setRotationSaveError] = useState<string | null>(null)

  const [update, setUpdate] = useState<UpdateConfig | null>(null)
  // 'checking'/'applying' cover the gap between clicking the button and the
  // watcher's broadcast landing once the real check/apply (out of process)
  // finishes -- this is the actual thing story 4 is for.
  const [updatePhase, setUpdatePhase] = useState<'idle' | 'checking' | 'applying'>('idle')
  const [rebooting, setRebooting] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const socket = new WebSocket(WS_URL)
    socketRef.current = socket

    socket.onopen = () => setConnection('open')
    socket.onclose = () => setConnection('closed')
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as ServerMessage
      switch (message.type) {
        case 'version':
          setVersion(message.value)
          break
        case 'config':
          if (message.section === 'audio') setAudio(message.data)
          else if (message.section === 'rotation') setRotation(message.data)
          else if (message.section === 'update') {
            setUpdate(message.data)
            setUpdatePhase('idle') // real data just arrived -- whatever was in flight is done
          }
          break
        case 'saved':
          if (message.section === 'audio') setAudioSaveStatus('saved')
          else if (message.section === 'rotation') setRotationSaveStatus('saved')
          break
        case 'error':
          if (message.section === 'audio') {
            setAudioSaveStatus('error')
            setAudioSaveError(message.message)
          } else if (message.section === 'rotation') {
            setRotationSaveStatus('error')
            setRotationSaveError(message.message)
          }
          break
        case 'checking':
          setUpdatePhase('checking')
          break
        case 'applying':
          setUpdatePhase('applying')
          break
        case 'rebooting':
          setRebooting(true)
          break
      }
    }

    return () => socket.close()
  }, [])

  function save(section: string, data: unknown) {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ type: 'save', section, data }))
  }

  function saveAudio(event: React.FormEvent) {
    event.preventDefault()
    if (!audio) return
    setAudioSaveStatus('saving')
    setAudioSaveError(null)
    save('audio', audio)
  }

  function saveRotation(event: React.FormEvent) {
    event.preventDefault()
    if (!rotation) return
    setRotationSaveStatus('saving')
    setRotationSaveError(null)
    save('rotation', rotation)
  }

  function updateRow(index: number, row: RotationRow) {
    if (!rotation) return
    setRotation(rotation.map((r, i) => (i === index ? row : r)))
  }

  function removeRow(index: number) {
    if (!rotation) return
    setRotation(rotation.filter((_, i) => i !== index))
  }

  function addRow() {
    if (!rotation || rotation.length >= ROTATION_MAX_ROWS) return
    setRotation([...rotation, { screen: ROTATION_SCREENS[0], seconds: 8 }])
  }

  function moveRow(index: number, delta: -1 | 1) {
    if (!rotation) return
    const target = index + delta
    if (target < 0 || target >= rotation.length) return
    const next = [...rotation]
    ;[next[index], next[target]] = [next[target], next[index]]
    setRotation(next)
  }

  function checkForUpdate() {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ type: 'update_check' }))
  }

  function applyUpdate() {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ type: 'update_apply' }))
  }

  function rebootBoard() {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ type: 'reboot' }))
  }

  return (
    <div className="container py-4" style={{ maxWidth: '40rem' }}>
      <header className="d-flex justify-content-between align-items-center mb-4">
        <h1 className="h3 mb-0">Hockey Scoreboard</h1>
        {connectionBadge(connection)}
      </header>

      <p className="text-body-secondary">
        Installed version: {version ?? 'waiting for server...'}
      </p>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Audio</h2>
          {audio ? (
            <form onSubmit={saveAudio}>
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="audio-enabled"
                  checked={audio.enabled}
                  onChange={(e) => setAudio({ ...audio, enabled: e.target.checked })}
                />
                <label className="form-check-label" htmlFor="audio-enabled">
                  Goal horn enabled
                </label>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="audio-device">
                  ALSA device (blank for default)
                </label>
                <input
                  className="form-control"
                  id="audio-device"
                  type="text"
                  value={audio.device}
                  onChange={(e) => setAudio({ ...audio, device: e.target.value })}
                />
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="audio-horn-dir">
                  Horn directory override (blank for default)
                </label>
                <input
                  className="form-control"
                  id="audio-horn-dir"
                  type="text"
                  value={audio.horn_dir}
                  onChange={(e) => setAudio({ ...audio, horn_dir: e.target.value })}
                />
              </div>
              <div className="d-flex align-items-center gap-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={audioSaveStatus === 'saving'}
                >
                  Save Audio
                </button>
                {saveFeedback(audioSaveStatus, audioSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-body">
          <h2 className="card-title h5">Idle rotation</h2>
          {rotation ? (
            <form onSubmit={saveRotation}>
              <p className="text-body-secondary small">
                Screens shown when the favourite is not live, in this order. Up to{' '}
                {ROTATION_MAX_ROWS} rows. Empty falls back to the built-in default
                (countdown/preview, standings, clock).
              </p>
              {rotation.map((row, i) => (
                <div className="d-flex align-items-center gap-2 mb-2" key={i}>
                  <select
                    className="form-select"
                    style={{ width: 'auto' }}
                    value={row.screen}
                    onChange={(e) => updateRow(i, { ...row, screen: e.target.value })}
                  >
                    {ROTATION_SCREENS.map((screen) => (
                      <option key={screen} value={screen}>
                        {screen}
                      </option>
                    ))}
                  </select>
                  <input
                    className="form-control"
                    style={{ width: '6rem' }}
                    type="number"
                    step="any"
                    min="0"
                    value={row.seconds}
                    onChange={(e) => updateRow(i, { ...row, seconds: Number(e.target.value) })}
                  />
                  <span className="text-body-secondary small">seconds</span>
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    onClick={() => moveRow(i, -1)}
                    disabled={i === 0}
                    aria-label="Move up"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    onClick={() => moveRow(i, 1)}
                    disabled={i === rotation.length - 1}
                    aria-label="Move down"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    onClick={() => removeRow(i)}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={addRow}
                  disabled={rotation.length >= ROTATION_MAX_ROWS}
                >
                  Add row
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={rotationSaveStatus === 'saving'}
                >
                  Save idle rotation
                </button>
                {saveFeedback(rotationSaveStatus, rotationSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mt-4">
        <div className="card-body">
          <h2 className="card-title h5">Software update</h2>
          {update ? (
            <>
              <p className="mb-1">Installed: {update.installed}</p>
              {update.latest && <p className="mb-1">Latest release: {update.latest}</p>}
              {update.checked_at && (
                <p className="text-body-secondary small mb-1">Last checked: {update.checked_at}</p>
              )}
              {update.error && <p className="text-danger mb-1">{update.error}</p>}
              {!update.error && update.reason && (
                <p className="text-body-secondary small mb-1">{update.reason}</p>
              )}
              {update.last_apply && (
                <p className="text-body-secondary small mb-1">Last install: {update.last_apply}</p>
              )}
              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={checkForUpdate}
                  disabled={updatePhase !== 'idle'}
                >
                  Check for updates now
                </button>
                {update.available && update.applicable && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={applyUpdate}
                    disabled={updatePhase !== 'idle'}
                  >
                    Install {update.latest}
                  </button>
                )}
                {updatePhase === 'checking' && (
                  <span className="text-body-secondary">Checking...</span>
                )}
                {updatePhase === 'applying' && (
                  <span className="text-body-secondary">
                    Installing. The board restarts and rolls back by itself if it doesn't come up.
                  </span>
                )}
              </div>
            </>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mt-4 mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Reboot</h2>
          <p className="text-body-secondary small">
            Reboots the whole board to apply any "applies after restart" change. This interrupts
            whatever is on screen right now, including a live game.
          </p>
          {rebooting ? (
            <p className="text-warning mb-0">Rebooting the board now...</p>
          ) : (
            <button type="button" className="btn btn-danger" onClick={rebootBoard}>
              Reboot board
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default App
