import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useIdleTimeout } from '../auth/useIdleTimeout'
import { Button, ShieldIcon } from './ui'

const IDLE_MS = 5 * 60_000
const WARN_MS = 30_000

export function Layout() {
  const { user, logout } = useAuth()
  const { remainingMs, stayActive } = useIdleTimeout(
    IDLE_MS,
    WARN_MS,
    () => logout('Cerramos tu sesión por inactividad.'),
    !!user,
  )

  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-100'}`

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2 font-bold text-slate-900">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700 text-white">
              <ShieldIcon className="h-5 w-5" />
            </span>
            VaultPay
          </div>
          <nav className="flex gap-1" aria-label="Principal">
            <NavLink to="/" end className={link}>Inicio</NavLink>
            <NavLink to="/transfer" className={link}>Transferir</NavLink>
            <NavLink to="/security" className={link}>Seguridad</NavLink>
          </nav>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-500 sm:inline">{user?.full_name}</span>
            <Button variant="secondary" onClick={() => logout()}>Salir</Button>
          </div>
        </div>
      </header>

      {remainingMs !== null && (
        <div role="alertdialog" aria-live="assertive" className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
          Tu sesión se cerrará por inactividad en {Math.ceil(remainingMs / 1000)}s.{' '}
          <button className="font-semibold underline" onClick={stayActive}>Seguir conectado</button>
        </div>
      )}

      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
