import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const DEST = '858448891235' // valid Luhn
const BAD_LUHN = '858448891236'

type Handler = (init?: RequestInit) => Response

function server(opts: { mfa?: boolean; balance?: number; transfer?: Handler } = {}) {
  const routes: Record<string, Handler> = {
    '/api/auth/refresh': () => json(200, { access_token: 'acc' }),
    '/api/auth/me': () =>
      json(200, { id: 'u', email: 'ana@example.com', full_name: 'Ana Prueba', role: 'customer', mfa_enabled: opts.mfa ?? false, created_at: '' }),
    '/api/accounts': () => json(200, [{ id: 'acc-1', account_number: '000000000000', currency: 'USD', balance_cents: opts.balance ?? 100000 }]),
    '/api/meta': () => json(200, { step_up_threshold_cents: 50000, max_transfer_cents: 1000000, demo_funding_enabled: true, demo_funding_max_cents: 100000 }),
    '/api/transfers': opts.transfer ?? (() => json(201, {})),
  }
  return vi.fn(async (url: string, init?: RequestInit) => (routes[url] ?? (() => json(404, {})))(init))
}

function renderTransfer() {
  return render(
    <MemoryRouter initialEntries={['/transfer']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const txOk = (amount: number) =>
  json(201, { id: 'tx-123', kind: 'transfer', amount_cents: amount, currency: 'USD', description: '', from_account: '••••0000', to_account: '••••1235', created_at: '' })

describe('transfer page', () => {
  let fetchMock: ReturnType<typeof server>
  afterEach(() => vi.unstubAllGlobals())

  describe('without MFA', () => {
    beforeEach(() => {
      fetchMock = server({ transfer: () => txOk(2500) })
      vi.stubGlobal('fetch', fetchMock)
    })

    it('flags a mistyped account number (Luhn) and keeps the form disabled', async () => {
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), BAD_LUHN)
      await user.type(screen.getByLabelText('Monto (USD)'), '25')
      expect(screen.getByText('Número de cuenta inválido (dígito verificador)')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
    })

    it('blocks amounts above the available balance before calling the API', async () => {
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), DEST)
      await user.type(screen.getByLabelText('Monto (USD)'), '1000.01')
      expect(screen.getByText('Fondos insuficientes')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
    })

    it('reviews and sends a transfer with an idempotency key and integer cents', async () => {
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), DEST)
      await user.type(screen.getByLabelText('Monto (USD)'), '25.00')
      await user.type(screen.getByLabelText('Concepto (opcional)'), '  Cena  ')
      await user.click(screen.getByRole('button', { name: 'Continuar' }))

      expect(await screen.findByText('Revisá la operación')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Confirmar envío' }))

      expect(await screen.findByText('Transferencia enviada')).toBeInTheDocument()
      const [, init] = fetchMock.mock.calls.find(([u]) => u === '/api/transfers')!
      const headers = init!.headers as Record<string, string>
      expect(headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
      expect(JSON.parse(init!.body as string)).toEqual({
        from_account_id: 'acc-1',
        to_account_number: DEST,
        amount_cents: 2500,
        description: 'Cena',
      })
    })

    it('asks to enable 2FA instead of allowing a step-up amount', async () => {
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), DEST)
      await user.type(screen.getByLabelText('Monto (USD)'), '500')
      expect(screen.getByText(/tenés que activar la verificación en dos pasos/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
    })
  })

  describe('with MFA (step-up)', () => {
    it('requires a 6-digit code for high amounts and sends it', async () => {
      fetchMock = server({ mfa: true, transfer: () => txOk(60000) })
      vi.stubGlobal('fetch', fetchMock)
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), DEST)
      await user.type(screen.getByLabelText('Monto (USD)'), '600')
      await user.click(screen.getByRole('button', { name: 'Continuar' }))

      const confirm = await screen.findByRole('button', { name: 'Confirmar envío' })
      expect(confirm).toBeDisabled()
      await user.type(screen.getByLabelText('Código de verificación 2FA'), '12a345')
      expect(confirm).toBeDisabled() // only 5 digits after stripping the letter
      await user.type(screen.getByLabelText('Código de verificación 2FA'), '6')
      await user.click(confirm)

      expect(await screen.findByText('Transferencia enviada')).toBeInTheDocument()
      const [, init] = fetchMock.mock.calls.find(([u]) => u === '/api/transfers')!
      expect(JSON.parse(init!.body as string)).toMatchObject({ amount_cents: 60000, otp_code: '123456' })
    })

    it('shows the domain error in Spanish and clears a rejected code', async () => {
      fetchMock = server({
        mfa: true,
        transfer: () => json(401, { detail: { code: 'invalid_otp', message: 'Invalid verification code.' } }),
      })
      vi.stubGlobal('fetch', fetchMock)
      const user = userEvent.setup()
      renderTransfer()
      await user.type(await screen.findByLabelText('Cuenta destino'), DEST)
      await user.type(screen.getByLabelText('Monto (USD)'), '600')
      await user.click(screen.getByRole('button', { name: 'Continuar' }))
      await user.type(await screen.findByLabelText('Código de verificación 2FA'), '000000')
      await user.click(screen.getByRole('button', { name: 'Confirmar envío' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Código de verificación inválido o ya utilizado.')
      await waitFor(() => expect(screen.getByLabelText('Código de verificación 2FA')).toHaveValue(''))
      // Exactly one POST: business 401s are never auto-replayed (would burn lockout attempts).
      expect(fetchMock.mock.calls.filter(([u]) => u === '/api/transfers')).toHaveLength(1)
    })
  })
})
