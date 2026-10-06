import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, CheckCircle2, ListChecks, Plus, ScrollText, Trash2, XCircle, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
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
import { ApiError, automationsApi, type AutomationRuleInput } from '../lib/api'
import {
  useAutomationExecutions,
  useAutomations,
  useAutomationTemplates,
  useLabels,
  useOrgMembers,
  useProjects,
} from '../lib/hooks'
import type {
  AutomationAction,
  AutomationCondition,
  AutomationRuleRead,
  AutomationTemplateRead,
  AutomationTrigger,
} from '../lib/types'
import { AUTOMATION_TRIGGER_LABELS } from '../lib/types'
import { cn, formatDate } from '../lib/utils'

const TRIGGERS: AutomationTrigger[] = [
  'task_created',
  'task_updated',
  'status_changed',
  'comment_created',
  'schedule',
]
const CONDITION_FIELDS = [
  'priority',
  'status',
  'status_category',
  'type',
  'title',
  'estimate',
  'assignee',
  'labels',
  'comment_body',
]
const CONDITION_OPS = [
  'equals',
  'not_equals',
  'contains',
  'not_contains',
  'in',
  'not_in',
  'gt',
  'lt',
  'is_set',
  'is_empty',
]
const ACTION_TYPES = [
  'assign',
  'transition',
  'comment',
  'notify',
  'webhook',
  'add_label',
  'set_priority',
]
const ACTION_LABELS: Record<string, string> = {
  assign: 'Assign someone',
  transition: 'Move to status',
  comment: 'Post a comment',
  notify: 'Notify people',
  webhook: 'Call a webhook',
  add_label: 'Add a label',
  set_priority: 'Set priority',
}

const EMPTY_ACTION: AutomationAction = { type: 'comment', body: '' }
const EMPTY_CONDITION: AutomationCondition = { field: 'priority', op: 'equals', value: '' }

interface RuleDraft {
  name: string
  description: string
  project_id: string
  trigger_type: AutomationTrigger
  to_status: string
  interval: string
  at: string
  conditions: AutomationCondition[]
  actions: AutomationAction[]
  is_active: boolean
}

function emptyDraft(): RuleDraft {
  return {
    name: '',
    description: '',
    project_id: '',
    trigger_type: 'task_created',
    to_status: '',
    interval: 'daily',
    at: '09:00',
    conditions: [],
    actions: [{ ...EMPTY_ACTION }],
    is_active: true,
  }
}

function draftFromRule(rule: AutomationRuleRead): RuleDraft {
  return {
    name: rule.name,
    description: rule.description ?? '',
    project_id: rule.project_id ?? '',
    trigger_type: rule.trigger_type,
    to_status: String(rule.trigger_config?.to_status ?? ''),
    interval: String(rule.trigger_config?.interval ?? 'daily'),
    at: String(rule.trigger_config?.at ?? '09:00'),
    conditions: (rule.conditions ?? []).map((condition) => ({ ...condition })),
    actions: rule.actions.map((action) => ({ ...action })),
    is_active: rule.is_active,
  }
}

function draftFromTemplate(template: AutomationTemplateRead): RuleDraft {
  const draft = emptyDraft()
  draft.name = template.name
  draft.description = template.description
  draft.trigger_type = template.trigger_type
  draft.conditions = (template.conditions ?? []).map((condition) => ({ ...condition }))
  draft.actions = template.actions.map((action) => ({ ...action }))
  draft.interval = String(template.trigger_config?.interval ?? 'daily')
  draft.at = String(template.trigger_config?.at ?? '09:00')
  draft.to_status = String(template.trigger_config?.to_status ?? '')
  return draft
}

function draftToInput(draft: RuleDraft): AutomationRuleInput {
  const trigger_config: Record<string, unknown> = {}
  if (draft.trigger_type === 'status_changed' && draft.to_status.trim()) {
    trigger_config.to_status = draft.to_status.trim()
  }
  if (draft.trigger_type === 'schedule') {
    trigger_config.interval = draft.interval
    trigger_config.at = draft.at
  }
  const conditions = draft.conditions
    .filter((condition) => condition.field)
    .map((condition) => ({
      ...condition,
      value:
        condition.op === 'is_set' || condition.op === 'is_empty'
          ? null
          : condition.value,
    }))
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    project_id: draft.project_id || null,
    trigger_type: draft.trigger_type,
    trigger_config: Object.keys(trigger_config).length ? trigger_config : null,
    conditions: conditions.length ? conditions : null,
    actions: draft.actions,
    is_active: draft.is_active,
  }
}

function RuleModal({
  open,
  onClose,
  slug,
  initial,
  editing,
}: {
  open: boolean
  onClose: () => void
  slug: string
  initial: RuleDraft
  editing: AutomationRuleRead | null
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const projects = useProjects(slug)
  const members = useOrgMembers(slug)
  const labels = useLabels(slug)
  const [draft, setDraft] = useState<RuleDraft>(initial)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['orgs', slug, 'automations'] })
  }

  const save = useMutation({
    mutationFn: () =>
      editing
        ? automationsApi.update(slug, editing.id, draftToInput(draft))
        : automationsApi.create(slug, draftToInput(draft)),
    onSuccess: () => {
      invalidate()
      toast.success(editing ? 'Rule updated' : 'Rule created')
      onClose()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not save rule'),
  })

  const valid =
    draft.name.trim().length > 0 &&
    draft.actions.length > 0 &&
    draft.actions.every((action) => action.type)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? 'Edit automation rule' : 'New automation rule'}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!valid} loading={save.isPending}>
            {editing ? 'Save rule' : 'Create rule'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            <Input
              value={draft.name}
              maxLength={128}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder="Notify leads on urgent work"
            />
          </Field>
          <Field label="Applies to" hint="Org-wide when empty">
            <Select
              value={draft.project_id}
              onChange={(event) => setDraft({ ...draft, project_id: event.target.value })}
            >
              <option value="">All projects</option>
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Description">
          <Input
            value={draft.description}
            maxLength={2000}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          />
        </Field>

        {/* Trigger */}
        <div className="space-y-2 rounded-lg border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Trigger</p>
          <Select
            value={draft.trigger_type}
            onChange={(event) =>
              setDraft({ ...draft, trigger_type: event.target.value as AutomationTrigger })
            }
          >
            {TRIGGERS.map((trigger) => (
              <option key={trigger} value={trigger}>
                {AUTOMATION_TRIGGER_LABELS[trigger]}
              </option>
            ))}
          </Select>
          {draft.trigger_type === 'status_changed' && (
            <Field label="To status" hint="Workflow status key, e.g. in_review">
              <Input
                value={draft.to_status}
                onChange={(event) => setDraft({ ...draft, to_status: event.target.value })}
                placeholder="in_review"
              />
            </Field>
          )}
          {draft.trigger_type === 'schedule' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Interval">
                <Select
                  value={draft.interval}
                  onChange={(event) => setDraft({ ...draft, interval: event.target.value })}
                >
                  <option value="hourly">Hourly</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </Select>
              </Field>
              {draft.interval === 'daily' && (
                <Field label="At (UTC)">
                  <Input
                    type="time"
                    value={draft.at}
                    onChange={(event) => setDraft({ ...draft, at: event.target.value })}
                  />
                </Field>
              )}
            </div>
          )}
        </div>

        {/* Conditions */}
        <div className="space-y-2 rounded-lg border border-slate-200 p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Conditions
            </p>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                setDraft({ ...draft, conditions: [...draft.conditions, { ...EMPTY_CONDITION }] })
              }
            >
              <Plus className="h-3.5 w-3.5" /> Condition
            </Button>
          </div>
          {draft.conditions.length === 0 && (
            <p className="text-xs text-slate-400">Always run (no conditions).</p>
          )}
          {draft.conditions.map((condition, index) => (
            <div key={index} className="flex items-center gap-2">
              <Select
                className="w-40"
                value={condition.field}
                onChange={(event) => {
                  const next = [...draft.conditions]
                  next[index] = { ...condition, field: event.target.value }
                  setDraft({ ...draft, conditions: next })
                }}
              >
                {CONDITION_FIELDS.map((field) => (
                  <option key={field} value={field}>
                    {field}
                  </option>
                ))}
              </Select>
              <Select
                className="w-36"
                value={condition.op}
                onChange={(event) => {
                  const next = [...draft.conditions]
                  next[index] = { ...condition, op: event.target.value }
                  setDraft({ ...draft, conditions: next })
                }}
              >
                {CONDITION_OPS.map((op) => (
                  <option key={op} value={op}>
                    {op.replace('_', ' ')}
                  </option>
                ))}
              </Select>
              {!['is_set', 'is_empty'].includes(condition.op) && (
                <Input
                  value={String(condition.value ?? '')}
                  placeholder="value"
                  onChange={(event) => {
                    const next = [...draft.conditions]
                    next[index] = { ...condition, value: event.target.value }
                    setDraft({ ...draft, conditions: next })
                  }}
                />
              )}
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                onClick={() =>
                  setDraft({
                    ...draft,
                    conditions: draft.conditions.filter((_, i) => i !== index),
                  })
                }
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div className="space-y-2 rounded-lg border border-slate-200 p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Actions</p>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setDraft({ ...draft, actions: [...draft.actions, { ...EMPTY_ACTION }] })}
            >
              <Plus className="h-3.5 w-3.5" /> Action
            </Button>
          </div>
          {draft.actions.map((action, index) => {
            const updateAction = (patch: Partial<AutomationAction>) => {
              const next = [...draft.actions]
              next[index] = { ...action, ...patch }
              setDraft({ ...draft, actions: next })
            }
            return (
              <div key={index} className="space-y-2 rounded border border-slate-100 p-2">
                <div className="flex items-center gap-2">
                  <Select
                    className="w-48"
                    value={action.type}
                    onChange={(event) =>
                      updateAction({ type: event.target.value as AutomationAction['type'] })
                    }
                  >
                    {ACTION_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {ACTION_LABELS[type]}
                      </option>
                    ))}
                  </Select>
                  <button
                    className="ml-auto rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        actions: draft.actions.filter((_, i) => i !== index),
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                {action.type === 'assign' && (
                  <Select
                    value={action.assignee_id ?? ''}
                    onChange={(event) => updateAction({ assignee_id: event.target.value })}
                  >
                    <option value="">Select assignee…</option>
                    {(members.data ?? []).map((member) => (
                      <option key={member.user_id} value={member.user_id}>
                        {member.user?.full_name || member.user?.email || member.user_id}
                      </option>
                    ))}
                  </Select>
                )}
                {action.type === 'transition' && (
                  <Input
                    value={action.status ?? ''}
                    placeholder="Status key, e.g. in_progress"
                    onChange={(event) => updateAction({ status: event.target.value })}
                  />
                )}
                {action.type === 'comment' && (
                  <Textarea
                    value={action.body ?? ''}
                    maxLength={20_000}
                    placeholder="Comment body (Markdown)"
                    onChange={(event) => updateAction({ body: event.target.value })}
                  />
                )}
                {action.type === 'notify' && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Select
                      value={action.role ?? ''}
                      onChange={(event) =>
                        updateAction({ role: event.target.value || null, user_id: null })
                      }
                    >
                      <option value="">Notify a role…</option>
                      <option value="owner">Owners</option>
                      <option value="admin">Admins</option>
                      <option value="manager">Managers</option>
                      <option value="member">All members</option>
                    </Select>
                    <Select
                      value={action.user_id ?? ''}
                      onChange={(event) =>
                        updateAction({ user_id: event.target.value || null, role: null })
                      }
                    >
                      <option value="">…or a specific person</option>
                      {(members.data ?? []).map((member) => (
                        <option key={member.user_id} value={member.user_id}>
                          {member.user?.full_name || member.user?.email || member.user_id}
                        </option>
                      ))}
                    </Select>
                  </div>
                )}
                {action.type === 'webhook' && (
                  <Input
                    value={action.url ?? ''}
                    placeholder="https://example.com/hooks/teamflow"
                    onChange={(event) => updateAction({ url: event.target.value })}
                  />
                )}
                {action.type === 'add_label' && (
                  <Select
                    value={action.label_id ?? ''}
                    onChange={(event) => updateAction({ label_id: event.target.value })}
                  >
                    <option value="">Select label…</option>
                    {(labels.data ?? []).map((label) => (
                      <option key={label.id} value={label.id}>
                        {label.name}
                      </option>
                    ))}
                  </Select>
                )}
                {action.type === 'set_priority' && (
                  <Select
                    value={action.priority ?? 'high'}
                    onChange={(event) =>
                      updateAction({
                        priority: event.target.value as AutomationAction['priority'],
                      })
                    }
                  >
                    {['low', 'medium', 'high', 'urgent'].map((priority) => (
                      <option key={priority} value={priority}>
                        {priority}
                      </option>
                    ))}
                  </Select>
                )}
              </div>
            )
          })}
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}
            className="h-4 w-4 rounded border-slate-300 text-brand-600"
          />
          Rule is active
        </label>
      </div>
    </Modal>
  )
}

export function AutomationsPage() {
  const { org } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const rules = useAutomations(org.slug)
  const templates = useAutomationTemplates(org.slug)
  const executions = useAutomationExecutions(org.slug)
  const projects = useProjects(org.slug)
  const [tab, setTab] = useState<'rules' | 'templates' | 'executions'>('rules')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<AutomationRuleRead | null>(null)
  const [initialDraft, setInitialDraft] = useState<RuleDraft>(emptyDraft())
  const [deleting, setDeleting] = useState<AutomationRuleRead | null>(null)

  const projectNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const project of projects.data ?? []) map.set(project.id, project.name)
    return map
  }, [projects.data])

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'automations'] })
  }

  const remove = useMutation({
    mutationFn: (rule: AutomationRuleRead) => automationsApi.remove(org.slug, rule.id),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success('Rule deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete rule'),
  })

  const toggle = useMutation({
    mutationFn: (rule: AutomationRuleRead) =>
      automationsApi.update(org.slug, rule.id, { is_active: !rule.is_active }),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update rule'),
  })

  function openEditor(rule: AutomationRuleRead | null, template?: AutomationTemplateRead) {
    setEditing(rule)
    setInitialDraft(
      rule ? draftFromRule(rule) : template ? draftFromTemplate(template) : emptyDraft(),
    )
    setEditorOpen(true)
  }

  const TABS = [
    { id: 'rules' as const, label: 'Rules', icon: Zap },
    { id: 'templates' as const, label: 'Templates', icon: ListChecks },
    { id: 'executions' as const, label: 'Execution log', icon: ScrollText },
  ]

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Automations</h1>
          <p className="text-sm text-slate-500">
            If-this-then-that rules that handle recurring coordination for you.
          </p>
        </div>
        <Button size="sm" onClick={() => openEditor(null)}>
          <Plus className="h-4 w-4" /> New rule
        </Button>
      </div>

      <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-0.5">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            onClick={() => setTab(entry.id)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              tab === entry.id
                ? 'bg-slate-900 text-white'
                : 'text-slate-500 hover:text-slate-700',
            )}
          >
            <entry.icon className="h-4 w-4" /> {entry.label}
          </button>
        ))}
      </div>

      {tab === 'rules' && (
        <div className="space-y-2">
          {rules.isLoading && <PageSpinner />}
          {rules.isError && (
            <ErrorState message="Could not load rules." onRetry={() => void rules.refetch()} />
          )}
          {rules.data?.length === 0 && (
            <EmptyState
              icon={<Bot className="h-8 w-8" />}
              title="No automation rules yet"
              description="Start from a template or build a rule from scratch."
              action={
                <Button size="sm" onClick={() => setTab('templates')}>
                  Browse templates
                </Button>
              }
            />
          )}
          {rules.data?.map((rule) => (
            <Card key={rule.id} className="flex flex-wrap items-center gap-3 p-4">
              <span
                className={cn(
                  'h-2 w-2 shrink-0 rounded-full',
                  rule.is_active ? 'bg-emerald-500' : 'bg-slate-300',
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-800">{rule.name}</p>
                <p className="text-xs text-slate-500">
                  {AUTOMATION_TRIGGER_LABELS[rule.trigger_type]}
                  {rule.project_id
                    ? ` · ${projectNames.get(rule.project_id) ?? 'project'}`
                    : ' · all projects'}
                  {rule.conditions?.length
                    ? ` · ${rule.conditions.length} condition(s)`
                    : ''}
                  {` · ${rule.actions.length} action(s)`}
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-400">
                <span>{rule.run_count} runs</span>
                {rule.last_run_at && <span>last {formatDate(rule.last_run_at)}</span>}
              </div>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => toggle.mutate(rule)}>
                  {rule.is_active ? 'Pause' : 'Activate'}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => openEditor(rule)}>
                  Edit
                </Button>
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  onClick={() => setDeleting(rule)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'templates' && (
        <div className="grid gap-3 md:grid-cols-2">
          {templates.data?.map((template) => (
            <Card key={template.id} className="space-y-2 p-4">
              <p className="text-sm font-semibold text-slate-800">{template.name}</p>
              <p className="text-xs text-slate-500">{template.description}</p>
              <div className="flex items-center justify-between">
                <Badge className="bg-slate-100 text-slate-600">
                  {AUTOMATION_TRIGGER_LABELS[template.trigger_type]}
                </Badge>
                <Button size="sm" variant="secondary" onClick={() => openEditor(null, template)}>
                  Use template
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'executions' && (
        <div className="space-y-2">
          {executions.isLoading && <PageSpinner />}
          {executions.data?.length === 0 && (
            <p className="text-sm text-slate-400">No executions recorded yet.</p>
          )}
          {executions.data?.map((execution) => (
            <Card key={execution.id} className="flex items-start gap-3 p-3">
              {execution.status === 'success' ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
              ) : execution.status === 'failed' ? (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              ) : (
                <Bot className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">
                  {execution.rule_name ?? 'Rule'} · {execution.trigger_event}
                </p>
                <p className="text-xs text-slate-500">
                  {execution.actions_log
                    .map((entry) => `${entry.action}: ${entry.status}`)
                    .join(' · ') || 'no actions'}
                </p>
                {execution.error && (
                  <p className="text-xs text-red-600">Error: {execution.error}</p>
                )}
              </div>
              <span className="shrink-0 text-xs text-slate-400">
                {formatDate(execution.created_at)}
              </span>
            </Card>
          ))}
        </div>
      )}

      {editorOpen && (
        <RuleModal
          key={editing?.id ?? initialDraft.name}
          open={editorOpen}
          onClose={() => setEditorOpen(false)}
          slug={org.slug}
          initial={initialDraft}
          editing={editing}
        />
      )}

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Delete automation rule"
        message={`Delete "${deleting?.name ?? ''}"? Its execution history is removed too.`}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  )
}
