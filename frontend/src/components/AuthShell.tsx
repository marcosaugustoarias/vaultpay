import type { ReactNode } from 'react'
import { ShieldIcon } from './ui'

export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-gradient-to-br from-teal-800 to-slate-900 p-12 text-teal-50 lg:flex">
        <div className="flex items-center gap-2 text-lg font-bold">
          <ShieldIcon className="h-7 w-7" /> VaultPay
        </div>
        <div className="space-y-6">
          <h2 className="text-3xl font-semibold leading-tight text-white">Tu dinero, protegido por diseño.</h2>
          <ul className="space-y-3 text-sm text-teal-100">
            <li>• Verificación en dos pasos y autenticación reforzada para montos altos</li>
            <li>• Datos sensibles cifrados con AES-256-GCM</li>
            <li>• Libro mayor de doble entrada inmutable y auditable</li>
            <li>• Cierre de sesión automático por inactividad</li>
          </ul>
        </div>
        <p className="text-xs text-teal-200/70">Entorno sandbox — no utilices datos reales.</p>
      </aside>
      <main className="flex items-center justify-center bg-slate-50 px-4 py-12">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-2 font-bold text-slate-900 lg:hidden">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700 text-white">
              <ShieldIcon className="h-5 w-5" />
            </span>
            VaultPay
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </main>
    </div>
  )
}
