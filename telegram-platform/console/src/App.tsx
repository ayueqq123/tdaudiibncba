import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'
import { AuthProvider, useAuth } from '@/lib/auth'
import AppLayout from '@/components/layout/app-layout'
import LoginPage from '@/pages/login'
import HomePage from '@/pages/home'
import AccountsPage from '@/pages/accounts'
import ImportsPage from '@/pages/imports'
import RulesPage from '@/pages/rules'
import DeliveriesPage from '@/pages/deliveries'
import ApprovalsPage from '@/pages/approvals'
import AiBindingsPage from '@/pages/ai-bindings'
import GuidePage from '@/pages/guide'
import LoginUsersPage from '@/pages/login-users'
import CommandsPage from '@/pages/commands'

function Guard() {
  const { user, ready } = useAuth()
  if (!ready) return null
  if (!user) return <Navigate to="/login" replace />
  return <AppLayout />
}

export default function App() {
  return (
    <AuthProvider>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Guard />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/accounts" element={<AccountsPage />} />
            <Route path="/imports" element={<ImportsPage />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/deliveries" element={<DeliveriesPage />} />
            <Route path="/ai-bindings" element={<AiBindingsPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/users" element={<LoginUsersPage />} />
            <Route path="/commands" element={<CommandsPage />} />
            <Route path="/guide" element={<GuidePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </HashRouter>
      <Toaster position="top-center" richColors />
    </AuthProvider>
  )
}
