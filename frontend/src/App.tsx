import { useEffect, useRef, useState } from 'react'
import './App.css'

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
    <main>
      <h1>Hockey Scoreboard</h1>
      <p>WebSocket: {connection}</p>
      <p>Installed version: {version ?? 'waiting for server...'}</p>

      <section>
        <h2>Audio</h2>
        {audio ? (
          <form onSubmit={saveAudio}>
            <label>
              <input
                type="checkbox"
                checked={audio.enabled}
                onChange={(e) => setAudio({ ...audio, enabled: e.target.checked })}
              />{' '}
              Goal horn enabled
            </label>
            <div>
              <label>
                ALSA device (blank for default)
                <br />
                <input
                  type="text"
                  value={audio.device}
                  onChange={(e) => setAudio({ ...audio, device: e.target.value })}
                />
              </label>
            </div>
            <div>
              <label>
                Horn directory override (blank for default)
                <br />
                <input
                  type="text"
                  value={audio.horn_dir}
                  onChange={(e) => setAudio({ ...audio, horn_dir: e.target.value })}
                />
              </label>
            </div>
            <button type="submit" disabled={saveStatus === 'saving'}>
              Save Audio
            </button>
            {saveStatus === 'saved' && <span> Saved.</span>}
            {saveStatus === 'error' && <span style={{ color: 'crimson' }}> {saveError}</span>}
          </form>
        ) : (
          <p>waiting for server...</p>
        )}
      </section>
    </main>
  )
}

export default App
