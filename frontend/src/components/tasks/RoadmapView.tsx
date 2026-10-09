import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarRange, ChevronDown, ChevronRight, ExternalLink, Plus, Rocket, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ActivityFeed } from './ActivityFeed'
import { ApiError, releasesApi } from '../../lib/api'
import { useReleases, useRoadmap, qk } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { ReleaseRead, ReleaseStatus, RoadmapEpic } from '../../lib/types'
import { RELEASE_STATUS_BADGE, RELEASE_STATUS_LABELS } from '../../lib/types'
import { cn, formatDate } from '../../lib/utils'
import { Badge, Button, Field, Input, Modal, Select, Spinner } from '../ui'

const STATUS_OPTIONS: ReleaseStatus[] = ['planned', 'in_progress', 'released', 'cancelled']

function Bar({
  start,
  end,
  rangeStart,
  rangeEnd,
  color,
}: {
  start: string | null
  end: string | null
  rangeStart: number
  rangeEnd: number
  color: string
}) {
  const { t } = useI18n()
  if (!start && !end) {
    return <span className="text-xs text-slate-400">{t('roadmap.noDates', 'No dates')}</span>
  }
  const span = Math.max(rangeEnd - rangeStart, 1)
  const startMs = start ? new Date(start).getTime() : new Date(end as string).getTime()
  const endMs = end ? new Date(end).getTime() : new Date(start as string).getTime()
  const left = ((startMs - rangeStart) / span) * 100
  const width = Math.max(((endMs - startMs) / span) * 100, 1.5)
  return (
    <div className="relative h-5 w-full rounded bg-slate-100">
      <div
        className={cn('absolute top-0 h-5 rounded', color)}
        style={{ left: `${Math.max(0, Math.min(97, left))}%`, width: `${Math.min(width, 100)}%` }}
      />
    </div>
  )
}

export function RoadmapView({ projectId }: { projectId: string }) {
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const releases = useReleases(projectId)
  const roadmap = useRoadmap(projectId)
  const [releaseOpen, setReleaseOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [form, setForm] = useState({
    name: '',
    version: '',
    description: '',
    status: 'planned' as ReleaseStatus,
    release_date: '',
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.releases(projectId) })
    void queryClient.invalidateQueries({ queryKey: qk.roadmap(projectId) })
  }

  const createRelease = useMutation({
    mutationFn: () =>
      releasesApi.create(projectId, {
        name: form.name.trim(),
        version: form.version.trim() || null,
        description: form.description.trim() || null,
        status: form.status,
        release_date: form.release_date ? new Date(form.release_date).toISOString() : null,
      }),
    onSuccess: () => {
      setReleaseOpen(false)
      setForm({ name: '', version: '', description: '', status: 'planned', release_date: '' })
      invalidate()
      toast.success(t('roadmap.created', 'Release created'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('roadmap.createError', 'Could not create release')),
  })

  const updateRelease = useMutation({
    mutationFn: ({ id, status }: { id: string; status: ReleaseStatus }) =>
      releasesApi.update(projectId, id, { status }),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('roadmap.updateError', 'Could not update release')),
  })

  const removeRelease = useMutation({
    mutationFn: (id: string) => releasesApi.remove(projectId, id),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('roadmap.deleteError', 'Could not delete release')),
  })

  const range = useMemo(() => {
    const dates: number[] = []
    for (const release of releases.data ?? []) {
      if (release.start_date) dates.push(new Date(release.start_date).getTime())
      if (release.release_date) dates.push(new Date(release.release_date).getTime())
    }
    for (const epic of roadmap.data?.epics ?? []) {
      if (epic.start_date) dates.push(new Date(epic.start_date).getTime())
      if (epic.due_date) dates.push(new Date(epic.due_date).getTime())
    }
    const now = Date.now()
    return {
      start: dates.length ? Math.min(...dates, now) : now - 30 * 86_400_000,
      end: dates.length ? Math.max(...dates, now) : now + 60 * 86_400_000,
    }
  }, [releases.data, roadmap.data])

  const loading = releases.isLoading || roadmap.isLoading

  function toggleEpic(id: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            {t('roadmap.title', 'Releases & roadmap')}
          </h2>
          <p className="text-xs text-slate-500">
            {t(
              'roadmap.subtitle',
              'Scope with dates per release; epics show their delivery window.',
            )}
          </p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => setReleaseOpen(true)}>
          <Plus className="h-3.5 w-3.5" /> {t('roadmap.newRelease', 'New release')}
        </Button>
      </div>

      {loading && (
        <div className="flex justify-center py-6">
          <Spinner className="h-5 w-5 text-slate-400" />
        </div>
      )}

      {/* Releases with scope progress */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(releases.data ?? []).map((release: ReleaseRead) => {
          const pct = release.task_count
            ? Math.round((release.done_task_count / release.task_count) * 100)
            : 0
          return (
            <div key={release.id} className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                    <Rocket className="h-3.5 w-3.5 text-brand-500" />
                    {release.name}
                    {release.version && (
                      <span className="text-xs font-normal text-slate-400">v{release.version}</span>
                    )}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {release.release_date
                      ? formatDate(release.release_date)
                      : t('roadmap.noReleaseDate', 'No release date')}
                  </p>
                </div>
                <Badge className={RELEASE_STATUS_BADGE[release.status]}>
                  {t(`releaseStatus.${release.status}`, RELEASE_STATUS_LABELS[release.status])}
                </Badge>
              </div>
              <div className="mt-3">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-brand-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {t('roadmap.tasksDone', '{done}/{total} tasks done ({pct}%)', {
                    done: release.done_task_count,
                    total: release.task_count,
                    pct,
                  })}
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <Select
                  className="w-36 py-1 text-xs"
                  value={release.status}
                  onChange={(event) =>
                    updateRelease.mutate({
                      id: release.id,
                      status: event.target.value as ReleaseStatus,
                    })
                  }
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {t(`releaseStatus.${status}`, RELEASE_STATUS_LABELS[status])}
                    </option>
                  ))}
                </Select>
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  title={t('roadmap.deleteRelease', 'Delete release')}
                  onClick={() => removeRelease.mutate(release.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          )
        })}
        {(releases.data?.length ?? 0) === 0 && !loading && (
          <p className="text-sm text-slate-400">
            {t('roadmap.noReleases', 'No releases yet — create one to scope a version.')}
          </p>
        )}
      </div>

      {/* Epic timeline */}
      <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
            <CalendarRange className="h-4 w-4 text-slate-400" /> {t('roadmap.timeline', 'Timeline by epic')}
          </h3>
          <div className="flex items-center gap-2 text-[10px] text-slate-400">
            <span>{formatDate(new Date(range.start).toISOString())}</span>
            <span>→</span>
            <span>{formatDate(new Date(range.end).toISOString())}</span>
          </div>
        </div>

        {(roadmap.data?.epics ?? []).map((epic: RoadmapEpic) => {
          const isOpen = expanded.has(epic.id)
          return (
            <div key={epic.id} className="rounded-lg border border-slate-100 bg-slate-50/50 p-2">
              <div className="grid items-center gap-2 md:grid-cols-[minmax(180px,1fr)_2fr]">
                <button
                  className="flex min-w-0 items-center gap-1 text-left"
                  onClick={() => toggleEpic(epic.id)}
                >
                  {isOpen ? (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                  )}
                  <span className="truncate text-sm font-medium text-slate-700">
                    {epic.key ? `${epic.key}: ` : ''}
                    {epic.title}
                  </span>
                  <span className="ml-1 shrink-0 text-xs text-slate-400">
                    {epic.done_task_count}/{epic.task_count}
                  </span>
                </button>
                <Bar
                  start={epic.start_date}
                  end={epic.due_date}
                  rangeStart={range.start}
                  rangeEnd={range.end}
                  color={
                    epic.status_category === 'done' ? 'bg-emerald-400' : 'bg-brand-400'
                  }
                />
              </div>
              {isOpen && (
                <div className="mt-2 space-y-1 pl-5">
                  {epic.children.map((child) => (
                    <div
                      key={child.id}
                      className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-white"
                    >
                      <span className="truncate text-slate-600">
                        {child.key ? `${child.key} · ` : ''}
                        {child.title}
                      </span>
                      <span className="shrink-0 text-slate-400">
                        {child.due_date ? formatDate(child.due_date) : '—'} · {child.status}
                      </span>
                    </div>
                  ))}
                  {epic.children.length === 0 && (
                    <p className="text-xs text-slate-400">{t('roadmap.noChildren', 'No child work items.')}</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {(roadmap.data?.epics.length ?? 0) === 0 && !loading && (
          <p className="text-sm text-slate-400">
            {t('roadmap.noEpics', 'No epics yet — create an epic to group delivery work.')}
          </p>
        )}
      </div>

      {(roadmap.data?.unassigned.length ?? 0) > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-800">
            {t('roadmap.unscheduled', 'Unscheduled work items')}
          </h3>
          <div className="mt-2 space-y-1">
            {roadmap.data?.unassigned.map((task) => (
              <div key={task.id} className="flex items-center justify-between text-xs">
                <span className="truncate text-slate-600">
                  <ExternalLink className="mr-1 inline h-3 w-3 text-slate-300" />
                  {task.key ? `${task.key} · ` : ''}
                  {task.title}
                </span>
                <span className="text-slate-400">{task.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-800">
          {t('roadmap.projectActivity', 'Project activity')}
        </h3>
        <ActivityFeed scope={{ type: 'project', id: projectId }} />
      </div>

      <Modal
        open={releaseOpen}
        onClose={() => setReleaseOpen(false)}
        title={t('roadmap.newRelease', 'New release')}
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setReleaseOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => createRelease.mutate()}
              disabled={!form.name.trim()}
              loading={createRelease.isPending}
            >
              {t('roadmap.createRelease', 'Create release')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t('common.name', 'Name')}>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder={t('roadmap.namePlaceholder', 'July release')}
            />
          </Field>
          <Field label={t('roadmap.version', 'Version')} hint={t('roadmap.versionHint', 'Optional, e.g. 1.4.0')}>
            <Input
              value={form.version}
              onChange={(event) => setForm({ ...form, version: event.target.value })}
            />
          </Field>
          <Field label={t('roadmap.releaseDate', 'Release date')}>
            <Input
              type="date"
              value={form.release_date}
              onChange={(event) => setForm({ ...form, release_date: event.target.value })}
            />
          </Field>
          <Field label={t('common.status', 'Status')}>
            <Select
              value={form.status}
              onChange={(event) =>
                setForm({ ...form, status: event.target.value as ReleaseStatus })
              }
            >
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {RELEASE_STATUS_LABELS[status]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Modal>
    </div>
  )
}
