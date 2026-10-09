import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
import { MfaSection } from '../components/settings/MfaSection'
import { PushSection } from '../components/settings/PushSection'
import { RolesSection } from '../components/settings/RolesSection'
import { ScimSection } from '../components/settings/ScimSection'
import { SsoSection } from '../components/settings/SsoSection'
import {
  Button,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  ErrorState,
  Field,
  Input,
  Select,
} from '../components/ui'
import { useAuth } from '../contexts/auth'
import { useToast } from '../contexts/toast'
import {
  ApiError,
  auditApi,
  authApi,
  dataApi,
  organizationsApi,
  preferencesApi,
} from '../lib/api'
import { applyAccent, isValidAccent } from '../lib/accent'
import { qk, useNotificationPreferences, useProjects } from '../lib/hooks'
import { translate, useI18n, type Locale } from '../lib/i18n'
import {
  isAdmin,
  isOwner,
  ROLE_LABELS,
  type ImportSummary,
  type NotificationPreferenceRead,
} from '../lib/types'

export function SettingsPage() {
  const { org, role } = useOrg()
  const { user, updateProfile, logout } = useAuth()
  const { locale, setLocale, t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const roleLabel = t(`role.${role}`, ROLE_LABELS[role])

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [orgName, setOrgName] = useState(org.name)
  const [accentColor, setAccentColor] = useState(org.accent_color ?? '#4f46e5')
  const [auditRetention, setAuditRetention] = useState(
    org.audit_retention_days ? String(org.audit_retention_days) : '',
  )
  const [confirmDeleteOrg, setConfirmDeleteOrg] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [orgError, setOrgError] = useState<string | null>(null)

  // Leaving the page without saving must not keep the previewed accent.
  useEffect(() => {
    return () => applyAccent(org.accent_color)
  }, [org.accent_color])

  const saveProfile = useMutation({
    mutationFn: () => updateProfile({ full_name: fullName.trim(), email: email.trim() }),
    onSuccess: () => {
      setProfileError(null)
      toast.success(t('settings.profileUpdated', 'Profile updated'))
    },
    onError: (err) =>
      setProfileError(
        err instanceof ApiError ? err.message : t('settings.couldNotUpdateProfile', 'Could not update profile'),
      ),
  })

  const saveOrg = useMutation({
    mutationFn: () =>
      organizationsApi.update(org.slug, {
        name: orgName.trim(),
        accent_color: isValidAccent(accentColor) ? accentColor : null,
        audit_retention_days: auditRetention ? Number(auditRetention) : null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs })
      setOrgError(null)
      toast.success(t('settings.workspaceUpdated', 'Workspace updated'))
    },
    onError: (err) => {
      applyAccent(org.accent_color)
      setOrgError(
        err instanceof ApiError ? err.message : t('settings.couldNotUpdateWorkspace', 'Could not update workspace'),
      )
    },
  })

  const deleteOrg = useMutation({
    mutationFn: () => organizationsApi.remove(org.slug),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs })
      toast.success(t('settings.workspaceDeleted', 'Workspace deleted'))
      navigate('/organizations', { replace: true })
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('settings.couldNotDeleteWorkspace', 'Could not delete workspace'),
      ),
  })

  const logoutAll = useMutation({
    mutationFn: authApi.logoutAll,
    onSuccess: () => {
      toast.success(t('settings.sessionsRevoked', 'All sessions revoked'))
      void logout()
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('settings.couldNotRevokeSessions', 'Could not revoke sessions'),
      ),
  })

  const projects = useProjects(org.slug)
  const [importProject, setImportProject] = useState('')
  const [importFormat, setImportFormat] = useState('csv')
  const [importDryRun, setImportDryRun] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null)

  const runImport = useMutation({
    mutationFn: () =>
      dataApi.importFile(org.slug, {
        project_id: importProject,
        format: importFormat,
        dry_run: importDryRun,
        file: importFile as File,
      }),
    onSuccess: (summary) => {
      setImportSummary(summary)
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug] })
      toast.success(
        summary.dry_run
          ? t('settings.dryRunImport', 'Dry run: would import {count} tasks', {
              count: summary.created_tasks,
            })
          : t('settings.importedTasks', 'Imported {count} tasks', {
              count: summary.created_tasks,
            }),
      )
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('settings.importFailed', 'Import failed')),
  })

  const preferences = useNotificationPreferences()
  const savePreferences = useMutation({
    mutationFn: (data: Partial<NotificationPreferenceRead>) => preferencesApi.update(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.preferences })
      toast.success(t('settings.preferencesSaved', 'Notification preferences saved'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('settings.couldNotSavePreferences', 'Could not save preferences'),
      ),
  })
  const prefs = preferences.data

  const retentionValid =
    auditRetention === '' ||
    (Number.isInteger(Number(auditRetention)) &&
      Number(auditRetention) >= 1 &&
      Number(auditRetention) <= 3650)

  return (
    <div className="max-w-3xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">
          {t('settings.title', 'Settings')}
        </h1>
        <p className="text-sm text-slate-500">
          {t('settings.subtitle', 'Your profile and the workspace.')}
        </p>
      </div>

      <Card>
        <CardHeader
          title={t('settings.profile', 'Your profile')}
          description={t('settings.signedInAs', 'Signed in as {role} of {workspace}', {
            role: roleLabel,
            workspace: org.name,
          })}
        />
        <div className="space-y-4 p-5">
          {profileError && <ErrorState message={profileError} />}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('auth.fullName', 'Full name')}>
              <Input
                value={fullName}
                maxLength={255}
                onChange={(event) => setFullName(event.target.value)}
              />
            </Field>
            <Field label={t('auth.email', 'Email')}>
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => saveProfile.mutate()}
              loading={saveProfile.isPending}
              disabled={!email.trim()}
            >
              {t('settings.saveProfile', 'Save profile')}
            </Button>
          </div>
        </div>
      </Card>

      <MfaSection />

      <Card>
        <CardHeader
          title={t('settings.language', 'Language & calendar')}
          description={t(
            'settings.languageDescription',
            'Interface language and the calendar used for dates.',
          )}
        />
        <div className="space-y-4 p-5">
          <Field
            label={t('settings.languageLabel', 'Language')}
            hint={t('settings.languageHint', 'Persian switches the app to RTL and the Jalali calendar.')}
          >
            <Select
              className="max-w-xs"
              value={locale}
              onChange={(event) => {
                const next = event.target.value as Locale
                setLocale(next)
                toast.success(
                  translate(
                    next,
                    next === 'fa' ? 'settings.languageChangedFa' : 'settings.languageChangedEn',
                  ),
                )
              }}
            >
              <option value="en">English</option>
              <option value="fa">فارسی</option>
            </Select>
          </Field>
        </div>
      </Card>

      <PushSection />

      <Card>
        <CardHeader
          title={t('settings.sessions', 'Sessions')}
          description={t(
            'settings.sessionsDescription',
            'Access tokens are short-lived; refresh tokens live on the server.',
          )}
        />
        <div className="flex items-center justify-between gap-3 p-5">
          <p className="text-sm text-slate-600">
            {t(
              'settings.sessionsRevokeHint',
              'Revoke every refresh token for your account, on all devices.',
            )}
          </p>
          <Button
            variant="danger"
            onClick={() => logoutAll.mutate()}
            loading={logoutAll.isPending}
          >
            {t('settings.logOutEverywhere', 'Log out everywhere')}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader
          title={t('settings.importExport', 'Import & export')}
          description={t(
            'settings.importExportDescription',
            'Migrate from Jira/Trello/Asana/CSV, or take your whole workspace with you.',
          )}
        />
        <div className="space-y-4 p-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t('settings.targetProject', 'Target project')}>
              <Select value={importProject} onChange={(event) => setImportProject(event.target.value)}>
                <option value="">{t('settings.selectProject', 'Select project…')}</option>
                {(projects.data ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('settings.format', 'Format')}>
              <Select value={importFormat} onChange={(event) => setImportFormat(event.target.value)}>
                <option value="csv">{t('settings.formatGenericCsv', 'Generic CSV')}</option>
                <option value="jira_csv">{t('settings.formatJiraCsv', 'Jira CSV')}</option>
                <option value="asana_csv">{t('settings.formatAsanaCsv', 'Asana CSV')}</option>
                <option value="trello_json">{t('settings.formatTrelloJson', 'Trello JSON')}</option>
              </Select>
            </Field>
            <Field label={t('settings.file', 'File')} hint={t('settings.fileHint', 'UTF-8, max 10 MB')}>
              <Input
                type="file"
                accept=".csv,.json,text/csv,application/json"
                onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              />
            </Field>
          </div>
          <Checkbox
            label={t('settings.dryRunOption', 'Dry run (parse and validate without writing)')}
            checked={importDryRun}
            onChange={(event) => setImportDryRun(event.target.checked)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => runImport.mutate()}
              loading={runImport.isPending}
              disabled={!importProject || !importFile}
            >
              {t('settings.importTasks', 'Import tasks')}
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                void dataApi
                  .downloadWorkspace(org.slug)
                  .catch(() =>
                    toast.error(t('settings.couldNotExportWorkspace', 'Could not export workspace')),
                  )
              }
            >
              {t('settings.exportWorkspaceJson', 'Export workspace (JSON)')}
            </Button>
          </div>
          {importSummary && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <p className="font-medium text-slate-700">
                {importSummary.dry_run
                  ? t(
                      'settings.importSummaryDryRun',
                      'Dry run — {rows} rows, {tasks} tasks, {labels} labels, {skipped} skipped',
                      {
                        rows: importSummary.rows,
                        tasks: importSummary.created_tasks,
                        labels: importSummary.created_labels,
                        skipped: importSummary.skipped,
                      },
                    )
                  : t(
                      'settings.importSummary',
                      'Import — {rows} rows, {tasks} tasks, {labels} labels, {skipped} skipped',
                      {
                        rows: importSummary.rows,
                        tasks: importSummary.created_tasks,
                        labels: importSummary.created_labels,
                        skipped: importSummary.skipped,
                      },
                    )}
              </p>
              {importSummary.issues.slice(0, 5).map((issue) => (
                <p key={issue.row} className="mt-0.5 text-amber-700">
                  {t('settings.rowIssue', 'Row {row}: {message}', {
                    row: issue.row,
                    message: issue.message,
                  })}
                </p>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader
          title={t('settings.emailNotifications', 'Email notifications')}
          description={t(
            'settings.emailNotificationsDescription',
            'Choose which events email you. In-app notifications are always recorded.',
          )}
        />
        <div className="space-y-4 p-5">
          {prefs && (
            <>
              <Checkbox
                label={t('settings.emailEnabled', 'Send me email notifications')}
                checked={prefs.email_enabled}
                onChange={(event) =>
                  savePreferences.mutate({ email_enabled: event.target.checked })
                }
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Checkbox
                  label={t('settings.emailAssigned', 'Task assigned to me')}
                  checked={prefs.assigned}
                  onChange={(event) =>
                    savePreferences.mutate({ assigned: event.target.checked })
                  }
                />
                <Checkbox
                  label={t('settings.emailMentioned', 'I am @mentioned')}
                  checked={prefs.mentioned}
                  onChange={(event) =>
                    savePreferences.mutate({ mentioned: event.target.checked })
                  }
                />
                <Checkbox
                  label={t('settings.emailComments', 'Comments on tasks I watch')}
                  checked={prefs.comments}
                  onChange={(event) =>
                    savePreferences.mutate({ comments: event.target.checked })
                  }
                />
                <Checkbox
                  label={t('settings.emailDue', 'Tasks due soon')}
                  checked={prefs.due}
                  onChange={(event) => savePreferences.mutate({ due: event.target.checked })}
                />
              </div>
              <Field
                label={t('settings.delivery', 'Delivery')}
                hint={t('settings.deliveryHint', 'Digests are emailed on the schedule instead of per event')}
              >
                <Select
                  className="max-w-xs"
                  value={prefs.digest}
                  onChange={(event) =>
                    savePreferences.mutate({
                      digest: event.target.value as NotificationPreferenceRead['digest'],
                    })
                  }
                >
                  <option value="immediate">
                    {t('settings.digestImmediate', 'Immediately (per event)')}
                  </option>
                  <option value="daily">{t('settings.digestDaily', 'Daily digest')}</option>
                  <option value="weekly">{t('settings.digestWeekly', 'Weekly digest')}</option>
                  <option value="off">{t('settings.digestOff', 'Off')}</option>
                </Select>
              </Field>
            </>
          )}
          {preferences.isLoading && (
            <p className="text-xs text-slate-400">
              {t('settings.loadingPreferences', 'Loading preferences…')}
            </p>
          )}
        </div>
      </Card>

      {isAdmin(role) && (
        <Card>
          <CardHeader
            title={t('settings.workspace', 'Workspace')}
            description={t(
              'settings.workspaceDescription',
              'Admins can rename and theme the workspace; only the owner can delete it.',
            )}
          />
          <div className="space-y-4 p-5">
            {orgError && <ErrorState message={orgError} />}
            <Field label={t('settings.workspaceName', 'Workspace name')}>
              <Input value={orgName} maxLength={255} onChange={(event) => setOrgName(event.target.value)} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label={t('settings.accentColor', 'Accent color')}
                hint={t('settings.accentColorHint', 'Used across buttons, links and highlights')}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    className="h-9 w-12 cursor-pointer rounded border border-slate-300 bg-white p-0.5"
                    value={isValidAccent(accentColor) ? accentColor : '#4f46e5'}
                    onChange={(event) => {
                      setAccentColor(event.target.value)
                      applyAccent(event.target.value)
                    }}
                  />
                  <Input
                    value={accentColor}
                    maxLength={7}
                    onChange={(event) => {
                      setAccentColor(event.target.value)
                      if (isValidAccent(event.target.value)) applyAccent(event.target.value)
                    }}
                    placeholder="#4f46e5"
                  />
                </div>
              </Field>
              <Field
                label={t('settings.auditRetention', 'Audit retention (days)')}
                hint={t(
                  'settings.auditRetentionHint',
                  'Audit rows older than this are purged; empty keeps them forever',
                )}
                error={
                  retentionValid
                    ? null
                    : t('settings.auditRetentionError', 'Enter a number between 1 and 3650')
                }
              >
                <Input
                  type="number"
                  min={1}
                  max={3650}
                  value={auditRetention}
                  onChange={(event) => setAuditRetention(event.target.value)}
                />
              </Field>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-slate-500">/{org.slug}</p>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setAccentColor(org.accent_color ?? '#4f46e5')
                    applyAccent(org.accent_color)
                  }}
                >
                  {t('settings.resetPreview', 'Reset preview')}
                </Button>
                <Button
                  onClick={() => saveOrg.mutate()}
                  loading={saveOrg.isPending}
                  disabled={!orgName.trim() || !retentionValid}
                >
                  {t('settings.saveWorkspace', 'Save workspace')}
                </Button>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
              <p className="text-sm font-medium text-slate-700">
                {t('settings.auditExport', 'Audit export')}
              </p>
              <p className="text-xs text-slate-500">
                {t(
                  'settings.auditExportHint',
                  'Hash-chained export for compliance reviews (up to 5000 rows).',
                )}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void auditApi
                      .downloadExport(org.slug, 'csv')
                      .catch(() =>
                        toast.error(t('settings.couldNotExportAudit', 'Could not export audit log')),
                      )
                  }
                >
                  <Download className="h-3.5 w-3.5" /> {t('settings.exportCsv', 'Export CSV')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void auditApi
                      .downloadExport(org.slug, 'json')
                      .catch(() =>
                        toast.error(t('settings.couldNotExportAudit', 'Could not export audit log')),
                      )
                  }
                >
                  <Download className="h-3.5 w-3.5" /> {t('settings.exportJson', 'Export JSON')}
                </Button>
              </div>
            </div>

            {isOwner(role) && (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-3">
                <div>
                  <p className="text-sm font-medium text-red-800">
                    {t('settings.deleteWorkspace', 'Delete workspace')}
                  </p>
                  <p className="text-xs text-red-600">
                    {t(
                      'settings.deleteWorkspaceWarning',
                      'Projects, tasks and members will be permanently removed.',
                    )}
                  </p>
                </div>
                <Button variant="danger" size="sm" onClick={() => setConfirmDeleteOrg(true)}>
                  {t('common.delete', 'Delete')}
                </Button>
              </div>
            )}
          </div>
        </Card>
      )}

      {isAdmin(role) && <SsoSection />}
      {isAdmin(role) && <ScimSection />}
      {isAdmin(role) && <RolesSection />}

      <ConfirmDialog
        open={confirmDeleteOrg}
        title={t('settings.deleteWorkspace', 'Delete workspace')}
        message={t(
          'settings.deleteWorkspaceConfirm',
          'Delete "{name}" and everything inside it? This cannot be undone.',
          { name: org.name },
        )}
        confirmLabel={t('settings.deleteWorkspace', 'Delete workspace')}
        busy={deleteOrg.isPending}
        onClose={() => setConfirmDeleteOrg(false)}
        onConfirm={() => deleteOrg.mutate()}
      />
    </div>
  )
}
