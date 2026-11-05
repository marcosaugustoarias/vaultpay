import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, refreshAccessToken, setSessionExpiredHandler, tokenStore } from './api'

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })

describe('api client security behaviour', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    tokenStore.set(null)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setSessionExpiredHandler(null)
  })

  it('sends the bearer token and the CSRF header', async () => {
    tokenStore.set('tok-1')
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }))
    await api('/accounts')
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/accounts')
    expect(init.headers.Authorization).toBe('Bearer tok-1')
    expect(init.headers['X-Requested-With']).toBe('vaultpay')
    expect(init.credentials).toBe('same-origin')
  })

  it('refreshes once on 401 and replays the request', async () => {
    tokenStore.set('expired')
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: { code: 'not_authenticated', message: 'x' } }))
      .mockResolvedValueOnce(json(200, { access_token: 'fresh' })) // /auth/refresh
      .mockResolvedValueOnce(json(200, [{ id: 'a' }]))
    const data = await api<{ id: string }[]>('/accounts')
    expect(data[0]!.id).toBe('a')
    expect(fetchMock.mock.calls[1]![0]).toBe('/api/auth/refresh')
    expect(fetchMock.mock.calls[2]![1].headers.Authorization).toBe('Bearer fresh')
  })

  it('concurrent refreshes are coalesced into ONE network call (rotation-safe)', async () => {
    let resolve!: (r: Response) => void
    fetchMock.mockReturnValueOnce(new Promise<Response>((r) => (resolve = r)))
    const results = Promise.all([refreshAccessToken(), refreshAccessToken(), refreshAccessToken()])
    resolve(json(200, { access_token: 'one' }))
    expect(await results).toEqual(['one', 'one', 'one'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('signals session expiry when refresh fails', async () => {
    const expired = vi.fn()
    setSessionExpiredHandler(expired)
    tokenStore.set('expired')
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: { code: 'not_authenticated', message: 'x' } }))
      .mockResolvedValueOnce(json(401, { detail: { code: 'invalid_refresh', message: 'x' } }))
    await expect(api('/accounts')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledOnce()
    expect(tokenStore.get()).toBeNull()
  })

  it('does NOT refresh or replay on business 401s such as a wrong OTP (regression)', async () => {
    tokenStore.set('valid')
    fetchMock.mockResolvedValueOnce(json(401, { detail: { code: 'invalid_otp', message: 'Invalid verification code.' } }))
    const err = (await api('/transfers', { method: 'POST', body: {} }).catch((e) => e)) as ApiError
    expect(err.code).toBe('invalid_otp')
    expect(fetchMock).toHaveBeenCalledTimes(1) // no /auth/refresh, no replayed transfer
    expect(tokenStore.get()).toBe('valid')
  })

  it('maps server errors to typed ApiError with stable codes', async () => {
    fetchMock.mockResolvedValueOnce(json(422, { detail: { code: 'insufficient_funds', message: 'Insufficient funds.' }, request_id: 'r1' }))
    const err = (await api('/transfers', { method: 'POST', body: {} }).catch((e) => e)) as ApiError
    expect(err.code).toBe('insufficient_funds')
    expect(err.requestId).toBe('r1')
  })

  it('never persists tokens in Web Storage', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { access_token: 'secret-token' }))
    await refreshAccessToken()
    expect(tokenStore.get()).toBe('secret-token')
    expect(JSON.stringify({ ...window.localStorage })).not.toContain('secret-token')
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain('secret-token')
    expect(document.cookie).not.toContain('secret-token')
  })
})
