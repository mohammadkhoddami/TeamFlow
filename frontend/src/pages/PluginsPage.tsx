import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, ExternalLink, Plug, Plus, Puzzle, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, pluginsApi } from '../lib/api'
import { qk, useDirectory, usePlugins } from '../lib/hooks'
import { isAdmin, type PluginCreated, type PluginDirectoryEntry, type PluginRead } from '../lib/types'

interface InstallState {
  entry: PluginDirectoryEntry | null
  webhookUrl: string
  events: string[]
}

const EMPTY_INSTALL: InstallState = { entry: null, webhookUrl: '', events: [] }

export function PluginsPage() {
  const { org, role } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const directory = useDirectory(org.slug)
  const installed = usePlugins(org.slug)
  const admin = isAdmin(role)

  const [install, setInstall] = useState<InstallState>(EMPTY_INSTALL)
  const [created, setCreated] = useState<PluginCreated | null>(null)
  const [uninstalling, setUninstalling] = useState<PluginRead | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.plugins(org.slug) })
    void queryClient.invalidateQueries({ queryKey: qk.pluginDirectory(org.slug) })
  }

  const installPlugin = useMutation({
    mutationFn: () =>
      pluginsApi.install(org.slug, {
        catalog_id: install.entry?.id,
        name: install.entry?.name,
        description: install.entry?.description,
        webhook_url: install.webhookUrl.trim(),
        events: install.events,
      }),
    onSuccess: (plugin) => {
      invalidate()
      setInstall(EMPTY_INSTALL)
      setCreated(plugin)
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not install plugin'),
  })

  const toggle = useMutation({
    mutationFn: (plugin: PluginRead) =>
      pluginsApi.update(org.slug, plugin.id, { is_active: !plugin.is_active }),
    onSuccess: () => {
      invalidate()
      toast.success('Plugin updated')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update plugin'),
  })

  const uninstall = useMutation({
    mutationFn: (plugin: PluginRead) => pluginsApi.remove(org.slug, plugin.id),
    onSuccess: () => {
      invalidate()
      setUninstalling(null)
      toast.success('Plugin uninstalled')
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not uninstall plugin'),
  })

  function openInstall(entry: PluginDirectoryEntry) {
    setInstall({ entry, webhookUrl: '', events: entry.events })
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Plugins</h1>
        <p className="text-sm text-slate-500">
          Extend the workspace with directory apps that receive event webhooks.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
          <Puzzle className="h-4 w-4 text-slate-400" /> Directory
        </h2>
        {directory.isLoading && <PageSpinner />}
        {directory.isError && (
          <ErrorState
            message="Could not load the plugin directory."
            onRetry={() => void directory.refetch()}
          />
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {directory.data?.map((entry) => (
            <Card key={entry.id} className="flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-800">{entry.name}</p>
                  <p className="text-xs text-slate-500">by {entry.author}</p>
                </div>
                {entry.installed && (
                  <Badge className="bg-emerald-100 text-emerald-700">installed</Badge>
                )}
              </div>
              <p className="mt-2 flex-1 text-sm text-slate-600">{entry.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {entry.events.slice(0, 4).map((event) => (
                  <Badge key={event}>{event}</Badge>
                ))}
                {entry.events.length > 4 && <Badge>+{entry.events.length - 4}</Badge>}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <a
                  href={entry.homepage}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  <ExternalLink className="h-3 w-3" /> Homepage
                </a>
                {admin && !entry.installed && (
                  <Button size="sm" onClick={() => openInstall(entry)}>
                    <Plus className="h-3.5 w-3.5" /> Install
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
          <Plug className="h-4 w-4 text-slate-400" /> Installed
        </h2>
        {(installed.data?.length ?? 0) === 0 && (
          <EmptyState
            icon={<Puzzle className="h-8 w-8" />}
            title="No plugins installed"
            description="Install one from the directory to start receiving events."
          />
        )}
        {installed.data?.map((plugin) => (
          <Card key={plugin.id} className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800">
                {plugin.name}
                {!plugin.is_active && <Badge className="ml-2">disabled</Badge>}
              </p>
              <p className="text-xs text-slate-500">
                {plugin.description ?? ''}
                {plugin.webhook_url ? ` · ${plugin.webhook_url}` : ''}
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {plugin.events.map((event) => (
                  <Badge key={event}>{event}</Badge>
                ))}
              </div>
            </div>
            {admin && (
              <div className="flex items-center gap-1">
                <Button size="sm" variant="secondary" onClick={() => toggle.mutate(plugin)}>
                  {plugin.is_active ? 'Disable' : 'Enable'}
                </Button>
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  title="Uninstall"
                  onClick={() => setUninstalling(plugin)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            )}
          </Card>
        ))}
      </section>

      <Modal
        open={Boolean(install.entry)}
        onClose={() => setInstall(EMPTY_INSTALL)}
        title={`Install ${install.entry?.name ?? 'plugin'}`}
        description="Events are delivered as signed webhook POSTs to your endpoint."
        footer={
          <>
            <Button variant="secondary" onClick={() => setInstall(EMPTY_INSTALL)}>
              Cancel
            </Button>
            <Button
              onClick={() => installPlugin.mutate()}
              loading={installPlugin.isPending}
              disabled={!install.webhookUrl.trim()}
            >
              Install
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Webhook URL" hint="Where TeamFlow POSTs plugin events">
            <Input
              autoFocus
              value={install.webhookUrl}
              onChange={(event) =>
                setInstall({ ...install, webhookUrl: event.target.value })
              }
              placeholder="https://example.com/hooks/teamflow"
            />
          </Field>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">Events</p>
            {(install.entry?.events ?? []).map((event) => (
              <Checkbox
                key={event}
                label={event}
                checked={install.events.includes(event)}
                onChange={(event_) =>
                  setInstall({
                    ...install,
                    events: event_.target.checked
                      ? [...install.events, event]
                      : install.events.filter((entry) => entry !== event),
                  })
                }
              />
            ))}
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(created)}
        onClose={() => setCreated(null)}
        title="Plugin signing secret"
        size="sm"
        footer={<Button onClick={() => setCreated(null)}>Done</Button>}
      >
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Use it to verify webhook signatures. It is never shown again.
          </p>
          <div className="flex items-center gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
            <span className="min-w-0 flex-1 break-all">{created?.secret ?? ''}</span>
            <button
              className="shrink-0 text-slate-400 hover:text-slate-700"
              onClick={() => {
                void navigator.clipboard.writeText(created?.secret ?? '').then(
                  () => toast.success('Copied'),
                  () => toast.error('Could not copy'),
                )
              }}
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(uninstalling)}
        title="Uninstall plugin"
        message={`Uninstall "${uninstalling?.name ?? ''}"? Webhook delivery stops immediately.`}
        busy={uninstall.isPending}
        onClose={() => setUninstalling(null)}
        onConfirm={() => uninstalling && uninstall.mutate(uninstalling)}
      />
    </div>
  )
}
