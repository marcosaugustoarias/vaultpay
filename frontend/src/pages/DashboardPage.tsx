import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Button, Card } from '../components/ui'
import { api } from '../lib/api'
import { errorMessage } from '../lib/errors'
import { formatCents, maskNumber } from '../lib/money'
import type { Account, LedgerEntry, LedgerPage, Meta } from '../lib/types'

export function DashboardPage() {
  const { user } = useAuth()
  const [account, setAccount] = useState<Account | null>(null)
  const [entries, setEntries] = useState<LedgerEntry[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [reveal, setReveal] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [funding, setFunding] = useState(false)

  const load = useCallback(async () => {
    try {
      const [accounts, m] = await Promise.all([api<Account[]>('/accounts'), api<Meta>('/meta', { auth: false })])
      setMeta(m)
      const acct = accounts[0] ?? null
      setAccount(acct)
      if (acct) {
        const page = await api<LedgerPage>(`/accounts/${encodeURIComponent(acct.id)}/transactions?limit=10`)
        setEntries(page.items)
        setCursor(page.next_cursor)
      }
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function loadMore() {
    if (!account || !cursor) return
    const page = await api<LedgerPage>(`/accounts/${encodeURIComponent(account.id)}/transactions?limit=10&cursor=${cursor}`)
    setEntries((prev) => [...prev, ...page.items])
    setCursor(page.next_cursor)
  }

  async function fund(cents: number) {
    if (!account) return
    setFunding(true)
    setError(null)
    try {
      await api(`/accounts/${encodeURIComponent(account.id)}/fund`, { method: 'POST', body: { amount_cents: cents } })
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setFunding(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Hola, {user?.full_name.split(' ')[0]}</h1>
        <p className="text-sm text-slate-500">Resumen de tu cuenta</p>
      </div>

      {error && <Alert>{error}</Alert>}
      {user && !user.mfa_enabled && (
        <Alert kind="warning">
          Activá la verificación en dos pasos para proteger tu cuenta y poder enviar montos altos.{' '}
          <Link to="/security" className="font-semibold underline">Activar ahora</Link>
        </Alert>
      )}

      {account && (
        <div className="grid gap-6 md:grid-cols-3">
          <div className="rounded-2xl bg-gradient-to-br from-teal-700 to-teal-900 p-6 text-white shadow-md md:col-span-2">
            <p className="text-sm text-teal-100">Saldo disponible</p>
            <p className="mt-2 text-4xl font-bold tracking-tight" data-testid="balance">
              {formatCents(account.balance_cents, account.currency)}
            </p>
            <div className="mt-6 flex items-center gap-3 text-sm text-teal-100">
              <span className="font-mono">{reveal ? account.account_number : maskNumber(account.account_number)}</span>
              <button onClick={() => setReveal((r) => !r)} className="rounded bg-white/10 px-2 py-0.5 text-xs hover:bg-white/20">
                {reveal ? 'Ocultar' : 'Mostrar número'}
              </button>
            </div>
            <div className="mt-6">
              <Link to="/transfer" className="inline-flex rounded-lg bg-white px-4 py-2 text-sm font-semibold text-teal-800 hover:bg-teal-50">
                Transferir dinero
              </Link>
            </div>
          </div>

          {meta?.demo_funding_enabled && (
            <Card>
              <h2 className="font-semibold text-slate-900">Fondos de prueba</h2>
              <p className="mt-1 text-xs text-slate-500">Solo en sandbox. Deshabilitado en producción.</p>
              <div className="mt-4 grid gap-2">
                {[10_000, 50_000, 100_000].map((c) => (
                  <Button key={c} variant="secondary" loading={funding} onClick={() => fund(c)}>
                    + {formatCents(c)}
                  </Button>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      <Card padded={false}>
        <div className="border-b border-slate-100 px-6 py-4">
          <h2 className="font-semibold text-slate-900">Movimientos</h2>
        </div>
        {entries.length === 0 ? (
          <p className="px-6 py-10 text-center text-sm text-slate-500">Todavía no hay movimientos.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {entries.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-4 px-6 py-3">
                <div className="min-w-0">
                  {/* User-controlled text is rendered as text: React escapes it (SEC-FE-02). */}
                  <p className="truncate text-sm font-medium text-slate-900">
                    {e.description || (e.kind === 'deposit' ? 'Depósito' : e.direction === 'debit' ? 'Transferencia enviada' : 'Transferencia recibida')}
                  </p>
                  <p className="text-xs text-slate-500">
                    {e.direction === 'debit' ? 'A' : 'De'} {e.counterparty} · {new Date(e.created_at).toLocaleString('es')}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-sm font-semibold ${e.direction === 'credit' ? 'text-emerald-700' : 'text-slate-900'}`}>
                    {e.direction === 'credit' ? '+' : '−'}
                    {formatCents(e.amount_cents)}
                  </p>
                  <Badge tone="slate">Saldo {formatCents(e.balance_after_cents)}</Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
        {cursor && (
          <div className="border-t border-slate-100 p-4 text-center">
            <Button variant="secondary" onClick={loadMore}>Ver más</Button>
          </div>
        )}
      </Card>
    </div>
  )
}
