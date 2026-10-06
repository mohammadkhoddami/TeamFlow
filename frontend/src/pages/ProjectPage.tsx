import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarRange,
  Columns3,
  Download,
  FileDown,
  LayoutGrid,
  Network,
  Plus,
  Save,
  Settings2,
  SlidersHorizontal,
  Workflow,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
import { BacklogView } from '../components/tasks/BacklogView'
import { BoardManager } from '../components/tasks/BoardManager'
import { CustomFieldsManager } from '../components/tasks/CustomFieldsManager'
import { SprintManager } from '../components/tasks/SprintManager'
import { TaskBoard } from '../components/tasks/TaskBoard'
import { TaskCreateDialog } from '../components/tasks/TaskCreateDialog'
import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import { TaskTree } from '../components/tasks/TaskTree'
import { WorkflowManager } from '../components/tasks/WorkflowManager'
import {
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Textarea,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, dataApi, tasksApi, projectsApi, templatesApi } from '../lib/api'
import {
  useBoards,
  useInvalidateTasks,
  useProject,
  useSprints,
  useTasks,
  useTaskTree,
  useWorkflow,
} from '../lib/hooks'
import { downloadOpenTasksMarkdown } from '../lib/taskExport'
import { canManage, type TaskRead, type TaskType } from '../lib/types'
import { cn, formatDate } from '../lib/utils'
import { createProjectSocket, type SocketStatus } from '../lib/ws'

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { org, role } = useOrg()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const invalidate = useInvalidateTasks()

  const project = useProject(projectId)
  const sprints = useSprints(projectId)
  const workflow = useWorkflow(projectId)
  const boards = useBoards(projectId)
  const [sprintFilter, setSprintFilter] = useState<string>('')
  const [boardId, setBoardId] = useState<string>('')
  const selectedBoard =
    boards.data?.find((board) => board.id === boardId) ??
    boards.data?.find((board) => board.is_default)
  const boardFilter = selectedBoard?.filter_query?.trim() || ''
  const taskFilters = useMemo(
    () => ({
      project_id: projectId,
      limit: 100,
      sprint_id: sprintFilter && sprintFilter !== '__backlog__' ? sprintFilter : undefined,
      backlog_only: sprintFilter === '__backlog__' || undefined,
    }),
    [projectId, sprintFilter],
  )
  const plainTasks = useTasks(org.slug, taskFilters)
  const filteredTasks = useQuery({
    queryKey: ['orgs', org.slug, 'tasks', 'board-filter', boardFilter],
    queryFn: () => tasksApi.query(org.slug, boardFilter, { limit: 100 }),
    enabled: Boolean(boardFilter),
  })
  const tasks = boardFilter ? filteredTasks : plainTasks
  const tree = useTaskTree(projectId)

  const [socketStatus, setSocketStatus] = useState<SocketStatus>('connecting')
  const [selectedTask, setSelectedTask] = useState<TaskRead | null>(null)
  const selectedTaskIdRef = useRef<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createStatus, setCreateStatus] = useState<string>('todo')
  const [createParent, setCreateParent] = useState<TaskRead | null>(null)
  const [createType, setCreateType] = useState<TaskType>('task')
  const [view, setView] = useState<'board' | 'tree' | 'backlog'>('board')
  const [showSubtasks, setShowSubtasks] = useState(true)
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [managingSprints, setManagingSprints] = useState(false)
  const [managingWorkflow, setManagingWorkflow] = useState(false)
  const [managingBoards, setManagingBoards] = useState(false)
  const [managingFields, setManagingFields] = useState(false)
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'active' | 'archived'>('active')
  const [projectKey, setProjectKey] = useState('')
  const [estimationUnit, setEstimationUnit] = useState<'none' | 'points' | 'hours'>('points')

  const boardTasks = tasks.data
    ? showSubtasks
      ? tasks.data.items
      : tasks.data.items.filter((task) => !task.parent_id)
    : []
  const openBoardTasks = boardTasks.filter((task) => task.status !== 'done').length

  useEffect(() => {
    if (project.data && editing) {
      setName(project.data.name)
      setDescription(project.data.description ?? '')
      setStatus(project.data.status)
      setProjectKey(project.data.key ?? '')
      setEstimationUnit(project.data.estimation_unit ?? 'points')
    }
  }, [project.data, editing])

  useEffect(() => {
    selectedTaskIdRef.current = selectedTask?.id ?? null
  }, [selectedTask])

  const startCreate = (options?: {
    status?: string
    parent?: TaskRead | null
    type?: TaskType
  }) => {
    setCreateStatus(options?.status ?? 'todo')
    setCreateParent(options?.parent ?? null)
    setCreateType(
      options?.type ?? (options?.parent?.type === 'epic' ? 'story' : 'task'),
    )
    setCreating(true)
  }

  useEffect(() => {
    if (!projectId) return
    return createProjectSocket(
      projectId,
      (event) => {
        if (event.type.startsWith('task.') || event.type.startsWith('comment.')) {
          invalidate(org.slug)
          void queryClient.invalidateQueries({
            queryKey: ['projects', projectId, 'task-tree'],
          })
          const openTaskId = selectedTaskIdRef.current
          if (openTaskId && event.data.id === openTaskId) {
            void queryClient.invalidateQueries({ queryKey: ['tasks', openTaskId] })
            void queryClient.invalidateQueries({ queryKey: ['tasks', openTaskId, 'comments'] })
          }
        }
      },
      setSocketStatus,
    )
  }, [projectId, org.slug, invalidate, queryClient])

  const move = useMutation({
    mutationFn: ({ taskId, status: next }: { taskId: string; status: string }) =>
      tasksApi.move(taskId, next),
    onSuccess: () => invalidate(org.slug),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'That status change is not allowed'),
  })

  const saveProject = useMutation({
    mutationFn: () =>
      projectsApi.update(projectId!, {
        name: name.trim(),
        description: description.trim() || null,
        status,
        key: projectKey.trim() ? projectKey.trim().toUpperCase() : undefined,
        estimation_unit: estimationUnit,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'projects'] })
      setEditing(false)
      toast.success('Project updated')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not save project'),
  })

  const saveTemplate = useMutation({
    mutationFn: () =>
      templatesApi.saveProjectAsTemplate(projectId!, { name: templateName.trim() }),
    onSuccess: () => {
      toast.success('Project template saved')
      setSavingTemplate(false)
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not save template'),
  })

  const deleteProject = useMutation({
    mutationFn: () => projectsApi.remove(projectId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'projects'] })
      toast.success('Project deleted')
      navigate(`/org/${org.slug}/projects`)
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete project'),
  })

  if (project.isLoading) return <PageSpinner label="Loading project…" />
  if (project.isError || !project.data) {
    return (
      <div className="p-6">
        <ErrorState
          message="Project not found or you no longer have access."
          onRetry={() => void project.refetch()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <Link
          to={`/org/${org.slug}/projects`}
          className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> All projects
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold text-slate-900">{project.data.name}</h1>
              <Badge
                className={
                  project.data.status === 'active'
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-slate-100 text-slate-600'
                }
              >
                {project.data.status}
              </Badge>
              <span
                className="inline-flex items-center gap-1 text-[11px] text-slate-400"
                title={`Realtime: ${socketStatus}`}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    socketStatus === 'open' ? 'bg-emerald-500' : 'bg-slate-300',
                  )}
                />
                {socketStatus === 'open' ? 'live' : socketStatus}
              </span>
            </div>
            {project.data.description && (
              <p className="mt-1 max-w-2xl text-sm text-slate-500">{project.data.description}</p>
            )}
            <p className="mt-1 text-xs text-slate-400">
              Created {formatDate(project.data.created_at)} · {tasks.data?.total ?? 0} tasks
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
              <button
                type="button"
                onClick={() => setView('board')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  view === 'board'
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:text-slate-700',
                )}
              >
                <LayoutGrid className="h-3.5 w-3.5" /> Board
              </button>
              <button
                type="button"
                onClick={() => setView('tree')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  view === 'tree'
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:text-slate-700',
                )}
              >
                <Network className="h-3.5 w-3.5" /> Hierarchy
              </button>
              <button
                type="button"
                onClick={() => setView('backlog')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  view === 'backlog'
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:text-slate-700',
                )}
              >
                <CalendarRange className="h-3.5 w-3.5" /> Backlog
              </button>
            </div>
            {view === 'board' && (
              <>
                {(boards.data ?? []).length > 0 && (
                  <Select
                    className="w-auto"
                    value={selectedBoard?.id ?? ''}
                    onChange={(event) => setBoardId(event.target.value)}
                    title="Saved board"
                  >
                    {boards.data!.map((board) => (
                      <option key={board.id} value={board.id}>
                        {board.name}
                        {board.is_default ? ' (default)' : ''}
                      </option>
                    ))}
                  </Select>
                )}
                <Select
                  className="w-auto"
                  value={sprintFilter}
                  onChange={(event) => setSprintFilter(event.target.value)}
                  title="Filter the board by sprint"
                >
                  <option value="">All tasks</option>
                  <option value="__backlog__">Backlog only</option>
                  {(sprints.data ?? []).map((sprint) => (
                    <option key={sprint.id} value={sprint.id}>
                      {sprint.name}
                      {sprint.state === 'active' ? ' (active)' : ''}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setManagingSprints(true)}
                >
                  <CalendarRange className="h-3.5 w-3.5" /> Sprints
                </Button>
                <Checkbox
                  label="Subtasks"
                  checked={showSubtasks}
                  onChange={(event) => setShowSubtasks(event.target.checked)}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={openBoardTasks === 0}
                  title="Download open board tasks as markdown"
                  onClick={() => {
                    const count = downloadOpenTasksMarkdown(project.data.name, boardTasks)
                    toast.success(
                      `Exported ${count} open task${count === 1 ? '' : 's'} to opening-tasks.md`,
                    )
                  }}
                >
                  <Download className="h-3.5 w-3.5" /> Export
                </Button>
              </>
            )}
            {canManage(role) && (
              <>
                <Button variant="secondary" size="sm" onClick={() => setManagingWorkflow(true)}>
                  <Workflow className="h-3.5 w-3.5" /> Workflow
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setManagingBoards(true)}>
                  <Columns3 className="h-3.5 w-3.5" /> Boards
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setManagingFields(true)}>
                  <SlidersHorizontal className="h-3.5 w-3.5" /> Fields
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setTemplateName(`${project.data.name} template`)
                    setSavingTemplate(true)
                  }}
                >
                  <Save className="h-3.5 w-3.5" /> Template
                </Button>
              </>
            )}
            <Button
              variant="secondary"
              size="sm"
              title="Download all project tasks as CSV"
              onClick={() =>
                void dataApi
                  .downloadProjectCsv(project.data.id, `${project.data.name}.csv`)
                  .catch(() => toast.error('Could not export CSV'))
              }
            >
              <FileDown className="h-3.5 w-3.5" /> CSV
            </Button>
            {canManage(role) && (
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                <Settings2 className="h-3.5 w-3.5" /> Project settings
              </Button>
            )}
            <Button size="sm" onClick={() => startCreate()}>
              <Plus className="h-3.5 w-3.5" /> Add task
            </Button>
          </div>
        </div>
      </div>

      {view === 'board' ? (
        <>
          {tasks.isLoading && <PageSpinner label="Loading board…" />}
          {tasks.isError && (
            <ErrorState message="Could not load tasks." onRetry={() => void tasks.refetch()} />
          )}
          {tasks.data && (
            <TaskBoard
              tasks={boardTasks}
              statuses={workflow.data ?? []}
              swimlaneBy={selectedBoard?.swimlane_by ?? 'none'}
              wipEnforced={project.data.wip_enforced}
              onOpen={setSelectedTask}
              onMove={(taskId, next) => move.mutate({ taskId, status: next })}
              onAdd={(next) => startCreate({ status: next })}
            />
          )}
        </>
      ) : view === 'backlog' ? (
        projectId ? (
          <BacklogView projectId={projectId} onOpen={setSelectedTask} />
        ) : null
      ) : (
        <>
          {tree.isLoading && <PageSpinner label="Loading hierarchy…" />}
          {tree.isError && (
            <ErrorState
              message="Could not load the hierarchy."
              onRetry={() => void tree.refetch()}
            />
          )}
          {tree.data && (
            <TaskTree
              nodes={tree.data}
              statuses={workflow.data}
              onOpen={setSelectedTask}
              onAddChild={(parent) => startCreate({ parent })}
            />
          )}
        </>
      )}

      {projectId && (
        <TaskCreateDialog
          open={creating}
          onClose={() => setCreating(false)}
          projectId={projectId}
          defaultStatus={createStatus}
          defaultParentId={createParent?.id ?? null}
          defaultType={createType}
        />
      )}

      <TaskDetailDrawer
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onOpenTask={(next) => setSelectedTask(next)}
        onAddChild={(parent) => startCreate({ parent })}
      />

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Project settings"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => saveProject.mutate()}
              loading={saveProject.isPending}
              disabled={name.trim().length === 0}
            >
              Save changes
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name">
            <Input value={name} maxLength={255} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field label="Description">
            <Textarea
              value={description}
              maxLength={10_000}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          <Field label="Status">
            <Select
              value={status}
              onChange={(event) => setStatus(event.target.value as 'active' | 'archived')}
            >
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </Select>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Issue key" hint="Prefix for new tasks, e.g. TEAM-42">
              <Input
                value={projectKey}
                maxLength={10}
                onChange={(event) => setProjectKey(event.target.value.toUpperCase())}
              />
            </Field>
            <Field label="Estimation" hint="Points or hours on tasks and sprint totals">
              <Select
                value={estimationUnit}
                onChange={(event) =>
                  setEstimationUnit(event.target.value as 'none' | 'points' | 'hours')
                }
              >
                <option value="points">Story points</option>
                <option value="hours">Hours</option>
                <option value="none">None</option>
              </Select>
            </Field>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-3">
            <div>
              <p className="text-sm font-medium text-red-800">Delete project</p>
              <p className="text-xs text-red-600">Tasks and comments will be removed.</p>
            </div>
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete project"
        message={`Delete "${project.data.name}" and everything inside it? This cannot be undone.`}
        busy={deleteProject.isPending}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => deleteProject.mutate()}
      />

      {projectId && (
        <>
          <SprintManager
            projectId={projectId}
            open={managingSprints}
            onClose={() => setManagingSprints(false)}
          />
          <WorkflowManager
            projectId={projectId}
            open={managingWorkflow}
            onClose={() => setManagingWorkflow(false)}
          />
          <BoardManager
            projectId={projectId}
            slug={org.slug}
            open={managingBoards}
            onClose={() => setManagingBoards(false)}
          />
          <CustomFieldsManager
            projectId={projectId}
            open={managingFields}
            onClose={() => setManagingFields(false)}
          />
          <Modal
            open={savingTemplate}
            onClose={() => setSavingTemplate(false)}
            title="Save as project template"
            description="Snapshots the workflow, labels, custom fields, boards and hierarchy."
            footer={
              <>
                <Button variant="secondary" onClick={() => setSavingTemplate(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => saveTemplate.mutate()}
                  loading={saveTemplate.isPending}
                  disabled={!templateName.trim()}
                >
                  Save template
                </Button>
              </>
            }
          >
            <Field label="Template name">
              <Input
                value={templateName}
                maxLength={128}
                onChange={(event) => setTemplateName(event.target.value)}
              />
            </Field>
          </Modal>
        </>
      )}
    </div>
  )
}
