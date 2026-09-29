import { useEffect, useRef, useState } from 'react'

// Python WebSocket server (nhl_scoreboard.ws_server, run separately for now:
// `python -m nhl_scoreboard.ws_server`). See its own docstring for the
// message protocol and what's been ported over so far (#178).
const WS_URL = 'ws://localhost:8765/'

type ConnectionState = 'connecting' | 'open' | 'closed'

interface AudioConfig {
  enabled: boolean
  device: string
  horn_dir: string
}

type ServerMessage =
  | { type: 'version'; value: string }
  | { type: 'config'; section: 'audio'; data: AudioConfig }
  | { type: 'saved'; section: string }
  | { type: 'error'; section?: string; message: string }

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

function connectionBadge(state: ConnectionState) {
  const variant = state === 'open' ? 'success' : state === 'connecting' ? 'secondary' : 'danger'
  return <span className={`badge text-bg-${variant}`}>{state}</span>
}

function App() {
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [version, setVersion] = useState<string | null>(null)
  const [audio, setAudio] = useState<AudioConfig | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
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
          break
        case 'saved':
          setSaveStatus('saved')
          break
        case 'error':
          setSaveStatus('error')
          setSaveError(message.message)
          break
      }
    }

    return () => socket.close()
  }, [])

  function saveAudio(event: React.FormEvent) {
    event.preventDefault()
    if (!audio || socketRef.current?.readyState !== WebSocket.OPEN) return
    setSaveStatus('saving')
    setSaveError(null)
    socketRef.current.send(JSON.stringify({ type: 'save', section: 'audio', data: audio }))
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

      <div className="card">
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
                <button type="submit" className="btn btn-primary" disabled={saveStatus === 'saving'}>
                  Save Audio
                </button>
                {saveStatus === 'saved' && <span className="text-success">Saved.</span>}
                {saveStatus === 'error' && <span className="text-danger">{saveError}</span>}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default App
