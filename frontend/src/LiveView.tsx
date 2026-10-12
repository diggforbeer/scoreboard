import { useEffect, useRef } from 'react'

// One frame of the panel (#268): base64 RGB, row-major, 3 bytes a pixel,
// as drawn (full brightness). `brightness` is the panel's setting, in %.
export type PanelFrame = {
  type: 'frame'
  width: number
  height: number
  brightness: number
  data: string
}

// Canvas pixels per LED. The canvas is scaled to the card's width by CSS;
// this only sets how round the dots look.
const PITCH = 8
const DOT_RADIUS = 3.2
const UNLIT = '#1a1a1a'

function drawFrame(canvas: HTMLCanvasElement, frame: PanelFrame) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const raw = atob(frame.data)
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  for (let y = 0; y < frame.height; y++) {
    for (let x = 0; x < frame.width; x++) {
      const i = (y * frame.width + x) * 3
      const r = raw.charCodeAt(i)
      const g = raw.charCodeAt(i + 1)
      const b = raw.charCodeAt(i + 2)
      ctx.fillStyle = r || g || b ? `rgb(${r},${g},${b})` : UNLIT
      ctx.beginPath()
      ctx.arc(x * PITCH + PITCH / 2, y * PITCH + PITCH / 2, DOT_RADIUS, 0, 2 * Math.PI)
      ctx.fill()
    }
  }
}

type Props = {
  enabled: boolean
  onToggle: (enabled: boolean) => void
  frame: PanelFrame | null
  error: string | null
}

export function LiveView({ enabled, onToggle, frame, error }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (enabled && frame && canvasRef.current) drawFrame(canvasRef.current, frame)
  }, [enabled, frame])

  const allDark = frame !== null && !/[^A]/.test(frame.data.replace(/=+$/, ''))

  return (
    <div className="card mb-4">
      <div className="card-body">
        <div className="d-flex align-items-center justify-content-between mb-2">
          <h2 className="card-title h5 mb-0">Live view</h2>
          <button
            type="button"
            className={enabled ? 'btn btn-outline-secondary btn-sm' : 'btn btn-outline-primary btn-sm'}
            onClick={() => onToggle(!enabled)}
          >
            {enabled ? 'Hide' : 'Show live view'}
          </button>
        </div>
        {!enabled && (
          <p className="text-body-secondary small mb-0">
            What the panel is showing right now, a few times a second. Off until you open it, so
            a page left open on a phone doesn't keep a stream running.
          </p>
        )}
        {enabled && error && <p className="text-danger mb-0">{error}</p>}
        {enabled && !error && (
          <>
            {frame ? (
              <canvas
                ref={canvasRef}
                width={frame.width * PITCH}
                height={frame.height * PITCH}
                className="w-100 rounded"
                style={{ background: '#000', imageRendering: 'pixelated' }}
                aria-label="Live view of the LED panel"
                data-testid="live-view"
              />
            ) : (
              <p className="text-body-secondary mb-0">waiting for the next frame...</p>
            )}
            {frame && (
              <p className="text-body-secondary small mt-2 mb-0">
                Colours as drawn, at full brightness; the panel is set to {frame.brightness}%.{' '}
                {allDark
                  ? 'Nothing is lit: the board is drawing a blank frame on purpose (night mode, for one).'
                  : 'If this shows a picture but the panel is dark, check the Panel hardware mapping and the wiring.'}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
