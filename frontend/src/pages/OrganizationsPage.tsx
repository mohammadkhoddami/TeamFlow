import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, organizationsApi } from '../lib/api'
import { qk, useOrganizations } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { ROLE_LABELS, type MembershipRole } from '../lib/types'

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
}

export function OrganizationsPage() {
  const organizations = useOrganizations()
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => organizationsApi.create({ name: name.trim(), slug }),
    onSuccess: (org) => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs })
      setOpen(false)
      setName('')
      setSlug('')
      setSlugTouched(false)
      toast.success(t('organizations.created', 'Workspace "{name}" created', { name: org.name }))
    },
    onError: (err) => {
      setError(
        err instanceof ApiError
          ? err.message
          : t('organizations.createError', 'Could not create workspace'),
      )
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">
            {t('organizations.title', 'Workspaces')}
          </h1>
          <p className="text-sm text-slate-500">
            {t('organizations.subtitle', 'Pick a workspace or create a new one.')}
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> {t('organizations.new', 'New workspace')}
        </Button>
      </div>

      {organizations.isLoading && <PageSpinner />}
      {organizations.isError && (
        <ErrorState
          message={t('organizations.loadError', 'Could not load workspaces.')}
          onRetry={() => void organizations.refetch()}
        />
      )}

      {organizations.data && organizations.data.length === 0 && (
        <EmptyState
          icon={<Building2 className="h-8 w-8" />}
          title={t('organizations.emptyTitle', 'No workspaces yet')}
          description={t(
            'organizations.emptyBody',
            'Create your first workspace to start managing projects and tasks.',
          )}
          action={
            <Button onClick={() => setOpen(true)}>
              {t('organizations.create', 'Create workspace')}
            </Button>
          }
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {organizations.data?.map(({ organization, role }) => (
          <Link key={organization.id} to={`/org/${organization.slug}/dashboard`}>
            <Card className="h-full p-5 transition-shadow hover:shadow-md">
              <div className="flex items-start justify-between gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                  <Building2 className="h-5 w-5" />
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {t(`role.${role}`, ROLE_LABELS[role as MembershipRole] ?? role)}
                </span>
              </div>
              <p className="mt-3 font-semibold text-slate-900">{organization.name}</p>
              <p className="text-xs text-slate-500">/{organization.slug}</p>
            </Card>
          </Link>
        ))}
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('organizations.new', 'New workspace')}
        description={t(
          'organizations.newHint',
          'Workspaces are the tenant boundary: projects, tasks and members live inside one.',
        )}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              disabled={name.trim().length === 0 || slug.length < 2}
            >
              {t('common.create', 'Create')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field label={t('common.name', 'Name')}>
            <Input
              value={name}
              autoFocus
              onChange={(event) => {
                setName(event.target.value)
                if (!slugTouched) setSlug(slugify(event.target.value))
              }}
              placeholder={t('organizations.namePlaceholder', 'Acme Inc.')}
            />
          </Field>
          <Field
            label={t('organizations.slug', 'Slug')}
            hint={t(
              'organizations.slugHint',
              'Lowercase letters, numbers and dashes; used in URLs.',
            )}
          >
            <Input
              value={slug}
              onChange={(event) => {
                setSlugTouched(true)
                setSlug(slugify(event.target.value))
              }}
              placeholder={t('organizations.slugPlaceholder', 'acme-inc')}
            />
          </Field>
        </div>
      </Modal>
    </div>
  )
}
