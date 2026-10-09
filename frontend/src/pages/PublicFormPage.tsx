import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { Button, ErrorState, Field, Input, PageSpinner, Select, Textarea } from '../components/ui'
import { LanguageToggle } from '../components/LanguageToggle'
import { ApiError, formsApi } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { PRIORITIES, PRIORITY_LABELS, type FormField, type FormSubmitted } from '../lib/types'

function defaultValues(fields: FormField[]): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of fields) values[field.key] = ''
  return values
}

export function PublicFormPage() {
  const { slug } = useParams<{ slug: string }>()
  const { t } = useI18n()
  const form = useQuery({
    queryKey: ['public-form', slug ?? ''],
    queryFn: () => formsApi.publicGet(slug as string),
    enabled: Boolean(slug),
    retry: false,
  })
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<FormSubmitted | null>(null)

  const submit = useMutation({
    mutationFn: () => formsApi.submit(slug as string, values),
    onSuccess: (result) => setSubmitted(result),
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : t('forms.submitError', 'Could not submit the form'),
      ),
  })

  if (form.isLoading) return <PageSpinner label={t('forms.loadingPublic', 'Loading form…')} />
  if (form.isError || !form.data) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState
          message={t('forms.publicNotFound', 'This form does not exist or is no longer public.')}
        />
      </div>
    )
  }

  const definition = form.data
  const current = { ...defaultValues(definition.fields), ...values }

  function update(key: string, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }))
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    for (const field of definition.fields) {
      if (field.required && !current[field.key]?.trim()) {
        setError(t('forms.fieldRequired', '"{field}" is required', { field: field.label }))
        return
      }
    }
    submit.mutate()
  }

  return (
    <div className="relative flex min-h-full items-start justify-center bg-slate-50 px-4 py-10">
      <div className="absolute end-4 top-4">
        <LanguageToggle />
      </div>
      <div className="w-full max-w-xl">
        <div className="mb-6 text-center">
          <p className="text-lg font-bold tracking-tight text-brand-700">
            {t('common.brand', 'TeamFlow')}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {submitted ? (
            <div className="space-y-3 py-6 text-center">
              <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
              <h1 className="text-lg font-semibold text-slate-900">
                {t('forms.thanks', 'Thanks — we got it')}
              </h1>
              <p className="text-sm text-slate-500">
                {submitted.task_key
                  ? t('forms.createdAs', 'Your request was created as {key}.', {
                      key: submitted.task_key,
                    })
                  : submitted.detail}
              </p>
            </div>
          ) : (
            <>
              <h1 className="text-xl font-semibold text-slate-900">{definition.name}</h1>
              <p className="mt-1 text-sm text-slate-500">
                {definition.description ??
                  t('forms.submitTo', 'Submit a request to {project}.', {
                    project: definition.project_name,
                  })}
              </p>
              <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
                {error && <ErrorState message={error} />}
                {definition.fields.map((field) => (
                  <Field key={field.key} label={`${field.label}${field.required ? ' *' : ''}`}>
                    {field.type === 'textarea' ? (
                      <Textarea
                        value={current[field.key] ?? ''}
                        onChange={(event) => update(field.key, event.target.value)}
                      />
                    ) : field.type === 'select' ? (
                      <Select
                        value={current[field.key] ?? ''}
                        onChange={(event) => update(field.key, event.target.value)}
                      >
                        <option value="">{t('forms.select', 'Select…')}</option>
                        {field.options.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </Select>
                    ) : field.type === 'priority' ? (
                      <Select
                        value={current[field.key] ?? ''}
                        onChange={(event) => update(field.key, event.target.value)}
                      >
                        <option value="">{t('forms.select', 'Select…')}</option>
                        {PRIORITIES.map((priority) => (
                          <option key={priority} value={priority}>
                            {t(`priority.${priority}`, PRIORITY_LABELS[priority])}
                          </option>
                        ))}
                      </Select>
                    ) : field.type === 'date' ? (
                      <Input
                        type="date"
                        value={current[field.key] ?? ''}
                        onChange={(event) => update(field.key, event.target.value)}
                      />
                    ) : (
                      <Input
                        type={field.type === 'user' ? 'email' : 'text'}
                        value={current[field.key] ?? ''}
                        onChange={(event) => update(field.key, event.target.value)}
                      />
                    )}
                  </Field>
                ))}
                {definition.fields.length === 0 && (
                  <p className="text-sm text-slate-400">
                    {t('forms.noFieldsConfigured', 'This form has no fields configured.')}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  loading={submit.isPending}
                  disabled={definition.fields.length === 0}
                >
                  {t('common.submit', 'Submit')}
                </Button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
