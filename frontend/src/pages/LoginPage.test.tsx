import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('login flow', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('asks for the TOTP code when the server requires MFA', async () => {
    const routes: Record<string, () => Response> = {
      '/api/auth/refresh': () => json(401, { detail: { code: 'invalid_refresh', message: '' } }),
      '/api/auth/login': () => json(200, { mfa_required: true, mfa_token: 'mfa-tok' }),
      '/api/auth/mfa/verify': () => json(200, { access_token: 'acc' }),
      '/api/auth/me': () => json(200, { id: 'u', email: 'a@b.co', full_name: 'Ana Pérez', role: 'customer', mfa_enabled: true, created_at: '' }),
      '/api/accounts': () => json(200, [{ id: 'acc-1', account_number: '000000000000', currency: 'USD', balance_cents: 12345 }]),
      '/api/meta': () => json(200, { step_up_threshold_cents: 50000, max_transfer_cents: 1000000, demo_funding_enabled: false, demo_funding_max_cents: 0 }),
      '/api/accounts/acc-1/transactions?limit=10': () => json(200, { items: [], next_cursor: null }),
    }
    fetchMock.mockImplementation(async (url: string) => (routes[url] ?? (() => json(404, {})))())

    const user = userEvent.setup()
    renderApp()
    await user.type(await screen.findByLabelText('Correo electrónico'), 'a@b.co')
    await user.type(screen.getByLabelText('Contraseña'), 'tangerine-orbit-maple-42')
    await user.click(screen.getByRole('button', { name: 'Ingresar' }))

    const codeInput = await screen.findByLabelText('Código')
    await user.type(codeInput, '12a3456') // non-digits are stripped
    expect(codeInput).toHaveValue('123456')
    await user.click(screen.getByRole('button', { name: 'Verificar' }))

    await waitFor(() => expect(screen.getByTestId('balance')).toHaveTextContent('$123.45'))
    const verifyCall = fetchMock.mock.calls.find(([u]) => u === '/api/auth/mfa/verify')!
    expect(JSON.parse(verifyCall[1].body)).toEqual({ mfa_token: 'mfa-tok', code: '123456' })
  })

  it('shows one generic message for bad credentials', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/login'
        ? json(401, { detail: { code: 'invalid_credentials', message: 'Invalid credentials.' } })
        : json(401, { detail: { code: 'invalid_refresh', message: '' } }),
    )
    const user = userEvent.setup()
    renderApp()
    await user.type(await screen.findByLabelText('Correo electrónico'), 'x@y.co')
    await user.type(screen.getByLabelText('Contraseña'), 'whatever-password')
    await user.click(screen.getByRole('button', { name: 'Ingresar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Credenciales inválidas o cuenta bloqueada temporalmente.')
  })
})
