import { SESSION_EXPIRED_EVENT, tokens } from './tokens'

export type SocketStatus = 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'

export interface ProjectSocketEvent {
  type: string
  data: { id?: string; task_id?: string; project_id?: string; [key: string]: unknown }
  ts?: string
}

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const MAX_BACKOFF_MS = 30_000
const PING_INTERVAL_MS = 25_000

function socketBaseUrl(): string {
  const explicit = import.meta.env.VITE_WS_BASE_URL as string | undefined
  if (explicit) return explicit.replace(/\/+$/, '')
  // Absolute API base (local development): swap the scheme and drop /api/v1.
  if (/^https?:\/\//i.test(API_BASE_URL)) {
    return API_BASE_URL.replace(/^http/, 'ws')
      .replace(/\/api\/v1\/?$/, '')
      .replace(/\/+$/, '')
  }
  // Relative API base (behind the production proxy): stay same-origin.
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const prefix = API_BASE_URL.replace(/\/api\/v1\/?$/, '').replace(/\/+$/, '')
  return `${protocol}://${window.location.host}${prefix}`
}

export function createProjectSocket(
  projectId: string,
  onEvent: (event: ProjectSocketEvent) => void,
  onStatus: (status: SocketStatus) => void,
): () => void {
  let socket: WebSocket | null = null
  let disposed = false
  let attempt = 0
  let reconnectTimer: number | null = null
  let pingTimer: number | null = null

  const stopTimers = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (pingTimer !== null) {
      window.clearInterval(pingTimer)
      pingTimer = null
    }
  }

  const reconnect = () => {
    if (disposed) return
    attempt += 1
    const delay = Math.min(1000 * 2 ** (attempt - 1), MAX_BACKOFF_MS)
    onStatus('reconnecting')
    reconnectTimer = window.setTimeout(connect, delay)
  }

  const connect = () => {
    if (disposed) return
    onStatus(attempt === 0 ? 'connecting' : 'reconnecting')
    const token = tokens.getAccess()
    const query = token ? `?token=${encodeURIComponent(token)}` : ''
    const current = new WebSocket(`${socketBaseUrl()}/ws/projects/${projectId}${query}`)
    socket = current

    current.onopen = () => {
      attempt = 0
      onStatus('open')
      pingTimer = window.setInterval(() => {
        if (current.readyState === WebSocket.OPEN) {
          current.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL_MS)
    }

    current.onmessage = (message) => {
      try {
        const parsed = JSON.parse(String(message.data)) as ProjectSocketEvent
        if (parsed && typeof parsed.type === 'string') onEvent(parsed)
      } catch {
        // Ignore malformed frames rather than tearing the socket down.
      }
    }

    current.onclose = (event) => {
      if (pingTimer !== null) {
        window.clearInterval(pingTimer)
        pingTimer = null
      }
      if (current !== socket) return
      socket = null
      if (disposed) {
        onStatus('closed')
        return
      }
      if (event.code === 4401) {
        // Token rejected: refresh will not help, tear the session down.
        tokens.clear()
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
        onStatus('error')
        return
      }
      if (event.code === 4404) {
        onStatus('error')
        return
      }
      reconnect()
    }
  }

  connect()

  return () => {
    disposed = true
    stopTimers()
    const current = socket
    socket = null
    current?.close()
    onStatus('closed')
  }
}
