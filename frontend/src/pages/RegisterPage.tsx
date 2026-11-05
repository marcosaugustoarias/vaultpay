import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthShell } from '../components/AuthShell'
import { Alert, Button, Field } from '../components/ui'
import { api } from '../lib/api'
import { errorMessage } from '../lib/errors'
import { checkPassword } from '../lib/password'

const BAR = ['bg-rose-500', 'bg-amber-500', 'bg-teal-500', 'bg-emerald-600']

export function RegisterPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const strength = checkPassword(form.password, form.email, form.full_name)
  const mismatch = form.confirm.length > 0 && form.confirm !== form.password
  const canSubmit = form.full_name.trim().length >= 2 && form.email && strength.problems.length === 0 && !mismatch && form.confirm

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await api('/auth/register', {
        method: 'POST',
        auth: false,
        body: { full_name: form.full_name, email: form.email, password: form.password },
      })
      // The server answers identically for new and existing e-mails (anti-enumeration).
      navigate('/login', { replace: true, state: { registered: true } })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthShell title="Crear cuenta" subtitle="Abrí tu cuenta en menos de un minuto.">
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {error && <Alert>{error}</Alert>}
        <Field label="Nombre completo" name="full_name" autoComplete="name" maxLength={120} value={form.full_name} onChange={set('full_name')} />
        <Field label="Correo electrónico" name="email" type="email" autoComplete="email" value={form.email} onChange={set('email')} />
        <div>
          <Field
            label="Contraseña"
            name="password"
            type="password"
            autoComplete="new-password"
            maxLength={128}
            value={form.password}
            onChange={set('password')}
            hint="Usá una frase larga y única (12+ caracteres). Un gestor de contraseñas es ideal."
          />
          {form.password && (
            <div className="mt-2" aria-live="polite">
              <div className="flex gap-1">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className={`h-1.5 flex-1 rounded ${i <= strength.score && strength.problems.length === 0 ? BAR[strength.score] : 'bg-slate-200'}`} />
                ))}
              </div>
              <p className="mt-1 text-xs text-slate-600">
                {strength.problems.length ? strength.problems.join(' · ') : `Fortaleza: ${strength.label}`}
              </p>
            </div>
          )}
        </div>
        <Field
          label="Repetir contraseña"
          name="confirm"
          type="password"
          autoComplete="new-password"
          value={form.confirm}
          onChange={set('confirm')}
          error={mismatch ? 'Las contraseñas no coinciden' : undefined}
        />
        <Button type="submit" className="w-full" loading={loading} disabled={!canSubmit}>
          Crear cuenta
        </Button>
        <p className="text-center text-sm text-slate-500">
          ¿Ya tenés cuenta?{' '}
          <Link to="/login" className="font-semibold text-teal-700 hover:underline">
            Iniciar sesión
          </Link>
        </p>
      </form>
    </AuthShell>
  )
}
