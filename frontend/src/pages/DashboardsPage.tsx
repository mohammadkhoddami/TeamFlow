import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Gauge, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, dashboardsApi } from '../lib/api'
import { qk, useDashboardData, useDashboards, useProjects } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import {
  STATUS_LABELS,
  WIDGET_TYPES,
  WIDGET_TYPE_LABELS,
  type DashboardRead,
  type DashboardWidget,
  type TaskStatus,
  type WidgetData,
  type WidgetType,
} from '../lib/types'
import { formatDate, relativeTime } from '../lib/utils'

interface BuilderState {
  name: string
  projectId: string
  isDefault: boolean
  widgets: DashboardWidget[]
}

const EMPTY_BUILDER: BuilderState = {
  name: '',
  projectId: '',
  isDefault: false,
  widgets: [],
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? (value.filter((entry) => entry && typeof entry === 'object') as Record<string, unknown>[])
    : []
}

function asNumber(value: unknown): number {
  return typeof value === 'number' ? value : 0
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

const STAT_LABELS: Record<string, string> = {
  projects: 'Projects',
  active_projects: 'Active projects',
  total_tasks: 'Total tasks',
  completed_tasks: 'Completed',
  overdue_tasks: 'Overdue',
  unassigned_tasks: 'Unassigned',
  active_members: 'Active members',
}

function WidgetBody({ widget }: { widget: WidgetData }) {
  const { t } = useI18n()

  if (widget.type === 'stats') {
    const data = asRecord(widget.data)
    return (
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(STAT_LABELS).map(([key, label]) => (
          <div key={key} className="rounded-lg bg-slate-50 px-3 py-2">
            <p className="text-lg font-semibold text-slate-800">{asNumber(data[key])}</p>
            <p className="text-xs text-slate-500">{t(`dashboards.stat.${key}`, label)}</p>
          </div>
        ))}
      </div>
    )
  }

  if (widget.type === 'status') {
    const data = asRecord(widget.data)
    return (
      <ul className="space-y-1.5">
        {Object.keys(STATUS_LABELS).map((key) => (
          <li key={key} className="flex items-center justify-between text-sm">
            <span className="text-slate-600">
              {t(`status.${key}`, STATUS_LABELS[key as TaskStatus])}
            </span>
            <span className="font-medium text-slate-800">{asNumber(data[key])}</span>
          </li>
        ))}
      </ul>
    )
  }

  if (widget.type === 'members') {
    const rows = asRows(widget.data)
    if (rows.length === 0) {
      return <p className="text-sm text-slate-400">{t('dashboards.noAssignedTasks', 'No assigned tasks.')}</p>
    }
    return (
      <ul className="space-y-1.5">
        {rows.map((row, index) => (
          <li key={index} className="flex items-center justify-between text-sm">
            <span className="min-w-0 flex-1 truncate text-slate-600">
              {asText(row.full_name) || t('common.unnamed', 'Unnamed')}
            </span>
            <Badge>
              {t('dashboards.openCount', '{count} open', { count: asNumber(row.open_tasks) })}
            </Badge>
          </li>
        ))}
      </ul>
    )
  }

  if (widget.type === 'overdue') {
    const rows = asRows(widget.data)
    if (rows.length === 0) {
      return <p className="text-sm text-slate-400">{t('dashboards.nothingOverdue', 'Nothing overdue.')}</p>
    }
    return (
      <ul className="space-y-1.5">
        {rows.map((row, index) => (
          <li key={index} className="text-sm">
            <p className="truncate text-slate-700">
              {asText(row.key) ? `${asText(row.key)} · ` : ''}
              {asText(row.title)}
            </p>
            <p className="text-xs text-slate-400">
              {t('dashboards.due', 'due {date}', {
                date: formatDate(asText(row.due_date) || null),
              })}
              {asText(row.assignee) ? ` · ${asText(row.assignee)}` : ''}
            </p>
          </li>
        ))}
      </ul>
    )
  }

  const rows = asRows(widget.data)
  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{t('dashboards.noRecentActivity', 'No recent activity.')}</p>
  }
  return (
    <ul className="space-y-1.5">
      {rows.map((row, index) => (
        <li key={index} className="text-sm">
          <p className="text-slate-700">{asText(row.summary)}</p>
          <p className="text-xs text-slate-400">{relativeTime(asText(row.created_at))}</p>
        </li>
      ))}
    </ul>
  )
}

export function DashboardsPage() {
  const { org } = useOrg()
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const dashboards = useDashboards(org.slug)
  const projects = useProjects(org.slug)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [builderOpen, setBuilderOpen] = useState(false)
  const [editing, setEditing] = useState<DashboardRead | null>(null)
  const [builder, setBuilder] = useState<BuilderState>(EMPTY_BUILDER)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<DashboardRead | null>(null)

  useEffect(() => {
    if (selectedId || !dashboards.data?.length) return
    const preferred =
      dashboards.data.find((entry) => entry.is_default) ?? dashboards.data[0]
    setSelectedId(preferred.id)
  }, [dashboards.data, selectedId])

  const data = useDashboardData(org.slug, selectedId)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.dashboards(org.slug) })
    if (selectedId) {
      void queryClient.invalidateQueries({
        queryKey: qk.dashboardData(org.slug, selectedId),
      })
    }
  }

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: builder.name.trim(),
        project_id: builder.projectId || null,
        is_default: builder.isDefault,
        widgets: builder.widgets.map((widget, index) => ({
          id: widget.id ?? `widget-${index}`,
          type: widget.type,
          title: widget.title.trim(),
          config: widget.config ?? {},
        })),
      }
      return editing
        ? dashboardsApi.update(org.slug, editing.id, payload)
        : dashboardsApi.create(org.slug, payload)
    },
    onSuccess: (dashboard) => {
      invalidate()
      setSelectedId(dashboard.id)
      setBuilderOpen(false)
      setEditing(null)
      setError(null)
      toast.success(
        editing
          ? t('dashboards.updated', 'Dashboard updated')
          : t('dashboards.created', 'Dashboard created'),
      )
    },
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : t('dashboards.saveError', 'Could not save dashboard'),
      ),
  })

  const remove = useMutation({
    mutationFn: (dashboard: DashboardRead) => dashboardsApi.remove(org.slug, dashboard.id),
    onSuccess: () => {
      if (deleting?.id === selectedId) setSelectedId(null)
      invalidate()
      setDeleting(null)
      toast.success(t('dashboards.deleted', 'Dashboard deleted'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('dashboards.deleteError', 'Could not delete dashboard'),
      ),
  })

  function openCreate() {
    setEditing(null)
    setBuilder(EMPTY_BUILDER)
    setError(null)
    setBuilderOpen(true)
  }

  function openEdit(dashboard: DashboardRead) {
    setEditing(dashboard)
    setBuilder({
      name: dashboard.name,
      projectId: dashboard.project_id ?? '',
      isDefault: dashboard.is_default,
      widgets: dashboard.widgets,
    })
    setError(null)
    setBuilderOpen(true)
  }

  const selected = dashboards.data?.find((entry) => entry.id === selectedId) ?? null

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">
            {t('dashboards.title', 'Dashboards')}
          </h1>
          <p className="text-sm text-slate-500">
            {t('dashboards.subtitle', 'Saved widget boards for the workspace or a single project.')}
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" /> {t('dashboards.new', 'New dashboard')}
        </Button>
      </div>

      {dashboards.isLoading && <PageSpinner label={t('dashboards.loading', 'Loading dashboards…')} />}
      {dashboards.isError && (
        <ErrorState
          message={t('dashboards.loadError', 'Could not load dashboards.')}
          onRetry={() => void dashboards.refetch()}
        />
      )}

      {dashboards.data?.length === 0 && (
        <EmptyState
          icon={<Gauge className="h-8 w-8" />}
          title={t('dashboards.emptyTitle', 'No dashboards yet')}
          description={t(
            'dashboards.emptyDescription',
            'Build a board from stats, status, members, overdue and activity widgets.',
          )}
          action={<Button onClick={openCreate}>{t('dashboards.create', 'Create a dashboard')}</Button>}
        />
      )}

      {dashboards.data && dashboards.data.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {dashboards.data.map((dashboard) => (
            <button
              key={dashboard.id}
              type="button"
              onClick={() => setSelectedId(dashboard.id)}
              className={
                dashboard.id === selectedId
                  ? 'rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white'
                  : 'rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50'
              }
            >
              {dashboard.name}
              {dashboard.is_default && (
                <span className="ml-1.5 text-xs opacity-75">
                  {t('dashboards.defaultBadge', 'default')}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-800">{selected.name}</h2>
              <p className="text-xs text-slate-500">
                {selected.project_id
                  ? t('dashboards.projectLabel', 'Project {name}', {
                      name:
                        projects.data?.find((p) => p.id === selected.project_id)?.name ?? '',
                    })
                  : t('dashboards.wholeWorkspace', 'Whole workspace')}
                {selected.is_default
                  ? t('dashboards.defaultSuffix', ' · default dashboard')
                  : ''}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="secondary" onClick={() => openEdit(selected)}>
                <Pencil className="h-3.5 w-3.5" /> {t('common.edit', 'Edit')}
              </Button>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                title={t('dashboards.deleteTitle', 'Delete dashboard')}
                onClick={() => setDeleting(selected)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          {data.isLoading && (
            <PageSpinner label={t('dashboards.loadingData', 'Loading widget data…')} />
          )}
          {data.isError && (
            <ErrorState
              message={t('dashboards.dataError', 'Could not load widget data.')}
              onRetry={() => void data.refetch()}
            />
          )}
          {data.data && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.data.widgets.map((widget) => (
                <Card key={widget.id || widget.title}>
                  <CardHeader
                    title={widget.title}
                    description={t(
                      `widgetType.${widget.type}`,
                      WIDGET_TYPE_LABELS[widget.type as WidgetType] ?? widget.type,
                    )}
                  />
                  <div className="p-5">
                    <WidgetBody widget={widget} />
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      <Modal
        open={builderOpen}
        onClose={() => setBuilderOpen(false)}
        title={
          editing
            ? t('dashboards.edit', 'Edit dashboard')
            : t('dashboards.new', 'New dashboard')
        }
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setBuilderOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!builder.name.trim()}
            >
              {t('dashboards.save', 'Save dashboard')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('common.name', 'Name')}>
              <Input
                autoFocus
                value={builder.name}
                maxLength={128}
                onChange={(event) => setBuilder({ ...builder, name: event.target.value })}
              />
            </Field>
            <Field
              label={t('common.project', 'Project')}
              hint={t('dashboards.projectHint', 'Empty = the whole workspace')}
            >
              <Select
                value={builder.projectId}
                onChange={(event) => setBuilder({ ...builder, projectId: event.target.value })}
              >
                <option value="">{t('dashboards.wholeWorkspace', 'Whole workspace')}</option>
                {(projects.data ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Checkbox
            label={t('dashboards.setDefault', 'Set as default dashboard')}
            checked={builder.isDefault}
            onChange={(event) => setBuilder({ ...builder, isDefault: event.target.checked })}
          />
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700">{t('dashboards.widgets', 'Widgets')}</p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setBuilder({
                    ...builder,
                    widgets: [
                      ...builder.widgets,
                      {
                        id: `widget-${Date.now()}`,
                        type: 'stats',
                        title: t('dashboards.statsWidgetTitle', 'Stats'),
                      },
                    ],
                  })
                }
              >
                <Plus className="h-3.5 w-3.5" /> {t('dashboards.addWidget', 'Add widget')}
              </Button>
            </div>
            {builder.widgets.length === 0 && (
              <p className="text-xs text-slate-400">{t('dashboards.noWidgets', 'No widgets yet.')}</p>
            )}
            {builder.widgets.map((widget, index) => (
              <div key={widget.id ?? index} className="flex items-center gap-2">
                <Select
                  className="w-44"
                  value={widget.type}
                  onChange={(event) =>
                    setBuilder({
                      ...builder,
                      widgets: builder.widgets.map((entry, entryIndex) =>
                        entryIndex === index
                          ? { ...entry, type: event.target.value as WidgetType }
                          : entry,
                      ),
                    })
                  }
                >
                  {WIDGET_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {t(`widgetType.${type}`, WIDGET_TYPE_LABELS[type])}
                    </option>
                  ))}
                </Select>
                <Input
                  value={widget.title}
                  maxLength={128}
                  onChange={(event) =>
                    setBuilder({
                      ...builder,
                      widgets: builder.widgets.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, title: event.target.value } : entry,
                      ),
                    })
                  }
                />
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  title={t('dashboards.removeWidget', 'Remove widget')}
                  onClick={() =>
                    setBuilder({
                      ...builder,
                      widgets: builder.widgets.filter((_, entryIndex) => entryIndex !== index),
                    })
                  }
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={t('dashboards.deleteTitle', 'Delete dashboard')}
        message={t('dashboards.deleteMessage', 'Delete "{name}"? Widgets are not recoverable.', {
          name: deleting?.name ?? '',
        })}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  )
}
