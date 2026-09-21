import { CornerDownRight, Eye, Plus, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import { TaskCreateDialog } from '../components/tasks/TaskCreateDialog'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  PageSpinner,
  Select,
} from '../components/ui'
import {
  PRIORITIES,
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  STATUS_BADGE,
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
import { useProjects, useTasks } from '../lib/hooks'
import type { TaskFilters } from '../lib/api'
import { cn, formatDate, isOverdue } from '../lib/utils'
import { Avatar } from '../components/ui'

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

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

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

  const tasks = useTasks(org.slug, filters)
  const total = tasks.data?.total ?? 0
  const perPage = tasks.data?.limit ?? 25
  const projectNames = new Map(projects.data?.map((project) => [project.id, project.name]) ?? [])

  const toggleStatus = (status: TaskStatus) => {
    setStatuses((current) =>
      current.includes(status) ? current.filter((entry) => entry !== status) : [...current, status],
    )
    setOffset(0)
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Tasks</h1>
          <p className="text-sm text-slate-500">
            {tasks.isLoading ? 'Loading…' : `${total} tasks match your filters.`}
          </p>
        </div>
        <Button onClick={() => setCreating(true)} disabled={!projects.data?.length}>
          <Plus className="h-4 w-4" /> New task
        </Button>
      </div>

      <Card className="space-y-3 p-4">
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
      </Card>

      {tasks.isLoading && <PageSpinner />}
      {tasks.isError && (
        <ErrorState message="Could not load tasks." onRetry={() => void tasks.refetch()} />
      )}

      {tasks.data?.items.length === 0 && (
        <EmptyState
          icon={<Eye className="h-8 w-8" />}
          title="No tasks match"
          description="Try relaxing the filters or create a new task."
        />
      )}

      {tasks.data && tasks.data.items.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Task</th>
                  <th className="px-4 py-2.5 font-medium">Project</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Priority</th>
                  <th className="px-4 py-2.5 font-medium">Assignee</th>
                  <th className="px-4 py-2.5 font-medium">Due</th>
                </tr>
              </thead>
              <tbody>
                {tasks.data.items.map((task) => {
                  const due = task.due_date
                  const late = isOverdue(task.due_date, task.status)
                  return (
                    <tr
                      key={task.id}
                      className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                      onClick={() => setSelectedTask(task)}
                    >
                      <td className="max-w-xs px-4 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <Badge className={TYPE_BADGE[task.type]}>{TYPE_LABELS[task.type]}</Badge>
                          <p className="truncate font-medium text-slate-800">{task.title}</p>
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
                        <Badge className={STATUS_BADGE[task.status]}>
                          {STATUS_LABELS[task.status]}
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
        onClose={() => setSelectedTask(null)}
        onOpenTask={(next) => setSelectedTask(next)}
      />
    </div>
  )
}
