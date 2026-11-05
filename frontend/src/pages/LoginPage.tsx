import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { AuthShell } from '../components/AuthShell'
import { Alert, Button, Field } from '../components/ui'
import { errorMessage } from '../lib/errors'

export function LoginPage() {
  const { login, verifyMfa, notice, clearNotice } = useAuth()
  const location = useLocation()
  const registered = (location.state as { registered?: boolean } | null)?.registered
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    clearNotice()
    setLoading(true)
    try {
      if (mfaToken) {
        await verifyMfa(mfaToken, code)
      } else {
        const res = await login(email, password)
        if (res.kind === 'mfa') setMfaToken(res.mfaToken)
      }
      setPassword('') // don't keep the secret in component state longer than needed
    } catch (err) {
      setError(errorMessage(err))
      setCode('')
    } finally {
      setLoading(false)
    }
  }

  if (mfaToken) {
    return (
      <AuthShell title="Verificación en dos pasos" subtitle="Ingresá el código de 6 dígitos de tu app autenticadora.">
        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          {error && <Alert>{error}</Alert>}
          <Field
            label="Código"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
          <Button type="submit" className="w-full" loading={loading} disabled={code.length !== 6}>
            Verificar
          </Button>
          <button type="button" className="w-full text-sm text-slate-500 hover:underline" onClick={() => setMfaToken(null)}>
            Volver
          </button>
        </form>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Iniciar sesión" subtitle="Accedé a tu cuenta VaultPay.">
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {notice && <Alert kind="info">{notice}</Alert>}
        {registered && !notice && <Alert kind="success">Registro recibido. Ya podés iniciar sesión.</Alert>}
        {error && <Alert>{error}</Alert>}
        <Field label="Correo electrónico" name="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="Contraseña" name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" className="w-full" loading={loading} disabled={!email || !password}>
          Ingresar
        </Button>
        <p className="text-center text-sm text-slate-500">
          ¿No tenés cuenta?{' '}
          <Link to="/register" className="font-semibold text-teal-700 hover:underline">
            Crear cuenta
          </Link>
        </p>
      </form>
    </AuthShell>
  )
}
