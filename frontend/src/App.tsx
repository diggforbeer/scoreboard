import { useEffect, useRef, useState } from 'react'

// Python admin server (nhl_scoreboard.admin_server) -- one port serves both
// this page's own production build and its WebSocket (#178 story 10); in
// local dev, run it separately alongside the Vite dev server:
// `python -m nhl_scoreboard.admin_server`. See its own docstring for the
// message protocol and what's been ported over so far.
//
// A real, shipped bug (found live against the actual board, not caught by
// any local verification): this used to be hardcoded to
// 'ws://localhost:8765/' unconditionally. That's only ever correct when
// the browser and the server happen to be the same machine -- true for
// every local-dev check this project's own testing did (Vite on 5173,
// admin_server.py on 8765, both on localhost), and also true, by pure
// coincidence, whenever *this dev machine's own* leftover local
// admin_server.py instance is still running -- which is exactly how this
// slipped through every "verified against the real board" check: the
// browser silently connected to that stray localhost:8765 process
// instead of the board's own server, showing whatever *that* process's
// state happened to be (whatever team was last set in local testing, an
// empty "no live app" snapshot from dev mode) rather than erroring
// loudly. On a real device, opened from a real remote browser with
// nothing coincidentally listening on that port, this would just fail to
// connect outright. In production (the built page served by
// admin_server.py itself, story 10's whole "one port serves both" point)
// the WebSocket must be derived from wherever the page was actually
// loaded from. import.meta.env.DEV (true only under `npm run dev`) keeps
// local dev's own two-port split (Vite on 5173, admin_server.py fixed at
// 8765) working exactly as before.
const WS_URL = import.meta.env.DEV
  ? 'ws://localhost:8765/'
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/`

// Mirrors config.py's VALID_ROTATION_SCREENS -- hardcoded here rather than
// asked of the server, same "one section's worth of evidence isn't enough
// to generalise yet" call the backend docstring makes.
const ROTATION_SCREENS = ['countdown_preview', 'standings', 'clock', 'matchup'] as const
const ROTATION_MAX_ROWS = 8
// Mirrors admin_server.py's HORN_MAX_BYTES; the server re-checks.
const HORN_MAX_BYTES = 2 * 1024 * 1024

// Abbreviations match display/teams.py's TEAM_COLORS keys exactly -- the
// only place this project otherwise enumerates every team. Full names are
// for this dropdown's own readability; the value saved is still just the
// 3-letter abbreviation config.py has always expected. Sorted by name.
const NHL_TEAMS = [
  ['ANA', 'Anaheim Ducks'],
  ['BOS', 'Boston Bruins'],
  ['BUF', 'Buffalo Sabres'],
  ['CGY', 'Calgary Flames'],
  ['CAR', 'Carolina Hurricanes'],
  ['CHI', 'Chicago Blackhawks'],
  ['COL', 'Colorado Avalanche'],
  ['CBJ', 'Columbus Blue Jackets'],
  ['DAL', 'Dallas Stars'],
  ['DET', 'Detroit Red Wings'],
  ['EDM', 'Edmonton Oilers'],
  ['FLA', 'Florida Panthers'],
  ['LAK', 'Los Angeles Kings'],
  ['MIN', 'Minnesota Wild'],
  ['MTL', 'Montreal Canadiens'],
  ['NSH', 'Nashville Predators'],
  ['NJD', 'New Jersey Devils'],
  ['NYI', 'New York Islanders'],
  ['NYR', 'New York Rangers'],
  ['OTT', 'Ottawa Senators'],
  ['PHI', 'Philadelphia Flyers'],
  ['PIT', 'Pittsburgh Penguins'],
  ['SJS', 'San Jose Sharks'],
  ['SEA', 'Seattle Kraken'],
  ['STL', 'St. Louis Blues'],
  ['TBL', 'Tampa Bay Lightning'],
  ['TOR', 'Toronto Maple Leafs'],
  ['UTA', 'Utah Mammoth'],
  ['VAN', 'Vancouver Canucks'],
  ['VGK', 'Vegas Golden Knights'],
  ['WSH', 'Washington Capitals'],
  ['WPG', 'Winnipeg Jets'],
] as const

// Common US timezones only, per the owner's request -- not every IANA zone.
// scoreboard.timezone accepts any IANA name, so a config already set to
// something outside this list is added as an extra option rather than
// silently dropped (see the Scoreboard form below).
const US_TIMEZONES = [
  ['America/New_York', 'Eastern (America/New_York)'],
  ['America/Chicago', 'Central (America/Chicago)'],
  ['America/Denver', 'Mountain (America/Denver)'],
  ['America/Phoenix', 'Mountain, no DST (America/Phoenix)'],
  ['America/Los_Angeles', 'Pacific (America/Los_Angeles)'],
  ['America/Anchorage', 'Alaska (America/Anchorage)'],
  ['Pacific/Honolulu', 'Hawaii (Pacific/Honolulu)'],
] as const

type ConnectionState = 'connecting' | 'open' | 'closed'
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface AudioConfig {
  enabled: boolean
  device: string
  horn_dir: string
  volume: number
}

interface ScoreboardConfig {
  favourite_team: string
  timezone: string
  rotate_seconds: number
  poll_seconds: number
  live_poll_seconds: number
  show_clock_when_idle: boolean
  prefer_favourite: boolean
  show_logos: boolean
  logo_variant: string
  goal_flash_seconds: number
  goal_detail_seconds: number
  three_stars_seconds: number
  countdown_hours: number
  final_hold_minutes: number
  show_standings: boolean
  show_clock_between_games: boolean
}

interface StatusConfig {
  enabled: boolean
  port: number
}

// Mirrors PanelConfig (config.py) except pitch_mm -- informational only,
// the driver never reads it, so status_server.py's own form has never
// exposed it either. Still typed here since the server's payload
// (dataclasses.asdict of the whole dataclass) includes it regardless;
// savePanel strips it back out before sending.
interface PanelConfig {
  rows: number
  cols: number
  chain_length: number
  parallel: number
  pitch_mm: number
  hardware_mapping: string
  rgb_sequence: string
  gpio_slowdown: number
  pwm_bits: number
  pwm_lsb_nanoseconds: number
  brightness: number
  limit_refresh_rate_hz: number
  disable_hardware_pulsing: boolean
  pixel_mapper: string
  auto_brightness: boolean
  min_brightness: number
  max_brightness: number
  brightness_poll_seconds: number
}

// Mirrors NightModeConfig's own *editable* fields (config.py) -- not
// start/end, which are derived datetime.time values the server never
// sends (see admin_server.py's _night_mode_payload).
interface NightModeConfig {
  enabled: boolean
  start_time: string
  end_time: string
  dim_brightness: number
  suppress_scope: string
  cooldown_minutes: number
}

// Mirrors WifiConfig (config.py) -- ssid/password/country live in the
// same [wifi] TOML table but aren't modelled here at all: actually
// joining a network is setup_server.py's job (the offline-first
// captive-portal page), out of scope for this whole rebuild.
interface WifiConfig {
  connect_timeout_seconds: number
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

// ScoreboardApp.status_snapshot()'s dict, handed straight through by
// admin_server.py's own "snapshot" message (#178 story 10) -- this page
// has no more idea what a scene or a game is than the server does, so
// keys are rendered generically rather than modelled one field at a time.
type SnapshotData = Record<string, string>

type ServerMessage =
  | { type: 'version'; value: string }
  | { type: 'config'; section: 'audio'; data: AudioConfig }
  | { type: 'config'; section: 'scoreboard'; data: ScoreboardConfig }
  | { type: 'config'; section: 'status'; data: StatusConfig }
  | { type: 'config'; section: 'panel'; data: PanelConfig }
  | { type: 'config'; section: 'night_mode'; data: NightModeConfig }
  | { type: 'config'; section: 'wifi'; data: WifiConfig }
  | { type: 'config'; section: 'rotation'; data: RotationRow[] }
  | { type: 'config'; section: 'update'; data: UpdateConfig }
  | { type: 'snapshot'; data: SnapshotData }
  | { type: 'saved'; section: string }
  | { type: 'error'; section?: string; message: string }
  | { type: 'checking' }
  | { type: 'applying' }
  | { type: 'rebooting' }
  | { type: 'horn_tested'; played: boolean }
  | { type: 'horn_uploaded'; name: string }

function connectionBadge(state: ConnectionState) {
  const variant = state === 'open' ? 'success' : state === 'connecting' ? 'secondary' : 'danger'
  return <span className={`badge text-bg-${variant}`}>{state}</span>
}

function saveFeedback(status: SaveStatus, error: string | null) {
  if (status === 'saved') return <span className="text-success">Saved.</span>
  if (status === 'error') return <span className="text-danger">{error}</span>
  return null
}

function teamName(abbrev: string) {
  const team = NHL_TEAMS.find(([code]) => code === abbrev)
  return team ? team[1] : '(none)'
}

// One line, colour-coded, for the "Software update" status box -- the same
// four states the Software update card itself distinguishes, just
// summarised at a glance rather than with its own Check/Install buttons.
function updateStatusLine(update: UpdateConfig | null) {
  if (!update) return <span className="text-body-secondary">waiting...</span>
  if (update.error) return <span className="text-danger">Check failed</span>
  if (update.available && update.applicable) {
    return <span className="text-warning">Update available: {update.latest}</span>
  }
  return <span className="text-success">Up to date</span>
}

function App() {
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [version, setVersion] = useState<string | null>(null)

  const [audio, setAudio] = useState<AudioConfig | null>(null)
  const [audioSaveStatus, setAudioSaveStatus] = useState<SaveStatus>('idle')
  const [audioSaveError, setAudioSaveError] = useState<string | null>(null)
  const [hornTesting, setHornTesting] = useState(false)
  const [hornTestMessage, setHornTestMessage] = useState<{ text: string; ok: boolean } | null>(
    null,
  )

  const [scoreboard, setScoreboard] = useState<ScoreboardConfig | null>(null)
  const [scoreboardSaveStatus, setScoreboardSaveStatus] = useState<SaveStatus>('idle')
  const [scoreboardSaveError, setScoreboardSaveError] = useState<string | null>(null)

  const [status, setStatus] = useState<StatusConfig | null>(null)
  const [statusSaveStatus, setStatusSaveStatus] = useState<SaveStatus>('idle')
  const [statusSaveError, setStatusSaveError] = useState<string | null>(null)

  const [panel, setPanel] = useState<PanelConfig | null>(null)
  const [panelSaveStatus, setPanelSaveStatus] = useState<SaveStatus>('idle')
  const [panelSaveError, setPanelSaveError] = useState<string | null>(null)

  const [nightMode, setNightMode] = useState<NightModeConfig | null>(null)
  const [nightModeSaveStatus, setNightModeSaveStatus] = useState<SaveStatus>('idle')
  const [nightModeSaveError, setNightModeSaveError] = useState<string | null>(null)

  const [wifi, setWifi] = useState<WifiConfig | null>(null)
  const [wifiSaveStatus, setWifiSaveStatus] = useState<SaveStatus>('idle')
  const [wifiSaveError, setWifiSaveError] = useState<string | null>(null)

  const [rotation, setRotation] = useState<RotationRow[] | null>(null)
  const [rotationSaveStatus, setRotationSaveStatus] = useState<SaveStatus>('idle')
  const [rotationSaveError, setRotationSaveError] = useState<string | null>(null)

  const [update, setUpdate] = useState<UpdateConfig | null>(null)
  // 'checking'/'applying' cover the gap between clicking the button and the
  // watcher's broadcast landing once the real check/apply (out of process)
  // finishes -- this is the actual thing story 4 is for.
  const [updatePhase, setUpdatePhase] = useState<'idle' | 'checking' | 'applying'>('idle')
  const [updateActionError, setUpdateActionError] = useState<string | null>(null)
  const [rebooting, setRebooting] = useState(false)
  const [rebootError, setRebootError] = useState<string | null>(null)

  const [snapshot, setSnapshot] = useState<SnapshotData | null>(null)

  // Two pages don't justify a router (#193): plain view state.
  const [page, setPage] = useState<'home' | 'audio'>('home')
  const [hornUploadTeam, setHornUploadTeam] = useState('default')
  const [hornUploadFile, setHornUploadFile] = useState<File | null>(null)
  const [hornUploading, setHornUploading] = useState(false)
  const [hornUploadMessage, setHornUploadMessage] = useState<{ text: string; ok: boolean } | null>(
    null,
  )

  const socketRef = useRef<WebSocket | null>(null)
  const hornTestTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined

    function connect() {
      const socket = new WebSocket(WS_URL)
      socketRef.current = socket

      socket.onopen = () => {
        setConnection('open')
        // A reconnect after a real reboot is the normal way this ever
        // clears -- the board goes down (socket closes), comes back up,
        // and the reconnect loop above lands here. Nothing else ever set
        // this back to false, so without this the Reboot card stayed
        // stuck on "Rebooting the board now..." forever, even once the
        // board was demonstrably back and answering again.
        setRebooting(false)
      }
      // No reconnect loop here originally meant a dropped connection (a
      // backgrounded phone browser tab, a brief WiFi blip) stayed dead
      // until a manual page reload -- and worse, silently: the dropdown/
      // form still shows whatever was last picked locally, since that's
      // separate React state from whether a save actually reached the
      // server, so a save clicked while disconnected looked like it
      // worked when nothing was ever sent. Retry with a fixed short
      // delay -- this is a LAN admin page, not worth exponential backoff.
      socket.onclose = () => {
        setConnection('closed')
        if (!cancelled) reconnectTimer = setTimeout(connect, 2000)
      }
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as ServerMessage
        switch (message.type) {
          case 'version':
            setVersion(message.value)
            break
          case 'config':
            if (message.section === 'audio') setAudio(message.data)
            else if (message.section === 'scoreboard') setScoreboard(message.data)
            else if (message.section === 'status') setStatus(message.data)
            else if (message.section === 'panel') setPanel(message.data)
            else if (message.section === 'night_mode') setNightMode(message.data)
            else if (message.section === 'wifi') setWifi(message.data)
            else if (message.section === 'rotation') setRotation(message.data)
            else if (message.section === 'update') {
              setUpdate(message.data)
              setUpdatePhase('idle') // real data just arrived -- whatever was in flight is done
            }
            break
          case 'snapshot':
            setSnapshot(message.data)
            break
          case 'saved':
            if (message.section === 'audio') setAudioSaveStatus('saved')
            else if (message.section === 'scoreboard') setScoreboardSaveStatus('saved')
            else if (message.section === 'status') setStatusSaveStatus('saved')
            else if (message.section === 'panel') setPanelSaveStatus('saved')
            else if (message.section === 'night_mode') setNightModeSaveStatus('saved')
            else if (message.section === 'wifi') setWifiSaveStatus('saved')
            else if (message.section === 'rotation') setRotationSaveStatus('saved')
            break
          case 'horn_uploaded':
            setHornUploading(false)
            setHornUploadMessage({ text: `Uploaded ${message.name}.`, ok: true })
            break
          case 'error':
            if (message.section === 'horn_upload') {
              setHornUploading(false)
              setHornUploadMessage({ text: message.message, ok: false })
            } else if (message.section === 'audio') {
              setAudioSaveStatus('error')
              setAudioSaveError(message.message)
            } else if (message.section === 'scoreboard') {
              setScoreboardSaveStatus('error')
              setScoreboardSaveError(message.message)
            } else if (message.section === 'status') {
              setStatusSaveStatus('error')
              setStatusSaveError(message.message)
            } else if (message.section === 'panel') {
              setPanelSaveStatus('error')
              setPanelSaveError(message.message)
            } else if (message.section === 'night_mode') {
              setNightModeSaveStatus('error')
              setNightModeSaveError(message.message)
            } else if (message.section === 'wifi') {
              setWifiSaveStatus('error')
              setWifiSaveError(message.message)
            } else if (message.section === 'rotation') {
              setRotationSaveStatus('error')
              setRotationSaveError(message.message)
            }
            break
          case 'checking':
            setUpdatePhase('checking')
            setUpdateActionError(null)
            break
          case 'applying':
            setUpdatePhase('applying')
            setUpdateActionError(null)
            break
          case 'rebooting':
            setRebooting(true)
            setRebootError(null)
            break
          case 'horn_tested':
            setHornTesting(false)
            if (hornTestTimerRef.current) clearTimeout(hornTestTimerRef.current)
            if (message.played) {
              setHornTestMessage({ text: 'Playing...', ok: true })
              // Playback is fire-and-forget server-side (admin_server.py
              // has no way to report "finished"), so nothing else ever
              // clears this -- left as-is it said "Playing..." forever.
              // A few seconds is enough for any real horn WAV to finish.
              hornTestTimerRef.current = setTimeout(() => setHornTestMessage(null), 4000)
            } else {
              setHornTestMessage({
                text: 'No horn available -- check Audio is enabled and a horn file exists.',
                ok: false,
              })
            }
            break
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socketRef.current?.close()
    }
  }, [])

  const NOT_CONNECTED_ERROR = 'Not connected to the board -- wait for reconnect and try again.'

  // Returns whether the message actually went out. A closed/reconnecting
  // socket used to fail here silently (a plain `return`, no signal to the
  // caller) -- every saveXxx handler below now surfaces that as a visible
  // error instead of leaving the button's status stuck on "saving" forever
  // with no feedback, which is exactly what made a save-while-disconnected
  // look like it had worked: the form field itself is separate local state
  // that already reflects whatever was picked, whether or not a save ever
  // reached the server.
  function save(section: string, data: unknown): boolean {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false
    socketRef.current.send(JSON.stringify({ type: 'save', section, data }))
    return true
  }

  function saveAudio(event: React.FormEvent) {
    event.preventDefault()
    if (!audio) return
    setAudioSaveStatus('saving')
    setAudioSaveError(null)
    if (!save('audio', audio)) {
      setAudioSaveStatus('error')
      setAudioSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function saveScoreboard(event: React.FormEvent) {
    event.preventDefault()
    if (!scoreboard) return
    setScoreboardSaveStatus('saving')
    setScoreboardSaveError(null)
    if (!save('scoreboard', scoreboard)) {
      setScoreboardSaveStatus('error')
      setScoreboardSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function saveStatus(event: React.FormEvent) {
    event.preventDefault()
    if (!status) return
    setStatusSaveStatus('saving')
    setStatusSaveError(null)
    if (!save('status', status)) {
      setStatusSaveStatus('error')
      setStatusSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function savePanel(event: React.FormEvent) {
    event.preventDefault()
    if (!panel) return
    setPanelSaveStatus('saving')
    setPanelSaveError(null)
    // pitch_mm is in the payload the server sends (it's a real PanelConfig
    // field) but not one it validates on save -- status_server.py's own
    // form never exposed it either, since it's informational only.
    const { pitch_mm: _pitchMm, ...data } = panel
    if (!save('panel', data)) {
      setPanelSaveStatus('error')
      setPanelSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function saveNightMode(event: React.FormEvent) {
    event.preventDefault()
    if (!nightMode) return
    setNightModeSaveStatus('saving')
    setNightModeSaveError(null)
    if (!save('night_mode', nightMode)) {
      setNightModeSaveStatus('error')
      setNightModeSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function saveWifi(event: React.FormEvent) {
    event.preventDefault()
    if (!wifi) return
    setWifiSaveStatus('saving')
    setWifiSaveError(null)
    if (!save('wifi', wifi)) {
      setWifiSaveStatus('error')
      setWifiSaveError(NOT_CONNECTED_ERROR)
    }
  }

  function saveRotation(event: React.FormEvent) {
    event.preventDefault()
    if (!rotation) return
    setRotationSaveStatus('saving')
    setRotationSaveError(null)
    if (!save('rotation', rotation)) {
      setRotationSaveStatus('error')
      setRotationSaveError(NOT_CONNECTED_ERROR)
    }
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
    setUpdateActionError(null)
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setUpdateActionError(NOT_CONNECTED_ERROR)
      return
    }
    socketRef.current.send(JSON.stringify({ type: 'update_check' }))
  }

  function applyUpdate() {
    setUpdateActionError(null)
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setUpdateActionError(NOT_CONNECTED_ERROR)
      return
    }
    socketRef.current.send(JSON.stringify({ type: 'update_apply' }))
  }

  function rebootBoard() {
    setRebootError(null)
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setRebootError(NOT_CONNECTED_ERROR)
      return
    }
    socketRef.current.send(JSON.stringify({ type: 'reboot' }))
  }

  function uploadHorn() {
    if (!hornUploadFile) return
    setHornUploadMessage(null)
    if (hornUploadFile.size > HORN_MAX_BYTES) {
      setHornUploadMessage({ text: 'File is too large (max 2 MB).', ok: false })
      return
    }
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setHornUploadMessage({ text: NOT_CONNECTED_ERROR, ok: false })
      return
    }
    const socket = socketRef.current
    const team = hornUploadTeam
    setHornUploading(true)
    const reader = new FileReader()
    reader.onerror = () => {
      setHornUploading(false)
      setHornUploadMessage({ text: 'Could not read the file.', ok: false })
    }
    reader.onload = () => {
      // readAsDataURL yields "data:...;base64,<payload>"; the server wants just the payload.
      const data = String(reader.result).split(',', 2)[1] ?? ''
      socket.send(JSON.stringify({ type: 'upload_horn', team, data }))
    }
    reader.readAsDataURL(hornUploadFile)
  }

  function testHorn() {
    if (hornTestTimerRef.current) clearTimeout(hornTestTimerRef.current)
    setHornTestMessage(null)
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setHornTestMessage({ text: NOT_CONNECTED_ERROR, ok: false })
      return
    }
    setHornTesting(true)
    socketRef.current.send(JSON.stringify({ type: 'test_horn' }))
  }

  return (
    <div className="container py-4" style={{ maxWidth: '75rem' }}>
      <header className="mb-4">
        <h1 className="h3 mb-0">Hockey Scoreboard</h1>
      </header>

      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="card h-100">
            <div className="card-body text-center py-2">
              <div className="text-body-secondary small">Connection</div>
              <div className="fs-5">{connectionBadge(connection)}</div>
            </div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="card h-100">
            <div className="card-body text-center py-2">
              <div className="text-body-secondary small">Version</div>
              <div className="fs-5">{version ?? 'waiting...'}</div>
            </div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="card h-100">
            <div className="card-body text-center py-2">
              <div className="text-body-secondary small">Software update</div>
              <div className="fs-5">{updateStatusLine(update)}</div>
            </div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="card h-100">
            <div className="card-body text-center py-2">
              <div className="text-body-secondary small">Favourite team</div>
              <div className="fs-5">
                {scoreboard ? teamName(scoreboard.favourite_team) : 'waiting...'}
              </div>
            </div>
          </div>
        </div>
      </div>

      <ul className="nav nav-tabs mb-4">
        {(['home', 'audio'] as const).map((name) => (
          <li className="nav-item" key={name}>
            <button
              type="button"
              className={`nav-link${page === name ? ' active' : ''}`}
              onClick={() => setPage(name)}
            >
              {name === 'home' ? 'Home' : 'Audio'}
            </button>
          </li>
        ))}
      </ul>

      {page === 'home' && (
        <>
      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Board status</h2>
          {snapshot ? (
            Object.keys(snapshot).length === 0 ? (
              <p className="text-body-secondary mb-0">
                No live app to report on (local dev, or a board with no ScoreboardApp attached).
              </p>
            ) : (
              <div className="row row-cols-2 row-cols-md-4 g-2">
                {Object.entries(snapshot).map(([key, value]) => (
                  <div className="col" key={key}>
                    <div className="text-body-secondary small text-capitalize">{key}</div>
                    <div>{value || '(none)'}</div>
                  </div>
                ))}
              </div>
            )
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="row g-4">
      <div className="col-lg-6">

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Scoreboard</h2>
          {scoreboard ? (
            <form onSubmit={saveScoreboard}>
              <div className="mb-3">
                <label className="form-label" htmlFor="sb-favourite-team">
                  Favourite team
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="sb-favourite-team"
                  value={scoreboard.favourite_team}
                  onChange={(e) => setScoreboard({ ...scoreboard, favourite_team: e.target.value })}
                >
                  <option value="">(none)</option>
                  {NHL_TEAMS.map(([abbrev, name]) => (
                    <option key={abbrev} value={abbrev}>
                      {name} ({abbrev})
                    </option>
                  ))}
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="sb-timezone">
                  Timezone
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="sb-timezone"
                  value={scoreboard.timezone}
                  onChange={(e) => setScoreboard({ ...scoreboard, timezone: e.target.value })}
                >
                  {!US_TIMEZONES.some(([zone]) => zone === scoreboard.timezone) && (
                    <option value={scoreboard.timezone}>{scoreboard.timezone}</option>
                  )}
                  {US_TIMEZONES.map(([zone, label]) => (
                    <option key={zone} value={zone}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              <h3 className="h6 text-body-secondary mt-4">Timing</h3>
              {(
                [
                  ['rotate_seconds', 'Seconds per game in rotation'],
                  ['poll_seconds', 'Score poll interval (seconds)'],
                  ['live_poll_seconds', 'Live score poll interval (seconds)'],
                  ['countdown_hours', 'Countdown window before puck drop (hours)'],
                  ['final_hold_minutes', 'Final score hold time (minutes)'],
                  ['goal_flash_seconds', 'Goal celebration duration (seconds)'],
                  ['goal_detail_seconds', 'Goal detail duration (seconds)'],
                  ['three_stars_seconds', 'Three stars duration (seconds)'],
                ] as const
              ).map(([key, label]) => (
                <div className="mb-3" key={key}>
                  <label className="form-label" htmlFor={`sb-${key}`}>
                    {label}
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '10rem' }}
                    id={`sb-${key}`}
                    type="number"
                    step="any"
                    value={scoreboard[key]}
                    onChange={(e) =>
                      setScoreboard({ ...scoreboard, [key]: Number(e.target.value) })
                    }
                  />
                </div>
              ))}

              <h3 className="h6 text-body-secondary mt-4">Display</h3>
              {(
                [
                  ['show_clock_when_idle', 'Show clock when there are no games'],
                  ['show_clock_between_games', "Show clock between favourite's games"],
                  ['show_logos', 'Show team logos'],
                  ['show_standings', "Show favourite's playoff standings"],
                  ['prefer_favourite', 'Prefer favourite when choosing a game'],
                ] as const
              ).map(([key, label]) => (
                <div className="form-check mb-2" key={key}>
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id={`sb-${key}`}
                    checked={scoreboard[key]}
                    onChange={(e) => setScoreboard({ ...scoreboard, [key]: e.target.checked })}
                  />
                  <label className="form-check-label" htmlFor={`sb-${key}`}>
                    {label}
                  </label>
                </div>
              ))}
              <div className="mb-3 mt-2">
                <label className="form-label" htmlFor="sb-logo-variant">
                  Logo variant
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="sb-logo-variant"
                  value={scoreboard.logo_variant}
                  onChange={(e) => setScoreboard({ ...scoreboard, logo_variant: e.target.value })}
                >
                  <option value="dark">dark</option>
                  <option value="light">light</option>
                </select>
              </div>

              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={scoreboardSaveStatus === 'saving'}
                >
                  Save Scoreboard
                </button>
                {saveFeedback(scoreboardSaveStatus, scoreboardSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Panel</h2>
          {panel ? (
            <form onSubmit={savePanel}>
              <h3 className="h6 text-body-secondary mt-2">
                Geometry <span className="badge text-bg-secondary fw-normal">restart required</span>
              </h3>
              {(
                [
                  ['rows', 'Rows per panel'],
                  ['cols', 'Columns per panel'],
                  ['chain_length', 'Chain length'],
                  ['parallel', 'Parallel chains'],
                ] as const
              ).map(([key, label]) => (
                <div className="mb-3" key={key}>
                  <label className="form-label" htmlFor={`panel-${key}`}>
                    {label}
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '10rem' }}
                    id={`panel-${key}`}
                    type="number"
                    step="1"
                    value={panel[key]}
                    onChange={(e) => setPanel({ ...panel, [key]: Number(e.target.value) })}
                  />
                </div>
              ))}

              <h3 className="h6 text-body-secondary mt-4">
                Driver / PWM <span className="badge text-bg-secondary fw-normal">restart required</span>
              </h3>
              <div className="mb-3">
                <label className="form-label" htmlFor="panel-hardware-mapping">
                  Hardware mapping
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="panel-hardware-mapping"
                  value={panel.hardware_mapping}
                  onChange={(e) => setPanel({ ...panel, hardware_mapping: e.target.value })}
                >
                  <option value="regular">regular</option>
                  <option value="adafruit-hat">adafruit-hat</option>
                  <option value="adafruit-hat-pwm">adafruit-hat-pwm</option>
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="panel-rgb-sequence">
                  RGB sequence (colour wire order)
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="panel-rgb-sequence"
                  value={panel.rgb_sequence}
                  onChange={(e) => setPanel({ ...panel, rgb_sequence: e.target.value })}
                >
                  {(['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR'] as const).map((seq) => (
                    <option key={seq} value={seq}>
                      {seq}
                    </option>
                  ))}
                </select>
              </div>
              {(
                [
                  ['gpio_slowdown', 'GPIO slowdown'],
                  ['pwm_bits', 'PWM bits'],
                  ['pwm_lsb_nanoseconds', 'PWM LSB nanoseconds'],
                  ['limit_refresh_rate_hz', 'Refresh rate limit (Hz, 0 = unlimited)'],
                ] as const
              ).map(([key, label]) => (
                <div className="mb-3" key={key}>
                  <label className="form-label" htmlFor={`panel-${key}`}>
                    {label}
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '10rem' }}
                    id={`panel-${key}`}
                    type="number"
                    step="1"
                    value={panel[key]}
                    onChange={(e) => setPanel({ ...panel, [key]: Number(e.target.value) })}
                  />
                </div>
              ))}
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="panel-disable-hardware-pulsing"
                  checked={panel.disable_hardware_pulsing}
                  onChange={(e) =>
                    setPanel({ ...panel, disable_hardware_pulsing: e.target.checked })
                  }
                />
                <label className="form-check-label" htmlFor="panel-disable-hardware-pulsing">
                  Disable hardware pulsing
                </label>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="panel-pixel-mapper">
                  Pixel mapper (blank for none)
                </label>
                <input
                  className="form-control"
                  id="panel-pixel-mapper"
                  type="text"
                  value={panel.pixel_mapper}
                  onChange={(e) => setPanel({ ...panel, pixel_mapper: e.target.value })}
                />
              </div>

              <h3 className="h6 text-body-secondary mt-4">Brightness</h3>
              <div className="mb-3">
                <label className="form-label" htmlFor="panel-brightness">
                  Brightness (1-100)
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="panel-brightness"
                  type="number"
                  step="1"
                  min="1"
                  max="100"
                  value={panel.brightness}
                  onChange={(e) => setPanel({ ...panel, brightness: Number(e.target.value) })}
                />
              </div>
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="panel-auto-brightness"
                  checked={panel.auto_brightness}
                  onChange={(e) => setPanel({ ...panel, auto_brightness: e.target.checked })}
                />
                <label className="form-check-label" htmlFor="panel-auto-brightness">
                  Auto brightness from ambient sensor
                </label>
              </div>
              {(
                [
                  ['min_brightness', 'Auto-brightness minimum'],
                  ['max_brightness', 'Auto-brightness maximum'],
                ] as const
              ).map(([key, label]) => (
                <div className="mb-3" key={key}>
                  <label className="form-label" htmlFor={`panel-${key}`}>
                    {label}
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '10rem' }}
                    id={`panel-${key}`}
                    type="number"
                    step="1"
                    min="1"
                    max="100"
                    value={panel[key]}
                    onChange={(e) => setPanel({ ...panel, [key]: Number(e.target.value) })}
                  />
                </div>
              ))}
              <div className="mb-3">
                <label className="form-label" htmlFor="panel-brightness-poll-seconds">
                  Brightness sensor poll interval (seconds)
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="panel-brightness-poll-seconds"
                  type="number"
                  step="any"
                  value={panel.brightness_poll_seconds}
                  onChange={(e) =>
                    setPanel({ ...panel, brightness_poll_seconds: Number(e.target.value) })
                  }
                />
              </div>

              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={panelSaveStatus === 'saving'}
                >
                  Save Panel
                </button>
                {saveFeedback(panelSaveStatus, panelSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      </div>
      <div className="col-lg-6">

      <div className="card mb-4">
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

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Status page</h2>
          {status ? (
            <form onSubmit={saveStatus}>
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="status-enabled"
                  checked={status.enabled}
                  onChange={(e) => setStatus({ ...status, enabled: e.target.checked })}
                />
                <label className="form-check-label" htmlFor="status-enabled">
                  Status page enabled
                </label>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="status-port">
                  Status page port
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="status-port"
                  type="number"
                  step="1"
                  value={status.port}
                  onChange={(e) => setStatus({ ...status, port: Number(e.target.value) })}
                />
              </div>
              <div className="d-flex align-items-center gap-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={statusSaveStatus === 'saving'}
                >
                  Save Status page
                </button>
                {saveFeedback(statusSaveStatus, statusSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Night mode</h2>
          {nightMode ? (
            <form onSubmit={saveNightMode}>
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="night-mode-enabled"
                  checked={nightMode.enabled}
                  onChange={(e) => setNightMode({ ...nightMode, enabled: e.target.checked })}
                />
                <label className="form-check-label" htmlFor="night-mode-enabled">
                  Night mode enabled
                </label>
              </div>
              <div className="d-flex gap-3">
                <div className="mb-3">
                  <label className="form-label" htmlFor="night-mode-start-time">
                    Dim window start (24-hour HH:MM)
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '8rem' }}
                    id="night-mode-start-time"
                    type="text"
                    value={nightMode.start_time}
                    onChange={(e) => setNightMode({ ...nightMode, start_time: e.target.value })}
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label" htmlFor="night-mode-end-time">
                    Dim window end (24-hour HH:MM)
                  </label>
                  <input
                    className="form-control"
                    style={{ maxWidth: '8rem' }}
                    id="night-mode-end-time"
                    type="text"
                    value={nightMode.end_time}
                    onChange={(e) => setNightMode({ ...nightMode, end_time: e.target.value })}
                  />
                </div>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="night-mode-dim-brightness">
                  Dimmed brightness (0-100)
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="night-mode-dim-brightness"
                  type="number"
                  step="1"
                  min="0"
                  max="100"
                  value={nightMode.dim_brightness}
                  onChange={(e) =>
                    setNightMode({ ...nightMode, dim_brightness: Number(e.target.value) })
                  }
                />
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="night-mode-suppress-scope">
                  Suppress scope
                </label>
                <select
                  className="form-select"
                  style={{ width: 'auto' }}
                  id="night-mode-suppress-scope"
                  value={nightMode.suppress_scope}
                  onChange={(e) => setNightMode({ ...nightMode, suppress_scope: e.target.value })}
                >
                  <option value="tracked">tracked (favourite's game only)</option>
                  <option value="all">all (any live game)</option>
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label" htmlFor="night-mode-cooldown-minutes">
                  Cooldown after game ends (minutes)
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="night-mode-cooldown-minutes"
                  type="number"
                  step="any"
                  min="0"
                  value={nightMode.cooldown_minutes}
                  onChange={(e) =>
                    setNightMode({ ...nightMode, cooldown_minutes: Number(e.target.value) })
                  }
                />
              </div>
              <div className="d-flex align-items-center gap-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={nightModeSaveStatus === 'saving'}
                >
                  Save Night mode
                </button>
                {saveFeedback(nightModeSaveStatus, nightModeSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Wi-Fi</h2>
          <p className="text-body-secondary small">
            Network name and password are set from the board's own setup page, not here -- this
            only tunes how long a join attempt waits before deciding it failed.
          </p>
          {wifi ? (
            <form onSubmit={saveWifi}>
              <div className="mb-3">
                <label className="form-label" htmlFor="wifi-connect-timeout-seconds">
                  Join attempt timeout (seconds)
                </label>
                <input
                  className="form-control"
                  style={{ maxWidth: '10rem' }}
                  id="wifi-connect-timeout-seconds"
                  type="number"
                  step="any"
                  min="0"
                  value={wifi.connect_timeout_seconds}
                  onChange={(e) =>
                    setWifi({ ...wifi, connect_timeout_seconds: Number(e.target.value) })
                  }
                />
              </div>
              <div className="d-flex align-items-center gap-3">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={wifiSaveStatus === 'saving'}
                >
                  Save Wi-Fi
                </button>
                {saveFeedback(wifiSaveStatus, wifiSaveError)}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
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
                {updateActionError && <span className="text-danger">{updateActionError}</span>}
              </div>
            </>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Reboot</h2>
          <p className="text-body-secondary small">
            Reboots the whole board to apply any "applies after restart" change. This interrupts
            whatever is on screen right now, including a live game.
          </p>
          {rebooting ? (
            <p className="text-warning mb-0">Rebooting the board now...</p>
          ) : (
            <div className="d-flex align-items-center gap-3">
              <button type="button" className="btn btn-danger" onClick={rebootBoard}>
                Reboot board
              </button>
              {rebootError && <span className="text-danger">{rebootError}</span>}
            </div>
          )}
        </div>
      </div>

      </div>
      </div>
        </>
      )}

      {page === 'audio' && (
        <>
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
              <div className="mb-3">
                <label className="form-label" htmlFor="audio-volume">
                  Volume ({audio.volume}%)
                </label>
                <input
                  className="form-range"
                  id="audio-volume"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={audio.volume}
                  onChange={(e) => setAudio({ ...audio, volume: Number(e.target.value) })}
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
              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={testHorn}
                  disabled={hornTesting}
                >
                  Test horn
                </button>
                {hornTestMessage && (
                  <span className={hornTestMessage.ok ? 'text-success' : 'text-danger'}>
                    {hornTestMessage.text}
                  </span>
                )}
              </div>
            </form>
          ) : (
            <p className="text-body-secondary mb-0">waiting for server...</p>
          )}
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-body">
          <h2 className="card-title h5">Custom goal horns</h2>
          <p className="text-body-secondary small">
            Upload a WAV (max 2 MB) to replace the default horn, or to give one team its own. A
            team's own horn always wins over the default.
          </p>
          <div className="row g-3 align-items-end">
            <div className="col-md-4">
              <label className="form-label" htmlFor="horn-upload-team">
                Horn for
              </label>
              <select
                className="form-select"
                id="horn-upload-team"
                value={hornUploadTeam}
                onChange={(e) => setHornUploadTeam(e.target.value)}
              >
                <option value="default">Default horn (all teams)</option>
                {NHL_TEAMS.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name} ({code})
                  </option>
                ))}
              </select>
            </div>
            <div className="col-md-5">
              <label className="form-label" htmlFor="horn-upload-file">
                WAV file
              </label>
              <input
                className="form-control"
                id="horn-upload-file"
                type="file"
                accept=".wav,audio/wav,audio/x-wav"
                onChange={(e) => setHornUploadFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="col-md-3">
              <button
                type="button"
                className="btn btn-primary"
                onClick={uploadHorn}
                disabled={!hornUploadFile || hornUploading}
              >
                Upload horn
              </button>
            </div>
          </div>
          {hornUploadMessage && (
            <p className={`mt-3 mb-0 ${hornUploadMessage.ok ? 'text-success' : 'text-danger'}`}>
              {hornUploadMessage.text}
            </p>
          )}
        </div>
      </div>

        </>
      )}
    </div>
  )
}

export default App
