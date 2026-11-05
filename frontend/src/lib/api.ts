/**
 * HTTP client.
 *
 * SEC-FE-01  The short-lived ACCESS token lives only in this module's memory:
 *            never Web Storage or JS-readable cookies, so an XSS payload cannot
 *            exfiltrate it from storage and a page reload drops it. The long-lived
 *            REFRESH token is an HttpOnly cookie that JavaScript cannot read.
 * SEC-FE-05  Refresh is single-flight (also across tabs via Web Locks). The server
 *            rotates refresh tokens and treats re-use as theft, so two concurrent
 *            refreshes with the same cookie must never happen.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fieldErrors: { field: string; message: string }[] = [],
    public requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

let accessToken: string | null = null
let onSessionExpired: (() => void) | null = null
let refreshInFlight: Promise<string | null> | null = null

export const tokenStore = {
  get: () => accessToken,
  set: (t: string | null) => {
    accessToken = t
  },
}

export function setSessionExpiredHandler(fn: (() => void) | null) {
  onSessionExpired = fn
}

const CSRF_HEADERS = { 'X-Requested-With': 'vaultpay' } // forces a CORS pre-flight cross-origin

async function parseError(res: Response): Promise<ApiError> {
  let body: any = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON error (proxy, 502...) */
  }
  const detail = body?.detail
  if (res.status === 429) {
    const retry = res.headers.get('Retry-After')
    return new ApiError(429, 'rate_limited', retry ? `Demasiados intentos. Reintentá en ${retry}s.` : 'Demasiados intentos.')
  }
  if (detail && typeof detail === 'object') {
    return new ApiError(res.status, detail.code ?? 'error', detail.message ?? 'Error', detail.errors ?? [], body?.request_id)
  }
  return new ApiError(res.status, 'error', typeof detail === 'string' ? detail : 'Error inesperado', [], body?.request_id)
}

async function doRefresh(): Promise<string | null> {
  try {
    const res = await fetch('/api/auth/refresh', { method: 'POST', headers: CSRF_HEADERS, credentials: 'same-origin' })
    if (!res.ok) {
      accessToken = null
      return null
    }
    const data = (await res.json()) as { access_token: string }
    accessToken = data.access_token
    return accessToken
  } catch {
    return null
  }
}

export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    const run = () => doRefresh()
    const locked = typeof navigator !== 'undefined' && navigator.locks ? navigator.locks.request('vaultpay-refresh', run) : run()
    refreshInFlight = Promise.resolve(locked).finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

interface Options {
  method?: 'GET' | 'POST'
  body?: unknown
  headers?: Record<string, string>
  auth?: boolean
}

export async function api<T>(path: string, opts: Options = {}, retried = false): Promise<T> {
  const { method = 'GET', body, headers = {}, auth = true } = opts
  const h: Record<string, string> = { ...CSRF_HEADERS, ...headers }
  if (body !== undefined) h['Content-Type'] = 'application/json'
  if (auth && accessToken) h.Authorization = `Bearer ${accessToken}`

  const res = await fetch(`/api${path}`, {
    method,
    headers: h,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!res.ok) {
    const err = await parseError(res)
    // Only an authentication failure triggers refresh + replay. Business 401s (wrong OTP,
    // step-up required...) are returned as-is: replaying them would burn extra failed
    // attempts toward the lockout and re-submit a money-moving POST.
    if (err.status === 401 && err.code === 'not_authenticated' && auth) {
      if (!retried) {
        const fresh = await refreshAccessToken()
        if (fresh) return api<T>(path, opts, true)
      }
      accessToken = null
      onSessionExpired?.()
    }
    throw err
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}
