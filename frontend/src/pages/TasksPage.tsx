import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArchiveRestore,
  Copy,
  CornerDownRight,
  Eye,
  ListFilter,
  Plus,
  Save,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import { TaskCreateDialog } from '../components/tasks/TaskCreateDialog'
import {
  Avatar,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  PageSpinner,
  Select,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, savedFiltersApi, tasksApi } from '../lib/api'
import type { TaskFilters } from '../lib/api'
import { useInvalidateTasks, useProjects, useSavedFilters, useTasks } from '../lib/hooks'
import {
  PRIORITIES,
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  CATEGORY_BADGE,
  STATUS_LABELS,
  TASK_STATUSES,
  TASK_TYPES,
  TYPE_BADGE,
  TYPE_LABELS,
  type TaskPriority,
  type TaskRead,
  type TaskStatus,
  type TaskType,
} from '../lib/types'
import { cn, formatDate, isOverdue } from '../lib/utils'

const SORTS = [
  { value: '-created_at', label: 'Newest first' },
  { value: 'created_at', label: 'Oldest first' },
  { value: '-due_date', label: 'Due date (latest)' },
  { value: 'due_date', label: 'Due date (soonest)' },
  { value: '-priority', label: 'Priority (high to low)' },
  { value: 'title', label: 'Title (A–Z)' },
]

export function TasksPage() {
  const { org, members } = useOrg()
  const projects = useProjects(org.slug)
  const invalidate = useInvalidateTasks()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const [mode, setMode] = useState<'filters' | 'teamql'>('filters')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [projectId, setProjectId] = useState('')
  const [statuses, setStatuses] = useState<TaskStatus[]>([])
  const [priority, setPriority] = useState('')
  const [type, setType] = useState('')
  const [rootsOnly, setRootsOnly] = useState(false)
  const [assigneeId, setAssigneeId] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [sort, setSort] = useState('-created_at')
  const [offset, setOffset] = useState(0)
  const [selectedTask, setSelectedTask] = useState<TaskRead | null>(null)
  const [creating, setCreating] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)

  const [teamqlInput, setTeamqlInput] = useState('')
  const [teamql, setTeamql] = useState('')
  const [saveName, setSaveName] = useState('')
  const [savingFilter, setSavingFilter] = useState(false)
  const savedFilters = useSavedFilters(org.slug)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  // Deep link: /tasks?task=<id> opens the drawer (emails, global search).
  const deepLinkTaskId = searchParams.get('task')
  useEffect(() => {
    if (!deepLinkTaskId) return
    let cancelled = false
    tasksApi
      .get(deepLinkTaskId)
      .then((task) => {
        if (!cancelled) setSelectedTask(task)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [deepLinkTaskId])

  const closeDrawer = () => {
    setSelectedTask(null)
    if (deepLinkTaskId) {
      const next = new URLSearchParams(searchParams)
      next.delete('task')
      setSearchParams(next, { replace: true })
    }
  }

  const filters = useMemo<TaskFilters>(
    () => ({
      project_id: projectId || undefined,
      status: statuses.length ? statuses : undefined,
      priority: priority ? [priority as TaskPriority] : undefined,
      type: type ? [type as TaskType] : undefined,
      roots_only: rootsOnly || undefined,
      assignee_id: assigneeId || undefined,
      search: search || undefined,
      overdue: overdue || undefined,
      sort,
      offset,
      limit: 25,
    }),
    [projectId, statuses, priority, type, rootsOnly, assigneeId, search, overdue, sort, offset],
  )

  const filterTasks = useTasks(org.slug, filters)
  const teamqlTasks = useQuery({
    queryKey: ['orgs', org.slug, 'teamql', teamql, offset],
    queryFn: () => tasksApi.query(org.slug, teamql, { offset, limit: 25 }),
    enabled: mode === 'teamql' && teamql.trim().length > 0,
  })

  const tasks = mode === 'filters' ? filterTasks : teamqlTasks
  const total = tasks.data?.total ?? 0
  const perPage = tasks.data?.limit ?? 25
  const items = tasks.data?.items ?? []
  const projectNames = new Map(projects.data?.map((project) => [project.id, project.name]) ?? [])

  const bulk = useMutation({
    mutationFn: (data: Parameters<typeof tasksApi.bulk>[1]) => tasksApi.bulk(org.slug, data),
    onSuccess: (result) => {
      invalidate(org.slug)
      setSelectedIds(new Set())
      const failed = result.failures.length
      toast.success(
        `Updated ${result.updated} of ${result.requested} task${result.requested === 1 ? '' : 's'}` +
          (failed ? ` — ${failed} skipped` : ''),
      )
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Bulk action failed'),
  })

  const toggleStatus = (status: TaskStatus) => {
    setStatuses((current) =>
      current.includes(status) ? current.filter((entry) => entry !== status) : [...current, status],
    )
    setOffset(0)
  }

  const toggleSelected = (taskId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(taskId)) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  const allSelected = items.length > 0 && items.every((task) => selectedIds.has(task.id))

  const selectedArray = [...selectedIds]

  const runTeamql = () => {
    setOffset(0)
    setTeamql(teamqlInput.trim())
    setSelectedIds(new Set())
  }

  const loadSavedFilter = (id: string) => {
    const saved = savedFilters.data?.find((entry) => entry.id === id)
    if (!saved) return
    setMode('teamql')
    setTeamqlInput(saved.query)
    setTeamql(saved.query)
    setOffset(0)
  }

  const saveCurrentFilter = async () => {
    const name = saveName.trim()
    if (!name || !teamqlInput.trim()) return
    try {
      await savedFiltersApi.create(org.slug, {
        name,
        query: teamqlInput.trim(),
        project_id: projectId || null,
        is_shared: true,
      })
      await queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'saved-filters'] })
      setSavingFilter(false)
      setSaveName('')
      toast.success(`Saved filter “${name}”`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not save the filter')
    }
  }

  const removeSavedFilter = async (id: string) => {
    try {
      await savedFiltersApi.remove(org.slug, id)
      await queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'saved-filters'] })
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not delete the filter')
    }
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Tasks</h1>
          <p className="text-sm text-slate-500">
            {tasks.isLoading ? 'Loading…' : `${total} tasks match your query.`}
          </p>
        </div>
        <Button onClick={() => setCreating(true)} disabled={!projects.data?.length}>
          <Plus className="h-4 w-4" /> New task
        </Button>
      </div>

      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
            <button
              type="button"
              onClick={() => setMode('filters')}
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                mode === 'filters'
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:text-slate-700',
              )}
            >
              <ListFilter className="h-3.5 w-3.5" /> Filters
            </button>
            <button
              type="button"
              onClick={() => setMode('teamql')}
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                mode === 'teamql'
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:text-slate-700',
              )}
            >
              <Sparkles className="h-3.5 w-3.5" /> TeamQL
            </button>
          </div>

          {savedFilters.data && savedFilters.data.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {savedFilters.data.map((saved) => (
                <span
                  key={saved.id}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600"
                >
                  <button
                    type="button"
                    onClick={() => loadSavedFilter(saved.id)}
                    className="hover:text-brand-700"
                    title={saved.query}
                  >
                    {saved.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeSavedFilter(saved.id)}
                    className="text-slate-300 hover:text-red-500"
                    aria-label={`Delete saved filter ${saved.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {mode === 'filters' ? (
          <>
            <div className="grid gap-3 md:grid-cols-5">
              <div className="relative md:col-span-2">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                <Input
                  className="pl-9"
                  placeholder="Search titles and descriptions…"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </div>
              <Select
                value={projectId}
                onChange={(event) => {
                  setProjectId(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">All projects</option>
                {projects.data?.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
              <Select
                value={type}
                onChange={(event) => {
                  setType(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">Any type</option>
                {TASK_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {TYPE_LABELS[value]}
                  </option>
                ))}
              </Select>
              <Select
                value={priority}
                onChange={(event) => {
                  setPriority(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">Any priority</option>
                {PRIORITIES.map((value) => (
                  <option key={value} value={value}>
                    {PRIORITY_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {TASK_STATUSES.map((status) => (
                <button
                  key={status}
                  onClick={() => toggleStatus(status)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                    statuses.includes(status)
                      ? 'border-brand-300 bg-brand-50 text-brand-700'
                      : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300',
                  )}
                >
                  {STATUS_LABELS[status]}
                </button>
              ))}
              <div className="mx-1 h-5 w-px bg-slate-200" />
              <Select
                className="w-auto"
                value={assigneeId}
                onChange={(event) => {
                  setAssigneeId(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">Anyone</option>
                {members.map((membership) => (
                  <option key={membership.user_id} value={membership.user_id}>
                    {membership.user?.full_name || membership.user?.email || membership.user_id}
                  </option>
                ))}
              </Select>
              <Checkbox
                label="Overdue only"
                checked={overdue}
                onChange={(event) => {
                  setOverdue(event.target.checked)
                  setOffset(0)
                }}
              />
              <Checkbox
                label="Top level only"
                checked={rootsOnly}
                onChange={(event) => {
                  setRootsOnly(event.target.checked)
                  setOffset(0)
                }}
              />
              <div className="ml-auto">
                <Select
                  className="w-auto"
                  value={sort}
                  onChange={(event) => {
                    setSort(event.target.value)
                    setOffset(0)
                  }}
                >
                  {SORTS.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          </>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                className="min-w-64 flex-1 font-mono text-xs"
                placeholder='status = todo AND priority = high AND assignee = me ORDER BY due'
                value={teamqlInput}
                onChange={(event) => setTeamqlInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') runTeamql()
                }}
              />
              <Button size="sm" onClick={runTeamql} disabled={!teamqlInput.trim()}>
                Run query
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setSavingFilter((value) => !value)}
                disabled={!teamqlInput.trim()}
              >
                <Save className="h-3.5 w-3.5" /> Save
              </Button>
            </div>
            {savingFilter && (
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="max-w-xs"
                  placeholder="Filter name"
                  value={saveName}
                  onChange={(event) => setSaveName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveCurrentFilter()
                  }}
                />
                <Button size="sm" onClick={() => void saveCurrentFilter()} disabled={!saveName.trim()}>
                  Save filter
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSavingFilter(false)}>
                  Cancel
                </Button>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Fields: project, status, priority, type, assignee, label, sprint, text, key,
              estimate, due, created, updated, archived, parent, roots. Operators: =, !=,
              &gt;, &gt;=, &lt;, &lt;=, ~, in, not in, is empty.
            </p>
          </div>
        )}
      </Card>

      {selectedIds.size > 0 && (
        <Card className="flex flex-wrap items-center gap-2 border-brand-200 bg-brand-50 px-3 py-2">
          <span className="text-xs font-medium text-brand-800">
            {selectedIds.size} selected
          </span>
          <Select
            className="w-auto"
            value=""
            onChange={(event) => {
              if (event.target.value) {
                bulk.mutate({
                  task_ids: selectedArray,
                  action: 'move',
                  status: event.target.value as TaskStatus,
                })
              }
            }}
          >
            <option value="">Move to…</option>
            {TASK_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </Select>
          <Select
            className="w-auto"
            value=""
            onChange={(event) => {
              if (event.target.value) {
                bulk.mutate({
                  task_ids: selectedArray,
                  action: 'update',
                  priority: event.target.value as TaskPriority,
                })
              }
            }}
          >
            <option value="">Set priority…</option>
            {PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_LABELS[value]}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => bulk.mutate({ task_ids: selectedArray, action: 'clone' })}
            loading={bulk.isPending}
          >
            <Copy className="h-3.5 w-3.5" /> Clone
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => bulk.mutate({ task_ids: selectedArray, action: 'archive' })}
            loading={bulk.isPending}
          >
            <Archive className="h-3.5 w-3.5" /> Archive
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => bulk.mutate({ task_ids: selectedArray, action: 'restore' })}
            loading={bulk.isPending}
          >
            <ArchiveRestore className="h-3.5 w-3.5" /> Restore
          </Button>
          <Button size="sm" variant="danger" onClick={() => setConfirmBulkDelete(true)}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelectedIds(new Set())}>
            Clear
          </Button>
        </Card>
      )}

      {tasks.isLoading && <PageSpinner />}
      {tasks.isError && (
        <ErrorState
          message={
            mode === 'teamql'
              ? 'The query could not be parsed or executed.'
              : 'Could not load tasks.'
          }
          onRetry={() => void tasks.refetch()}
        />
      )}

      {tasks.data && items.length === 0 && (
        <EmptyState
          icon={<Eye className="h-8 w-8" />}
          title="No tasks match"
          description="Try relaxing the filters or create a new task."
        />
      )}

      {tasks.data && items.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-10 px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all tasks on this page"
                      checked={allSelected}
                      onChange={(event) =>
                        setSelectedIds(
                          event.target.checked ? new Set(items.map((task) => task.id)) : new Set(),
                        )
                      }
                      className="h-3.5 w-3.5 rounded border-slate-300"
                    />
                  </th>
                  <th className="px-4 py-2.5 font-medium">Task</th>
                  <th className="px-4 py-2.5 font-medium">Project</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Priority</th>
                  <th className="px-4 py-2.5 font-medium">Assignee</th>
                  <th className="px-4 py-2.5 font-medium">Due</th>
                </tr>
              </thead>
              <tbody>
                {items.map((task) => {
                  const due = task.due_date
                  const late = isOverdue(task.due_date, task.status)
                  return (
                    <tr
                      key={task.id}
                      className={cn(
                        'cursor-pointer border-t border-slate-100 hover:bg-slate-50',
                        selectedIds.has(task.id) && 'bg-brand-50/60',
                        task.archived_at && 'opacity-60',
                      )}
                      onClick={() => setSelectedTask(task)}
                    >
                      <td className="px-3 py-2.5" onClick={(event) => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={`Select ${task.title}`}
                          checked={selectedIds.has(task.id)}
                          onChange={() => toggleSelected(task.id)}
                          className="h-3.5 w-3.5 rounded border-slate-300"
                        />
                      </td>
                      <td className="max-w-xs px-4 py-2.5">
                        <div className="flex items-center gap-1.5">
                          {task.key && (
                            <span className="shrink-0 font-mono text-[10px] text-slate-400">
                              {task.key}
                            </span>
                          )}
                          <Badge className={TYPE_BADGE[task.type]}>{TYPE_LABELS[task.type]}</Badge>
                          <p className="truncate font-medium text-slate-800">{task.title}</p>
                          {task.estimate != null && (
                            <span className="shrink-0 rounded-full bg-slate-100 px-1.5 text-[10px] text-slate-500">
                              {task.estimate}
                            </span>
                          )}
                          {task.archived_at && (
                            <span className="shrink-0 rounded-full bg-slate-200 px-1.5 text-[10px] text-slate-500">
                              archived
                            </span>
                          )}
                          {task.child_count > 0 && (
                            <span className="shrink-0 text-[10px] text-slate-400">
                              {task.done_child_count}/{task.child_count}
                            </span>
                          )}
                        </div>
                        {task.parent && (
                          <p className="mt-0.5 flex items-center gap-1 truncate text-[10px] text-slate-400">
                            <CornerDownRight className="h-3 w-3 shrink-0" />
                            <span className="truncate">
                              {TYPE_LABELS[task.parent.type]} · {task.parent.title}
                            </span>
                          </p>
                        )}
                        <div className="mt-0.5 flex gap-1">
                          {task.labels.map((label) => (
                            <span
                              key={label.id}
                              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600"
                            >
                              <span
                                className="h-1.5 w-1.5 rounded-full"
                                style={{ backgroundColor: label.color ?? '#94a3b8' }}
                              />
                              {label.name}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-slate-500">
                        {projectNames.get(task.project_id) ?? '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge className={CATEGORY_BADGE[task.status_category]}>
                          {task.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge className={PRIORITY_BADGE[task.priority]}>
                          {PRIORITY_LABELS[task.priority]}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        {task.assignee ? (
                          <div className="flex items-center gap-2">
                            <Avatar
                              name={task.assignee.full_name || task.assignee.email}
                              email={task.assignee.email}
                              size="sm"
                            />
                            <span className="text-slate-600">
                              {task.assignee.full_name || task.assignee.email}
                            </span>
                          </div>
                        ) : (
                          <span className="text-slate-400">Unassigned</span>
                        )}
                      </td>
                      <td className={cn('px-4 py-2.5', late ? 'font-medium text-red-600' : 'text-slate-500')}>
                        {due ? formatDate(due) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
            <span>
              Showing {Math.min(offset + 1, total)}–{Math.min(offset + perPage, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - perPage))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={offset + perPage >= total}
                onClick={() => setOffset((value) => value + perPage)}
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}

      <TaskCreateDialog
        open={creating}
        onClose={() => setCreating(false)}
        projectId={projectId}
        projects={projects.data ?? []}
      />
      <TaskDetailDrawer
        task={selectedTask}
        onClose={closeDrawer}
        onOpenTask={(next) => setSelectedTask(next)}
      />

      <ConfirmDialog
        open={confirmBulkDelete}
        title="Delete selected tasks"
        message={`Delete ${selectedIds.size} task${selectedIds.size === 1 ? '' : 's'}? This cannot be undone.`}
        busy={bulk.isPending}
        onClose={() => setConfirmBulkDelete(false)}
        onConfirm={() => {
          bulk.mutate({ task_ids: selectedArray, action: 'delete' })
          setConfirmBulkDelete(false)
        }}
      />
    </div>
  )
}
