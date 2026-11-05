import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Alert, Button, Card, Field } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { errorMessage } from '../lib/errors'
import { formatCents, luhnValid, parseToCents } from '../lib/money'
import type { Account, Meta, Transaction } from '../lib/types'

type Step = 'form' | 'review' | 'done'

const newKey = () => crypto.randomUUID()

export function TransferPage() {
  const { user } = useAuth()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [step, setStep] = useState<Step>('form')
  const [to, setTo] = useState('')
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [otp, setOtp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Transaction | null>(null)
  // SEC-FE-04 / SEC-DATA-05: one idempotency key per *logical* transfer. Retries of the
  // same reviewed transfer reuse it, so a timeout + retry can never pay twice.
  const idemKey = useRef(newKey())

  useEffect(() => {
    Promise.all([api<Account[]>('/accounts'), api<Meta>('/meta', { auth: false })])
      .then(([a, m]) => {
        setAccounts(a)
        setMeta(m)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [])

  const source = accounts[0]
  const cents = parseToCents(amount)
  const toValid = luhnValid(to)
  const needsOtp = !!meta && cents !== null && cents >= meta.step_up_threshold_cents
  const overBalance = !!source && cents !== null && cents > source.balance_cents
  const formValid = !!source && toValid && cents !== null && !overBalance && to !== source.account_number

  function review(e: FormEvent) {
    e.preventDefault()
    setError(null)
    idemKey.current = newKey() // details may have changed -> new logical operation
    setStep('review')
  }

  async function send() {
    if (!source || cents === null || sending) return // guard against double submit
    setSending(true)
    setError(null)
    try {
      const tx = await api<Transaction>('/transfers', {
        method: 'POST',
        headers: { 'Idempotency-Key': idemKey.current },
        body: {
          from_account_id: source.id,
          to_account_number: to,
          amount_cents: cents,
          description: description.trim(),
          ...(needsOtp ? { otp_code: otp } : {}),
        },
      })
      setResult(tx)
      setStep('done')
    } catch (err) {
      setError(errorMessage(err))
      if (err instanceof ApiError && err.code === 'invalid_otp') setOtp('')
    } finally {
      setSending(false)
    }
  }

  function reset() {
    setTo('')
    setAmount('')
    setDescription('')
    setOtp('')
    setResult(null)
    setError(null)
    idemKey.current = newKey()
    setStep('form')
    api<Account[]>('/accounts').then(setAccounts).catch(() => undefined)
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Transferir</h1>
        {source && <p className="text-sm text-slate-500">Disponible: {formatCents(source.balance_cents)}</p>}
      </div>

      {error && <Alert>{error}</Alert>}

      {step === 'form' && (
        <Card>
          <form onSubmit={review} className="space-y-5" noValidate>
            <Field
              label="Cuenta destino"
              name="to"
              inputMode="numeric"
              autoComplete="off"
              maxLength={12}
              placeholder="12 dígitos"
              value={to}
              onChange={(e) => setTo(e.target.value.replace(/\D/g, ''))}
              error={to.length === 12 && !toValid ? 'Número de cuenta inválido (dígito verificador)' : source && to === source.account_number ? 'No podés transferirte a vos mismo' : undefined}
            />
            <Field
              label="Monto (USD)"
              name="amount"
              inputMode="decimal"
              autoComplete="off"
              placeholder="0.00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              error={amount && cents === null ? 'Monto inválido (máximo 2 decimales)' : overBalance ? 'Fondos insuficientes' : undefined}
              hint={meta ? `Desde ${formatCents(meta.step_up_threshold_cents)} se requiere tu código 2FA. Máximo por operación: ${formatCents(meta.max_transfer_cents)}.` : undefined}
            />
            <Field label="Concepto (opcional)" name="description" maxLength={140} value={description} onChange={(e) => setDescription(e.target.value)} />
            {needsOtp && !user?.mfa_enabled && (
              <Alert kind="warning">
                Para enviar este monto tenés que activar la verificación en dos pasos.{' '}
                <Link to="/security" className="font-semibold underline">Ir a Seguridad</Link>
              </Alert>
            )}
            <Button type="submit" className="w-full" disabled={!formValid || (needsOtp && !user?.mfa_enabled)}>
              Continuar
            </Button>
          </form>
        </Card>
      )}

      {step === 'review' && cents !== null && (
        <Card>
          <h2 className="font-semibold text-slate-900">Revisá la operación</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">Destino</dt><dd className="font-mono">{to}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Monto</dt><dd className="text-lg font-semibold">{formatCents(cents)}</dd></div>
            {description && <div className="flex justify-between gap-4"><dt className="text-slate-500">Concepto</dt><dd className="truncate">{description}</dd></div>}
          </dl>
          {needsOtp && (
            <div className="mt-6 rounded-lg bg-amber-50 p-4 ring-1 ring-amber-200">
              <Field
                label="Código de verificación 2FA"
                name="otp"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                disabled={sending}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                hint="Monto alto: confirmá con un código nuevo de tu app autenticadora."
              />
            </div>
          )}
          <div className="mt-6 flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setStep('form')} disabled={sending}>Editar</Button>
            <Button className="flex-1" onClick={send} loading={sending} disabled={needsOtp && otp.length !== 6}>
              Confirmar envío
            </Button>
          </div>
        </Card>
      )}

      {step === 'done' && result && (
        <Card className="text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-emerald-100 text-2xl text-emerald-700">✓</div>
          <h2 className="mt-4 text-lg font-semibold text-slate-900">Transferencia enviada</h2>
          <p className="mt-1 text-sm text-slate-500">
            {formatCents(result.amount_cents)} a {result.to_account}
          </p>
          <p className="mt-2 font-mono text-xs text-slate-400">Comprobante {result.id}</p>
          <div className="mt-6 flex justify-center gap-3">
            <Button variant="secondary" onClick={reset}>Nueva transferencia</Button>
            <Link to="/" className="inline-flex items-center rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800">Ir al inicio</Link>
          </div>
        </Card>
      )}
    </div>
  )
}
