import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
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
import { ApiError, authApi, dataApi, organizationsApi, preferencesApi } from '../lib/api'
import { qk, useNotificationPreferences, useProjects } from '../lib/hooks'
import {
  isAdmin,
  isOwner,
  type ImportSummary,
  type NotificationPreferenceRead,
} from '../lib/types'

export function SettingsPage() {
  const { org, role } = useOrg()
  const { user, updateProfile, logout } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [orgName, setOrgName] = useState(org.name)
  const [confirmDeleteOrg, setConfirmDeleteOrg] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [orgError, setOrgError] = useState<string | null>(null)

  const saveProfile = useMutation({
    mutationFn: () => updateProfile({ full_name: fullName.trim(), email: email.trim() }),
    onSuccess: () => {
      setProfileError(null)
      toast.success('Profile updated')
    },
    onError: (err) =>
      setProfileError(err instanceof ApiError ? err.message : 'Could not update profile'),
  })

  const saveOrg = useMutation({
    mutationFn: () => organizationsApi.update(org.slug, { name: orgName.trim() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs })
      setOrgError(null)
      toast.success('Workspace updated')
    },
    onError: (err) => setOrgError(err instanceof ApiError ? err.message : 'Could not update workspace'),
  })

  const deleteOrg = useMutation({
    mutationFn: () => organizationsApi.remove(org.slug),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs })
      toast.success('Workspace deleted')
      navigate('/organizations', { replace: true })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete workspace'),
  })

  const logoutAll = useMutation({
    mutationFn: authApi.logoutAll,
    onSuccess: () => {
      toast.success('All sessions revoked')
      void logout()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not revoke sessions'),
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
          ? `Dry run: would import ${summary.created_tasks} tasks`
          : `Imported ${summary.created_tasks} tasks`,
      )
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Import failed'),
  })

  const preferences = useNotificationPreferences()
  const savePreferences = useMutation({
    mutationFn: (data: Partial<NotificationPreferenceRead>) => preferencesApi.update(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.preferences })
      toast.success('Notification preferences saved')
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not save preferences'),
  })
  const prefs = preferences.data

  return (
    <div className="max-w-3xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">Your profile and the {org.name} workspace.</p>
      </div>

      <Card>
        <CardHeader title="Your profile" description={`Signed in as ${role} of ${org.name}`} />
        <div className="space-y-4 p-5">
          {profileError && <ErrorState message={profileError} />}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name">
              <Input
                value={fullName}
                maxLength={255}
                onChange={(event) => setFullName(event.target.value)}
              />
            </Field>
            <Field label="Email">
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
              Save profile
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Sessions"
          description="Access tokens are short-lived; refresh tokens live on the server."
        />
        <div className="flex items-center justify-between gap-3 p-5">
          <p className="text-sm text-slate-600">
            Revoke every refresh token for your account, on all devices.
          </p>
          <Button
            variant="danger"
            onClick={() => logoutAll.mutate()}
            loading={logoutAll.isPending}
          >
            Log out everywhere
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Import & export"
          description="Migrate from Jira/Trello/Asana/CSV, or take your whole workspace with you."
        />
        <div className="space-y-4 p-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Target project">
              <Select value={importProject} onChange={(event) => setImportProject(event.target.value)}>
                <option value="">Select project…</option>
                {(projects.data ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Format">
              <Select value={importFormat} onChange={(event) => setImportFormat(event.target.value)}>
                <option value="csv">Generic CSV</option>
                <option value="jira_csv">Jira CSV</option>
                <option value="asana_csv">Asana CSV</option>
                <option value="trello_json">Trello JSON</option>
              </Select>
            </Field>
            <Field label="File" hint="UTF-8, max 10 MB">
              <Input
                type="file"
                accept=".csv,.json,text/csv,application/json"
                onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              />
            </Field>
          </div>
          <Checkbox
            label="Dry run (parse and validate without writing)"
            checked={importDryRun}
            onChange={(event) => setImportDryRun(event.target.checked)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => runImport.mutate()}
              loading={runImport.isPending}
              disabled={!importProject || !importFile}
            >
              Import tasks
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                void dataApi
                  .downloadWorkspace(org.slug)
                  .catch(() => toast.error('Could not export workspace'))
              }
            >
              Export workspace (JSON)
            </Button>
          </div>
          {importSummary && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <p className="font-medium text-slate-700">
                {importSummary.dry_run ? 'Dry run' : 'Import'} — {importSummary.rows} rows,{' '}
                {importSummary.created_tasks} tasks, {importSummary.created_labels} labels,{' '}
                {importSummary.skipped} skipped
              </p>
              {importSummary.issues.slice(0, 5).map((issue) => (
                <p key={issue.row} className="mt-0.5 text-amber-700">
                  Row {issue.row}: {issue.message}
                </p>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Email notifications"
          description="Choose which events email you. In-app notifications are always recorded."
        />
        <div className="space-y-4 p-5">
          {prefs && (
            <>
              <Checkbox
                label="Send me email notifications"
                checked={prefs.email_enabled}
                onChange={(event) =>
                  savePreferences.mutate({ email_enabled: event.target.checked })
                }
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Checkbox
                  label="Task assigned to me"
                  checked={prefs.assigned}
                  onChange={(event) =>
                    savePreferences.mutate({ assigned: event.target.checked })
                  }
                />
                <Checkbox
                  label="I am @mentioned"
                  checked={prefs.mentioned}
                  onChange={(event) =>
                    savePreferences.mutate({ mentioned: event.target.checked })
                  }
                />
                <Checkbox
                  label="Comments on tasks I watch"
                  checked={prefs.comments}
                  onChange={(event) =>
                    savePreferences.mutate({ comments: event.target.checked })
                  }
                />
                <Checkbox
                  label="Tasks due soon"
                  checked={prefs.due}
                  onChange={(event) => savePreferences.mutate({ due: event.target.checked })}
                />
              </div>
              <Field label="Delivery" hint="Digests are emailed on the schedule instead of per event">
                <Select
                  className="max-w-xs"
                  value={prefs.digest}
                  onChange={(event) =>
                    savePreferences.mutate({
                      digest: event.target.value as NotificationPreferenceRead['digest'],
                    })
                  }
                >
                  <option value="immediate">Immediately (per event)</option>
                  <option value="daily">Daily digest</option>
                  <option value="weekly">Weekly digest</option>
                  <option value="off">Off</option>
                </Select>
              </Field>
            </>
          )}
          {preferences.isLoading && (
            <p className="text-xs text-slate-400">Loading preferences…</p>
          )}
        </div>
      </Card>

      {isAdmin(role) && (
        <Card>
          <CardHeader
            title="Workspace"
            description="Admins can rename the workspace; only the owner can delete it."
          />
          <div className="space-y-4 p-5">
            {orgError && <ErrorState message={orgError} />}
            <Field label="Workspace name">
              <Input value={orgName} maxLength={255} onChange={(event) => setOrgName(event.target.value)} />
            </Field>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">/{org.slug}</p>
              <Button
                onClick={() => saveOrg.mutate()}
                loading={saveOrg.isPending}
                disabled={!orgName.trim()}
              >
                Save workspace
              </Button>
            </div>

            {isOwner(role) && (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-3">
                <div>
                  <p className="text-sm font-medium text-red-800">Delete workspace</p>
                  <p className="text-xs text-red-600">
                    Projects, tasks and members will be permanently removed.
                  </p>
                </div>
                <Button variant="danger" size="sm" onClick={() => setConfirmDeleteOrg(true)}>
                  Delete
                </Button>
              </div>
            )}
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={confirmDeleteOrg}
        title="Delete workspace"
        message={`Delete "${org.name}" and everything inside it? This cannot be undone.`}
        confirmLabel="Delete workspace"
        busy={deleteOrg.isPending}
        onClose={() => setConfirmDeleteOrg(false)}
        onConfirm={() => deleteOrg.mutate()}
      />
    </div>
  )
}
