import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Button, Card, Field, ShieldIcon } from '../components/ui'
import { api } from '../lib/api'
import { errorMessage } from '../lib/errors'
import { checkPassword } from '../lib/password'
import type { AuditEvent } from '../lib/types'

const ACTION_LABELS: Record<string, string> = {
  'auth.login': 'Inicio de sesión',
  'auth.login_password_ok': 'Contraseña correcta (2FA pendiente)',
  'auth.mfa': 'Verificación 2FA',
  'auth.logout': 'Cierre de sesión',
  'auth.lockout': 'Cuenta bloqueada por intentos fallidos',
  'auth.register': 'Registro',
  'auth.password_change': 'Cambio de contraseña',
  'auth.refresh_reuse_detected': 'Posible robo de sesión detectado',
  'mfa.setup_started': 'Configuración 2FA iniciada',
  'mfa.enabled': '2FA activado',
  'mfa.disabled': '2FA desactivado',
  'mfa.disable': 'Intento de desactivar 2FA',
  'transfer.created': 'Transferencia enviada',
  'transfer.denied': 'Transferencia rechazada',
  'account.funded': 'Fondos de prueba',
}

export function SecurityPage() {
  const { user, reloadUser, logout } = useAuth()
  const [events, setEvents] = useState<AuditEvent[]>([])
  const loadEvents = useCallback(() => api<AuditEvent[]>('/audit/me?limit=15').then(setEvents).catch(() => undefined), [])
  useEffect(() => {
    loadEvents()
  }, [loadEvents])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Seguridad</h1>
        <p className="text-sm text-slate-500">Protegé tu cuenta y revisá la actividad reciente.</p>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <MfaCard enabled={!!user?.mfa_enabled} onChange={async () => { await reloadUser(); loadEvents() }} />
        <PasswordCard email={user?.email ?? ''} name={user?.full_name ?? ''} onChanged={() => logout('Contraseña actualizada. Iniciá sesión con la nueva contraseña.')} />
      </div>
      <Card padded={false}>
        <div className="border-b border-slate-100 px-6 py-4">
          <h2 className="font-semibold text-slate-900">Actividad de seguridad</h2>
          <p className="text-xs text-slate-500">Si ves algo que no reconocés, cambiá tu contraseña de inmediato.</p>
        </div>
        <ul className="divide-y divide-slate-100">
          {events.map((ev) => (
            <li key={ev.seq} className="flex items-center justify-between gap-4 px-6 py-3 text-sm">
              <div>
                <p className="font-medium text-slate-900">{ACTION_LABELS[ev.action] ?? ev.action}</p>
                <p className="text-xs text-slate-500">{new Date(ev.ts).toLocaleString('es')} · IP {ev.ip ?? '—'}</p>
              </div>
              <Badge tone={ev.outcome === 'success' ? 'green' : ev.outcome === 'denied' ? 'amber' : 'red'}>
                {ev.outcome === 'success' ? 'OK' : ev.outcome === 'denied' ? 'Rechazado' : 'Fallido'}
              </Badge>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

function MfaCard({ enabled, onChange }: { enabled: boolean; onChange: () => Promise<void> }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [disabling, setDisabling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function run(fn: () => Promise<void>) {
    setError(null)
    setLoading(true)
    try {
      await fn()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const start = () => run(async () => setSetup(await api('/mfa/setup', { method: 'POST' })))
  const enable = (e: FormEvent) => {
    e.preventDefault()
    run(async () => {
      await api('/mfa/enable', { method: 'POST', body: { code } })
      setSetup(null)
      setCode('')
      await onChange()
    })
  }
  const disable = (e: FormEvent) => {
    e.preventDefault()
    run(async () => {
      await api('/mfa/disable', { method: 'POST', body: { password, code } })
      setDisabling(false)
      setPassword('')
      setCode('')
      await onChange()
    })
  }

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className={`grid h-10 w-10 place-items-center rounded-full ${enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            <ShieldIcon />
          </span>
          <div>
            <h2 className="font-semibold text-slate-900">Verificación en dos pasos</h2>
            <p className="text-xs text-slate-500">TOTP (Google Authenticator, 1Password, Authy…)</p>
          </div>
        </div>
        <Badge tone={enabled ? 'green' : 'amber'}>{enabled ? 'Activa' : 'Inactiva'}</Badge>
      </div>
      <div className="mt-5 space-y-4">
        {error && <Alert>{error}</Alert>}
        {!enabled && !setup && <Button onClick={start} loading={loading}>Activar 2FA</Button>}
        {!enabled && setup && (
          <form onSubmit={enable} className="space-y-4">
            <p className="text-sm text-slate-600">1. Escaneá el código QR con tu app autenticadora.</p>
            <div className="flex justify-center rounded-lg bg-white p-4 ring-1 ring-slate-200">
              <QRCodeSVG value={setup.otpauth_uri} size={176} level="M" />
            </div>
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer">¿No podés escanear? Ingresá la clave manualmente</summary>
              <code className="mt-2 block break-all rounded bg-slate-100 p-2 font-mono text-slate-800">{setup.secret}</code>
            </details>
            <Field label="2. Ingresá el código de 6 dígitos" name="mfa-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
            <Button type="submit" loading={loading} disabled={code.length !== 6}>Confirmar y activar</Button>
          </form>
        )}
        {enabled && !disabling && (
          <Button variant="secondary" onClick={() => setDisabling(true)}>Desactivar 2FA</Button>
        )}
        {enabled && disabling && (
          <form onSubmit={disable} className="space-y-4">
            <Alert kind="warning">Desactivar 2FA reduce la seguridad de tu cuenta. Se requieren tu contraseña y un código.</Alert>
            <Field label="Contraseña" name="mfa-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Field label="Código 2FA" name="mfa-disable-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
            <div className="flex gap-3">
              <Button variant="secondary" type="button" onClick={() => setDisabling(false)}>Cancelar</Button>
              <Button variant="danger" type="submit" loading={loading} disabled={!password || code.length !== 6}>Desactivar</Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  )
}

function PasswordCard({ email, name, onChanged }: { email: string; name: string; onChanged: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const strength = checkPassword(next, email, name)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await api('/auth/change-password', { method: 'POST', body: { current_password: current, new_password: next } })
      onChanged() // the server revoked every session, including this one
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <h2 className="font-semibold text-slate-900">Cambiar contraseña</h2>
      <p className="text-xs text-slate-500">Cierra la sesión en todos tus dispositivos.</p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Contraseña actual" name="current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <Field
          label="Nueva contraseña"
          name="new"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          hint={next ? (strength.problems.join(' · ') || `Fortaleza: ${strength.label}`) : 'Mínimo 12 caracteres.'}
        />
        <Button type="submit" loading={loading} disabled={!current || strength.problems.length > 0}>Actualizar contraseña</Button>
      </form>
    </Card>
  )
}
