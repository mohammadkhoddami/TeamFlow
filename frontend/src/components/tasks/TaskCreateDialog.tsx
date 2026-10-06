import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useOrg } from '../OrgLayout'
import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { useInvalidateTasks, useLabels, useTasks } from '../../lib/hooks'
import {
  PRIORITIES,
  PRIORITY_LABELS,
  STATUS_LABELS,
  TASK_TYPES,
  TYPE_LABELS,
  allowedParentTypes,
  type ProjectRead,
  type TaskPriority,
  type TaskStatus,
  type TaskType,
} from '../../lib/types'
import { fromDateTimeLocal } from '../../lib/utils'
import { Button, ErrorState, Field, Input, Modal, Select } from '../ui'
import { MarkdownEditor } from '../MarkdownEditor'
import { LabelPicker } from './LabelPicker'

export function TaskCreateDialog({
  open,
  onClose,
  projectId,
  projects,
  defaultStatus = 'todo',
  defaultParentId = null,
  defaultType = 'task',
}: {
  open: boolean
  onClose: () => void
  projectId: string
  projects?: ProjectRead[]
  defaultStatus?: TaskStatus
  defaultParentId?: string | null
  defaultType?: TaskType
}) {
  const { org, members } = useOrg()
  const labels = useLabels(org.slug)
  const invalidate = useInvalidateTasks()
  const toast = useToast()

  const [selectedProject, setSelectedProject] = useState(projectId)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('medium')
  const [taskType, setTaskType] = useState<TaskType>(defaultType)
  const [parentId, setParentId] = useState<string>(defaultParentId ?? '')
  const [dueDate, setDueDate] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [labelIds, setLabelIds] = useState<string[]>([])
  const [estimate, setEstimate] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Candidate parents share the board's query cache (same key shape).
  const projectTasks = useTasks(org.slug, { project_id: selectedProject, limit: 100 })
  const parentTypes = allowedParentTypes(taskType)
  const parentCandidates = (projectTasks.data?.items ?? []).filter((task) =>
    parentTypes.includes(task.type),
  )

  useEffect(() => {
    if (open) {
      setSelectedProject(projectId || projects?.[0]?.id || '')
      setTitle('')
      setDescription('')
      setPriority('medium')
      setTaskType(defaultType)
      setParentId(defaultParentId ?? '')
      setDueDate('')
      setAssigneeId('')
      setLabelIds([])
      setEstimate('')
      setError(null)
    }
  }, [open, projectId, projects, defaultParentId, defaultType])

  const changeType = (next: TaskType) => {
    setTaskType(next)
    setParentId((currentParent) => {
      if (!currentParent) return ''
      const parent = projectTasks.data?.items.find((entry) => entry.id === currentParent)
      return parent && allowedParentTypes(next).includes(parent.type) ? currentParent : ''
    })
  }

  const create = useMutation({
    mutationFn: async () => {
      const task = await tasksApi.create(selectedProject, {
        title: title.trim(),
        description: description.trim() || null,
        priority,
        type: taskType,
        parent_id: parentId || null,
        due_date: dueDate ? fromDateTimeLocal(dueDate) : null,
        assignee_id: assigneeId || null,
        label_ids: labelIds,
        estimate: estimate.trim() === '' ? null : Number(estimate),
      })
      if (defaultStatus !== 'todo') {
        await tasksApi.move(task.id, defaultStatus)
      }
      return task
    },
    onSuccess: () => {
      invalidate(org.slug)
      toast.success(taskType === 'task' ? 'Task created' : `${TYPE_LABELS[taskType]} created`)
      onClose()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create task'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`New ${TYPE_LABELS[taskType].toLowerCase()}`}
      description={defaultStatus !== 'todo' ? `Will be placed in ${STATUS_LABELS[defaultStatus]}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={title.trim().length === 0 || !selectedProject}
          >
            Create {TYPE_LABELS[taskType].toLowerCase()}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <ErrorState message={error} />}
        {projects && (
          <Field label="Project">
            <Select
              value={selectedProject}
              onChange={(event) => {
                setSelectedProject(event.target.value)
                setParentId('')
              }}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Title">
          <Input
            autoFocus
            value={title}
            maxLength={255}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Ship the release notes"
          />
        </Field>
        <Field label="Description" hint="Markdown supported — headings, lists, code, links">
          <MarkdownEditor
            value={description}
            onChange={setDescription}
            maxLength={20_000}
            minRows={5}
            placeholder="Add context, acceptance criteria, links…"
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Type" hint="Epic → story → task">
            <Select value={taskType} onChange={(event) => changeType(event.target.value as TaskType)}>
              {TASK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {TYPE_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Parent"
            hint={
              parentTypes.length === 0
                ? 'Epics are always top level'
                : 'Optional — nest under a higher level'
            }
          >
            <Select
              value={parentId}
              disabled={parentTypes.length === 0 || parentCandidates.length === 0}
              onChange={(event) => setParentId(event.target.value)}
            >
              <option value="">
                {parentCandidates.length === 0 ? 'No parent available' : 'No parent (top level)'}
              </option>
              {parentCandidates.map((parent) => (
                <option key={parent.id} value={parent.id}>
                  [{TYPE_LABELS[parent.type]}] {parent.title}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Priority">
            <Select value={priority} onChange={(event) => setPriority(event.target.value as TaskPriority)}>
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {PRIORITY_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Due date">
            <Input
              type="datetime-local"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
            />
          </Field>
          <Field label="Estimate" hint="Story points or hours, per project setting">
            <Input
              type="number"
              min={0}
              step="0.5"
              value={estimate}
              onChange={(event) => setEstimate(event.target.value)}
              placeholder="5"
            />
          </Field>
        </div>
        <Field label="Assignee">
          <Select value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
            <option value="">Unassigned</option>
            {members.map((membership) => (
              <option key={membership.user_id} value={membership.user_id}>
                {membership.user?.full_name || membership.user?.email || membership.user_id}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Labels">
          <LabelPicker
            labels={labels.data ?? []}
            selectedIds={labelIds}
            onChange={setLabelIds}
          />
        </Field>
      </div>
    </Modal>
  )
}
