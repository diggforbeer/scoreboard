import { useEffect, useState } from 'react'
import './App.css'

// Story 1 of #178: prove the pipeline end to end -- React SPA connects to
// the Python WebSocket server (nhl_scoreboard.ws_server, run separately for
// now: `python -m nhl_scoreboard.ws_server`) and displays the one piece of
// data it sends on connect. No reconnect logic, no real styling, no other
// messages -- those are later stories' jobs.
const WS_URL = 'ws://localhost:8765/'

type ConnectionState = 'connecting' | 'open' | 'closed'

function App() {
  const [state, setState] = useState<ConnectionState>('connecting')
  const [version, setVersion] = useState<string | null>(null)

  useEffect(() => {
    const socket = new WebSocket(WS_URL)

    socket.onopen = () => setState('open')
    socket.onclose = () => setState('closed')
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as { version: string }
      setVersion(data.version)
    }

    return () => socket.close()
  }, [])

  return (
    <main>
      <h1>Hockey Scoreboard</h1>
      <p>WebSocket: {state}</p>
      <p>Installed version: {version ?? 'waiting for server...'}</p>
    </main>
  )
}

export default App
