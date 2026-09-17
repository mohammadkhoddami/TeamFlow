import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useOrg } from '../OrgLayout'
import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { useInvalidateTasks, useLabels } from '../../lib/hooks'
import { PRIORITIES, PRIORITY_LABELS, STATUS_LABELS, type ProjectRead, type TaskPriority, type TaskStatus } from '../../lib/types'
import { fromDateTimeLocal } from '../../lib/utils'
import { Button, ErrorState, Field, Input, Modal, Select, Textarea } from '../ui'
import { LabelPicker } from './LabelPicker'

export function TaskCreateDialog({
  open,
  onClose,
  projectId,
  projects,
  defaultStatus = 'todo',
}: {
  open: boolean
  onClose: () => void
  projectId: string
  projects?: ProjectRead[]
  defaultStatus?: TaskStatus
}) {
  const { org, members } = useOrg()
  const labels = useLabels(org.slug)
  const invalidate = useInvalidateTasks()
  const toast = useToast()

  const [selectedProject, setSelectedProject] = useState(projectId)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('medium')
  const [dueDate, setDueDate] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [labelIds, setLabelIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setSelectedProject(projectId || projects?.[0]?.id || '')
      setTitle('')
      setDescription('')
      setPriority('medium')
      setDueDate('')
      setAssigneeId('')
      setLabelIds([])
      setError(null)
    }
  }, [open, projectId, projects])

  const create = useMutation({
    mutationFn: async () => {
      const task = await tasksApi.create(selectedProject, {
        title: title.trim(),
        description: description.trim() || null,
        priority,
        due_date: dueDate ? fromDateTimeLocal(dueDate) : null,
        assignee_id: assigneeId || null,
        label_ids: labelIds,
      })
      if (defaultStatus !== 'todo') {
        await tasksApi.move(task.id, defaultStatus)
      }
      return task
    },
    onSuccess: () => {
      invalidate(org.slug)
      toast.success('Task created')
      onClose()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create task'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New task"
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
            Create task
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
              onChange={(event) => setSelectedProject(event.target.value)}
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
        <Field label="Description">
          <Textarea
            value={description}
            maxLength={20_000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Add context, acceptance criteria, links…"
          />
        </Field>
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
