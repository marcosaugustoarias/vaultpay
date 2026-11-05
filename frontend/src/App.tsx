import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { SecurityPage } from './pages/SecurityPage'
import { TransferPage } from './pages/TransferPage'

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center bg-slate-50" aria-busy>
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-teal-700 border-t-transparent" />
    </div>
  )
}

/** Route guards are UX only. Authorisation is enforced by the API on every request. */
export default function App() {
  const { status } = useAuth()
  if (status === 'loading') return <Splash />
  const authed = status === 'authenticated'

  return (
    <Routes>
      <Route path="/login" element={authed ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={authed ? <Navigate to="/" replace /> : <RegisterPage />} />
      <Route element={authed ? <Layout /> : <Navigate to="/login" replace />}>
        <Route index element={<DashboardPage />} />
        <Route path="transfer" element={<TransferPage />} />
        <Route path="security" element={<SecurityPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
