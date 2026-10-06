import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderKanban, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Textarea,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, projectsApi, templatesApi } from '../lib/api'
import { useProjects } from '../lib/hooks'
import { canManage } from '../lib/types'
import { cn, formatDate } from '../lib/utils'

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'archived', label: 'Archived' },
] as const

export function ProjectsPage() {
  const { org, role } = useOrg()
  const [filter, setFilter] = useState('')
  const projects = useProjects(org.slug, filter)
  const queryClient = useQueryClient()
  const toast = useToast()

  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const templates = useQuery({
    queryKey: ['orgs', org.slug, 'project-templates'],
    queryFn: () => templatesApi.listProjectTemplates(org.slug),
  })

  const create = useMutation({
    mutationFn: () =>
      templateId
        ? templatesApi.createProjectFromTemplate(org.slug, {
            name: name.trim(),
            template_id: templateId,
            description: description.trim() || null,
          })
        : projectsApi.create(org.slug, {
            name: name.trim(),
            description: description.trim() || undefined,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'projects'] })
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'labels'] })
      setOpen(false)
      setName('')
      setDescription('')
      setTemplateId('')
      setError(null)
      toast.success('Project created')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create project'),
  })

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Projects</h1>
          <p className="text-sm text-slate-500">Everything your team is working on.</p>
        </div>
        {canManage(role) && (
          <Button onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> New project
          </Button>
        )}
      </div>

      <div className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1 text-sm">
        {FILTERS.map((entry) => (
          <button
            key={entry.value}
            onClick={() => setFilter(entry.value)}
            className={cn(
              'rounded-md px-3 py-1.5 font-medium transition-colors',
              filter === entry.value
                ? 'bg-brand-50 text-brand-700'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700',
            )}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {projects.isLoading && <PageSpinner />}
      {projects.isError && (
        <ErrorState message="Could not load projects." onRetry={() => void projects.refetch()} />
      )}

      {projects.data?.length === 0 && (
        <EmptyState
          icon={<FolderKanban className="h-8 w-8" />}
          title="No projects here"
          description={
            canManage(role)
              ? 'Create a project to start tracking tasks on a board.'
              : 'Ask a manager to create the first project.'
          }
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {projects.data?.map((project) => (
          <Link key={project.id} to={`/org/${org.slug}/projects/${project.id}`}>
            <Card className="flex h-full flex-col p-5 transition-shadow hover:shadow-md">
              <div className="flex items-start justify-between gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                  <FolderKanban className="h-5 w-5" />
                </span>
                <Badge
                  className={
                    project.status === 'active'
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-100 text-slate-600'
                  }
                >
                  {project.status}
                </Badge>
              </div>
              <p className="mt-3 font-semibold text-slate-900">{project.name}</p>
              <p className="mt-1 line-clamp-2 flex-1 text-sm text-slate-500">
                {project.description || 'No description'}
              </p>
              <p className="mt-3 text-xs text-slate-400">Created {formatDate(project.created_at)}</p>
            </Card>
          </Link>
        ))}
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="New project"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              disabled={name.trim().length === 0}
            >
              Create project
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field
            label="Template"
            hint="Scrum/Kanban/Bug triage preset, a saved template, or blank"
          >
            <Select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
              <option value="">Blank project</option>
              {(templates.data ?? []).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.is_builtin ? '★ ' : ''}
                  {template.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name">
            <Input
              autoFocus
              value={name}
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
              placeholder="Website redesign"
            />
          </Field>
          <Field label="Description">
            <Textarea
              value={description}
              maxLength={10_000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is this project about?"
            />
          </Field>
        </div>
      </Modal>
    </div>
  )
}
