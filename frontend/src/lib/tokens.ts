import type { TokenPair } from './types'

const ACCESS_KEY = 'teamflow.access_token'
const REFRESH_KEY = 'teamflow.refresh_token'

export const SESSION_EXPIRED_EVENT = 'teamflow:session-expired'

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // Storage unavailable (private mode) — the session then lives for the tab.
  }
}

export const tokens = {
  hasSession(): boolean {
    return Boolean(read(REFRESH_KEY))
  },

  getAccess(): string | null {
    return read(ACCESS_KEY)
  },

  getRefresh(): string | null {
    return read(REFRESH_KEY)
  },

  set(pair: TokenPair): void {
    write(ACCESS_KEY, pair.access_token)
    write(REFRESH_KEY, pair.refresh_token)
  },

  clear(): void {
    write(ACCESS_KEY, null)
    write(REFRESH_KEY, null)
  },
}
