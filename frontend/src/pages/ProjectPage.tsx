import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Settings2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
import { TaskBoard } from '../components/tasks/TaskBoard'
import { TaskCreateDialog } from '../components/tasks/TaskCreateDialog'
import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import {
  Badge,
  Button,
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
import { ApiError, tasksApi, projectsApi } from '../lib/api'
import { useInvalidateTasks, useProject, useTasks } from '../lib/hooks'
import { canManage, type TaskRead, type TaskStatus } from '../lib/types'
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
  const tasks = useTasks(org.slug, { project_id: projectId, limit: 100 })

  const [socketStatus, setSocketStatus] = useState<SocketStatus>('connecting')
  const [selectedTask, setSelectedTask] = useState<TaskRead | null>(null)
  const selectedTaskIdRef = useRef<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createStatus, setCreateStatus] = useState<TaskStatus>('todo')
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'active' | 'archived'>('active')

  useEffect(() => {
    if (project.data && editing) {
      setName(project.data.name)
      setDescription(project.data.description ?? '')
      setStatus(project.data.status)
    }
  }, [project.data, editing])

  useEffect(() => {
    selectedTaskIdRef.current = selectedTask?.id ?? null
  }, [selectedTask])

  useEffect(() => {
    if (!projectId) return
    return createProjectSocket(
      projectId,
      (event) => {
        if (event.type.startsWith('task.') || event.type.startsWith('comment.')) {
          invalidate(org.slug)
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
    mutationFn: ({ taskId, status: next }: { taskId: string; status: TaskStatus }) =>
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
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'projects'] })
      setEditing(false)
      toast.success('Project updated')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not save project'),
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
            {canManage(role) && (
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                <Settings2 className="h-3.5 w-3.5" /> Project settings
              </Button>
            )}
            <Button
              size="sm"
              onClick={() => {
                setCreateStatus('todo')
                setCreating(true)
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add task
            </Button>
          </div>
        </div>
      </div>

      {tasks.isLoading && <PageSpinner label="Loading board…" />}
      {tasks.isError && (
        <ErrorState message="Could not load tasks." onRetry={() => void tasks.refetch()} />
      )}
      {tasks.data && (
        <TaskBoard
          tasks={tasks.data.items}
          onOpen={setSelectedTask}
          onMove={(taskId, next) => move.mutate({ taskId, status: next })}
          onAdd={(next) => {
            setCreateStatus(next)
            setCreating(true)
          }}
        />
      )}

      {projectId && (
        <TaskCreateDialog
          open={creating}
          onClose={() => setCreating(false)}
          projectId={projectId}
          defaultStatus={createStatus}
        />
      )}

      <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTask(null)} />

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
    </div>
  )
}
