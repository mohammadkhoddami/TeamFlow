import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from './components/AppLayout'
import { OrgLayout } from './components/OrgLayout'
import { GuestRoute, ProtectedRoute } from './components/ProtectedRoute'
import { StandaloneLayout } from './components/StandaloneLayout'
import { AuditPage } from './pages/AuditPage'
import { DashboardPage } from './pages/DashboardPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { InvitationsPage } from './pages/InvitationsPage'
import { LabelsPage } from './pages/LabelsPage'
import { LoginPage } from './pages/LoginPage'
import { MembersPage } from './pages/MembersPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { OAuthCallbackPage } from './pages/OAuthCallbackPage'
import { OrganizationsPage } from './pages/OrganizationsPage'
import { OtpPage } from './pages/OtpPage'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { RegisterPage } from './pages/RegisterPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { SettingsPage } from './pages/SettingsPage'
import { TasksPage } from './pages/TasksPage'
import { UnsubscribePage } from './pages/UnsubscribePage'
import { WebhooksPage } from './pages/WebhooksPage'

export default function App() {
  return (
    <Routes>
      <Route element={<GuestRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/login/otp" element={<OtpPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      </Route>
      {/* Reset / OAuth / unsubscribe links must work even with a session. */}
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/auth/callback" element={<OAuthCallbackPage />} />
      <Route path="/unsubscribe" element={<UnsubscribePage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<StandaloneLayout />}>
          <Route path="/organizations" element={<OrganizationsPage />} />
          <Route path="/invitations" element={<InvitationsPage />} />
        </Route>

        <Route path="/org/:slug" element={<OrgLayout />}>
          <Route element={<AppLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="projects/:projectId" element={<ProjectPage />} />
            <Route path="tasks" element={<TasksPage />} />
            <Route path="members" element={<MembersPage />} />
            <Route path="labels" element={<LabelsPage />} />
            <Route path="webhooks" element={<WebhooksPage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="/" element={<Navigate to="/organizations" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
