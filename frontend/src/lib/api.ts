import { SESSION_EXPIRED_EVENT, tokens } from './tokens'
import type {
  ActivityRead,
  AiApplyResult,
  AiBreakdownItem,
  AiBreakdownProposal,
  ApiTokenCreated,
  ApiTokenRead,
  ApiTokenUsage,
  AttachmentRead,
  AuditLogRead,
  AutomationAction,
  AutomationCondition,
  AutomationExecutionRead,
  AutomationRuleRead,
  AutomationTemplateRead,
  AutomationTrigger,
  BoardRead,
  BulkTaskAction,
  BulkTaskResult,
  BurndownReport,
  CalendarResponse,
  CapacityMemberRead,
  CfdReport,
  ChecklistItemRead,
  CommentRead,
  CursorPage,
  CustomFieldRead,
  CustomRoleInput,
  CustomRoleRead,
  CycleTimeReport,
  DashboardData,
  DashboardInput,
  DashboardRead,
  DashboardStats,
  DownloadGrant,
  EstimationUnit,
  FormInput,
  FormRead,
  FormSubmissionRead,
  FormSubmitted,
  GoalInput,
  GoalRead,
  ImportSummary,
  IntegrationCreated,
  IntegrationEventRead,
  IntegrationRead,
  InvitationRead,
  LabelRead,
  LoginResponse,
  MembershipRead,
  MembershipRole,
  MfaSetup,
  MfaStatus,
  NotificationMuteRead,
  NotificationPreferenceRead,
  NotificationRead,
  OAuthAppCreated,
  OAuthAppRead,
  OrganizationMemberRead,
  OrganizationRead,
  Page,
  PluginCreated,
  PluginDirectoryEntry,
  PluginInstallInput,
  PluginRead,
  ProjectMemberRead,
  ProjectMemberRole,
  ProjectRead,
  ProjectTemplateRead,
  PublicFormRead,
  PushSubscribeInput,
  PushSubscriptionRead,
  ReactionSummary,
  ReleaseRead,
  ReleaseStatus,
  RoadmapResponse,
  SavedFilterRead,
  ScimTokenCreated,
  ScimTokenRead,
  SearchResponse,
  ServiceAccountRead,
  SprintRead,
  SprintReport,
  SsoConfigInput,
  SsoConfigRead,
  SsoPublicConfig,
  TaskAssigneeRead,
  TaskLinkSummary,
  TaskPriority,
  TaskRead,
  TaskStatus,
  TaskTemplateRead,
  TaskTreeNode,
  TaskType,
  TimesheetReport,
  TokenPair,
  UploadGrant,
  UserRead,
  VelocityReport,
  WebhookCreated,
  WebhookDeliveryRead,
  WebhookRead,
  WorkflowStatusInput,
  WorkflowStatusRead,
  WorklogRead,
} from './types'

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly detail?: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

// ------------------------------------------------------------------ inputs

export interface TaskFilters {
  project_id?: string
  status?: TaskStatus[]
  priority?: TaskPriority[]
  type?: TaskType[]
  parent_id?: string
  roots_only?: boolean
  assignee_id?: string
  unassigned?: boolean
  label_id?: string
  search?: string
  due_before?: string
  due_after?: string
  overdue?: boolean
  sprint_id?: string
  backlog_only?: boolean
  include_archived?: boolean
  archived_only?: boolean
  blocked?: boolean
  category?: string[]
  sort?: string
  offset?: number
  limit?: number
}

export interface TaskCreateInput {
  title: string
  description?: string | null
  priority?: TaskPriority
  type?: TaskType
  parent_id?: string | null
  due_date?: string | null
  assignee_id?: string | null
  label_ids?: string[]
  sprint_id?: string | null
  estimate?: number | null
  remaining_estimate?: number | null
  actual_estimate?: number | null
  custom_fields?: Record<string, unknown>
  assignees?: { user_id: string; role: 'assignee' | 'approver' }[]
  checklist?: string[]
  recurrence_rule?: string | null
  release_id?: string | null
}

export interface TaskUpdateInput {
  title?: string
  description?: string | null
  status?: string
  priority?: TaskPriority
  type?: TaskType
  parent_id?: string | null
  due_date?: string | null
  assignee_id?: string | null
  label_ids?: string[]
  sprint_id?: string | null
  estimate?: number | null
  remaining_estimate?: number | null
  actual_estimate?: number | null
  custom_fields?: Record<string, unknown>
  recurrence_rule?: string | null
  release_id?: string | null
}

export interface BulkTaskInput {
  task_ids: string[]
  action: BulkTaskAction
  status?: TaskStatus
  priority?: TaskPriority
  assignee_id?: string | null
  label_ids?: string[]
  sprint_id?: string | null
  project_id?: string | null
  estimate?: number | null
}

// ------------------------------------------------------------- request core

type QueryScalar = string | number | boolean
type QueryValue = QueryScalar | null | undefined | QueryScalar[]

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue
    if (Array.isArray(value)) {
      for (const entry of value) {
        if (entry !== undefined && entry !== null) search.append(key, String(entry))
      }
    } else {
      search.append(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown
  try {
    const body = (await response.json()) as { detail?: unknown }
    detail = body?.detail ?? body
  } catch {
    detail = undefined
  }
  const firstValidation =
    Array.isArray(detail) && detail.length > 0
      ? (detail[0] as { msg?: unknown })
      : undefined
  const message =
    typeof detail === 'string'
      ? detail
      : typeof firstValidation?.msg === 'string'
        ? firstValidation.msg
        : `Request failed with status ${response.status}`
  return new ApiError(response.status, message, detail)
}

let refreshInFlight: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight
  const refreshToken = tokens.getRefresh()
  if (!refreshToken) return false
  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!response.ok) {
        tokens.clear()
        return false
      }
      tokens.set((await response.json()) as TokenPair)
      return true
    } catch {
      tokens.clear()
      return false
    }
  })()
  try {
    return await refreshInFlight
  } finally {
    refreshInFlight = null
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
  retryOn401?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, retryOn401 = true } = options
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const access = auth ? tokens.getAccess() : null
  if (access) headers.Authorization = `Bearer ${access}`

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && auth && retryOn401) {
    // One retry after rotating tokens; anything else tears the session down.
    if (await refreshSession()) {
      return request<T>(path, { ...options, retryOn401: false })
    }
  }
  if (response.status === 401 && auth) {
    tokens.clear()
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204 || response.status === 205) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

// ---------------------------------------------------------------- auth api

export const authApi = {
  register: (data: {
    email: string
    password: string
    full_name?: string
    code: string
  }) =>
    request<UserRead>('/auth/register', {
      method: 'POST',
      body: data,
      auth: false,
      retryOn401: false,
    }),

  async login(email: string, password: string): Promise<LoginResponse> {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }).toString(),
    })
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as LoginResponse
  },

  verifyMfa: (mfaToken: string, code: string) =>
    request<TokenPair>('/auth/mfa/verify', {
      method: 'POST',
      body: { mfa_token: mfaToken, code },
      auth: false,
      retryOn401: false,
    }),

  requestOtp: (email: string) =>
    request<{ detail: string }>('/auth/otp/request', {
      method: 'POST',
      body: { email },
      auth: false,
      retryOn401: false,
    }),

  verifyOtp: (email: string, code: string) =>
    request<TokenPair>('/auth/otp/verify', {
      method: 'POST',
      body: { email, code },
      auth: false,
      retryOn401: false,
    }),

  // Browser navigation target for the Google consent screen.
  googleStartUrl: (): string => `${API_BASE_URL}/auth/google/start`,

  exchangeOAuthCode: (code: string) =>
    request<TokenPair>('/auth/oauth/exchange', {
      method: 'POST',
      body: { code },
      auth: false,
      retryOn401: false,
    }),

  me: () => request<UserRead>('/auth/me'),

  updateMe: (data: { email?: string; full_name?: string; locale?: string }) =>
    request<UserRead>('/auth/me', { method: 'PATCH', body: data }),

  logout: () =>
    request<void>('/auth/logout', {
      method: 'POST',
      body: { refresh_token: tokens.getRefresh() },
    }),

  logoutAll: () => request<void>('/auth/logout-all', { method: 'POST' }),

  forgotPassword: (email: string) =>
    request<{ detail: string }>('/auth/forgot-password', {
      method: 'POST',
      body: { email },
      auth: false,
      retryOn401: false,
    }),

  resetPassword: (token: string, newPassword: string) =>
    request<void>('/auth/reset-password', {
      method: 'POST',
      body: { token, new_password: newPassword },
      auth: false,
      retryOn401: false,
    }),
}

// ---------------------------------------------------------------- mfa api

export const mfaApi = {
  status: () => request<MfaStatus>('/auth/mfa'),

  setup: () => request<MfaSetup>('/auth/mfa/setup', { method: 'POST' }),

  enable: (code: string) =>
    request<MfaStatus>('/auth/mfa/enable', { method: 'POST', body: { code } }),

  disable: (code: string) =>
    request<void>('/auth/mfa/disable', { method: 'POST', body: { code } }),
}

// ------------------------------------------------------- organizations api

export const organizationsApi = {
  list: (params?: { offset?: number; limit?: number }) =>
    request<OrganizationMemberRead[]>(
      `/organizations${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  get: (slug: string) => request<OrganizationRead>(`/organizations/${slug}`),

  create: (data: { name: string; slug: string }) =>
    request<OrganizationRead>('/organizations', { method: 'POST', body: data }),

  update: (
    slug: string,
    data: {
      name?: string
      is_active?: boolean
      accent_color?: string | null
      audit_retention_days?: number | null
    },
  ) =>
    request<OrganizationRead>(`/organizations/${slug}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string) =>
    request<void>(`/organizations/${slug}`, { method: 'DELETE' }),
}

// ------------------------------------------------------------ members api

export const membersApi = {
  list: (slug: string) => request<MembershipRead[]>(`/organizations/${slug}/members`),

  add: (slug: string, data: { user_email: string; role: MembershipRole }) =>
    request<MembershipRead>(`/organizations/${slug}/members`, {
      method: 'POST',
      body: data,
    }),

  updateRole: (
    slug: string,
    userId: string,
    data: { role?: string; custom_role_id?: string | null },
  ) =>
    request<MembershipRead>(`/organizations/${slug}/members/${userId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, userId: string) =>
    request<void>(`/organizations/${slug}/members/${userId}`, { method: 'DELETE' }),
}

// -------------------------------------------------------- invitations api

export const invitationsApi = {
  create: (slug: string, data: { email: string; role: MembershipRole }) =>
    request<InvitationRead>(`/organizations/${slug}/invitations`, {
      method: 'POST',
      body: data,
    }),

  listOrg: (slug: string) =>
    request<InvitationRead[]>(`/organizations/${slug}/invitations`),

  revoke: (slug: string, invitationId: string) =>
    request<void>(`/organizations/${slug}/invitations/${invitationId}`, {
      method: 'DELETE',
    }),

  listMine: () => request<InvitationRead[]>('/invitations/me'),

  accept: (invitationId: string) =>
    request<MembershipRead>(`/invitations/${invitationId}/accept`, { method: 'POST' }),

  decline: (invitationId: string) =>
    request<void>(`/invitations/${invitationId}/decline`, { method: 'POST' }),
}

// ----------------------------------------------------------- projects api

export const projectsApi = {
  list: (slug: string, status?: string) =>
    request<ProjectRead[]>(
      `/organizations/${slug}/projects${buildQuery({ status })}`,
    ),

  create: (slug: string, data: { name: string; description?: string | null }) =>
    request<ProjectRead>(`/organizations/${slug}/projects`, {
      method: 'POST',
      body: data,
    }),

  get: (projectId: string) => request<ProjectRead>(`/projects/${projectId}`),

  update: (
    projectId: string,
    data: {
      name?: string
      description?: string | null
      status?: 'active' | 'archived'
      key?: string
      estimation_unit?: EstimationUnit
      visibility?: 'workspace' | 'private'
    },
  ) =>
    request<ProjectRead>(`/projects/${projectId}`, { method: 'PATCH', body: data }),

  remove: (projectId: string) =>
    request<void>(`/projects/${projectId}`, { method: 'DELETE' }),
}

// -------------------------------------------------------------- tasks api

export const tasksApi = {
  list: (slug: string, filters: TaskFilters) =>
    request<Page<TaskRead>>(
      `/organizations/${slug}/tasks${buildQuery(filters as Record<string, QueryValue>)}`,
    ),

  get: (taskId: string) => request<TaskRead>(`/tasks/${taskId}`),

  create: (projectId: string, data: TaskCreateInput) =>
    request<TaskRead>(`/projects/${projectId}/tasks`, { method: 'POST', body: data }),

  update: (taskId: string, data: TaskUpdateInput) =>
    request<TaskRead>(`/tasks/${taskId}`, { method: 'PATCH', body: data }),

  move: (taskId: string, status: string) =>
    request<TaskRead>(`/tasks/${taskId}/move`, { method: 'POST', body: { status } }),

  remove: (taskId: string) =>
    request<void>(`/tasks/${taskId}`, { method: 'DELETE' }),

  watch: (taskId: string) =>
    request<void>(`/tasks/${taskId}/watchers/me`, { method: 'POST' }),

  unwatch: (taskId: string) =>
    request<void>(`/tasks/${taskId}/watchers/me`, { method: 'DELETE' }),

  watchers: (taskId: string) => request<UserRead[]>(`/tasks/${taskId}/watchers`),

  children: (taskId: string) => request<TaskRead[]>(`/tasks/${taskId}/children`),

  tree: (projectId: string) =>
    request<TaskTreeNode[]>(`/projects/${projectId}/tasks/tree`),

  cursor: (
    slug: string,
    filters: TaskFilters & { cursor?: string | null },
  ) =>
    request<CursorPage<TaskRead>>(
      `/organizations/${slug}/tasks/cursor${buildQuery(
        filters as Record<string, QueryValue>,
      )}`,
    ),

  query: (slug: string, q: string, params?: { offset?: number; limit?: number }) =>
    request<Page<TaskRead>>(
      `/organizations/${slug}/tasks/query${buildQuery({
        q,
        offset: params?.offset,
        limit: params?.limit,
      } as Record<string, QueryValue>)}`,
    ),

  bulk: (slug: string, data: BulkTaskInput) =>
    request<BulkTaskResult>(`/organizations/${slug}/tasks/bulk`, {
      method: 'POST',
      body: data,
    }),

  archive: (taskId: string) =>
    request<TaskRead>(`/tasks/${taskId}/archive`, { method: 'POST' }),

  restore: (taskId: string) =>
    request<TaskRead>(`/tasks/${taskId}/restore`, { method: 'POST' }),
}

// -------------------------------------------------------------- sprints api

export const sprintsApi = {
  list: (projectId: string) =>
    request<SprintRead[]>(`/projects/${projectId}/sprints`),

  create: (
    projectId: string,
    data: { name: string; goal?: string | null; start_date?: string | null; end_date?: string | null },
  ) => request<SprintRead>(`/projects/${projectId}/sprints`, { method: 'POST', body: data }),

  update: (
    sprintId: string,
    data: { name?: string; goal?: string | null; start_date?: string | null; end_date?: string | null },
  ) => request<SprintRead>(`/sprints/${sprintId}`, { method: 'PATCH', body: data }),

  start: (sprintId: string) =>
    request<SprintRead>(`/sprints/${sprintId}/start`, { method: 'POST' }),

  complete: (sprintId: string, carryOverSprintId?: string | null) =>
    request<SprintRead>(`/sprints/${sprintId}/complete`, {
      method: 'POST',
      body: { carry_over_sprint_id: carryOverSprintId ?? null },
    }),

  remove: (sprintId: string) =>
    request<void>(`/sprints/${sprintId}`, { method: 'DELETE' }),

  backlog: (projectId: string, params?: { offset?: number; limit?: number }) =>
    request<Page<TaskRead>>(
      `/projects/${projectId}/sprints/backlog${buildQuery(params as Record<string, QueryValue>)}`,
    ),
}

// ------------------------------------------------------- saved filters api

export const savedFiltersApi = {
  list: (slug: string) =>
    request<SavedFilterRead[]>(`/organizations/${slug}/saved-filters`),

  create: (
    slug: string,
    data: { name: string; query: string; project_id?: string | null; is_shared?: boolean },
  ) => request<SavedFilterRead>(`/organizations/${slug}/saved-filters`, { method: 'POST', body: data }),

  update: (
    slug: string,
    savedFilterId: string,
    data: { name?: string; query?: string; is_shared?: boolean },
  ) =>
    request<SavedFilterRead>(`/organizations/${slug}/saved-filters/${savedFilterId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, savedFilterId: string) =>
    request<void>(`/organizations/${slug}/saved-filters/${savedFilterId}`, {
      method: 'DELETE',
    }),
}

// -------------------------------------------------------------- search api

export const searchApi = {
  global: (slug: string, q: string, limit = 10) =>
    request<SearchResponse>(`/organizations/${slug}/search${buildQuery({ q, limit })}`),
}

// -------------------------------------------------------- preferences api

export const preferencesApi = {
  get: () => request<NotificationPreferenceRead>('/auth/me/notification-preferences'),

  update: (data: Partial<NotificationPreferenceRead>) =>
    request<NotificationPreferenceRead>('/auth/me/notification-preferences', {
      method: 'PUT',
      body: data,
    }),

  unsubscribe: (token: string) =>
    request<{ detail: string }>(`/auth/unsubscribe${buildQuery({ token })}`, {
      method: 'POST',
      auth: false,
      retryOn401: false,
    }),
}

// ----------------------------------------------------------- comments api

export const commentsApi = {
  list: (taskId: string) => request<CommentRead[]>(`/tasks/${taskId}/comments`),

  create: (taskId: string, body: string, parentId?: string | null) =>
    request<CommentRead>(`/tasks/${taskId}/comments`, {
      method: 'POST',
      body: { body, parent_id: parentId ?? null },
    }),

  update: (commentId: string, body: string) =>
    request<CommentRead>(`/comments/${commentId}`, { method: 'PATCH', body: { body } }),

  remove: (commentId: string) =>
    request<void>(`/comments/${commentId}`, { method: 'DELETE' }),

  react: (commentId: string, emoji: string) =>
    request<ReactionSummary>(`/comments/${commentId}/reactions`, {
      method: 'POST',
      body: { emoji },
    }),

  unreact: (commentId: string, emoji: string) =>
    request<void>(
      `/comments/${commentId}/reactions/${encodeURIComponent(emoji)}`,
      { method: 'DELETE' },
    ),
}

// -------------------------------------------------------- attachments api

export const attachmentsApi = {
  list: (taskId: string) =>
    request<AttachmentRead[]>(`/tasks/${taskId}/attachments`),

  createUploadIntent: (
    taskId: string,
    data: { filename: string; content_type: string; size: number },
  ) =>
    request<UploadGrant>(`/tasks/${taskId}/attachments`, {
      method: 'POST',
      body: data,
    }),

  confirm: (taskId: string, attachmentId: string) =>
    request<AttachmentRead>(`/tasks/${taskId}/attachments/${attachmentId}/confirm`, {
      method: 'POST',
    }),

  downloadUrl: (attachmentId: string) =>
    request<DownloadGrant>(`/attachments/${attachmentId}/download-url`, {
      method: 'POST',
    }),

  remove: (attachmentId: string) =>
    request<void>(`/attachments/${attachmentId}`, { method: 'DELETE' }),
}

// Uploads go straight to S3/MinIO via a presigned URL: no Authorization
// header, and failures surface as a plain Error for the caller's catch.
export async function uploadToStorage(
  uploadUrl: string,
  file: File,
  contentType: string,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: file,
  })
  if (!response.ok) {
    throw new ApiError(response.status, `Upload failed with status ${response.status}`)
  }
}

// ------------------------------------------------------ notifications api

export const notificationsApi = {
  list: (params?: { unread_only?: boolean; offset?: number; limit?: number }) =>
    request<Page<NotificationRead>>(
      `/notifications${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  unreadCount: () => request<{ unread: number }>('/notifications/unread-count'),

  markRead: (notificationId: string) =>
    request<NotificationRead>(`/notifications/${notificationId}/read`, {
      method: 'POST',
    }),

  markAllRead: () =>
    request<{ marked: number }>('/notifications/read-all', { method: 'POST' }),

  listMutes: () => request<NotificationMuteRead[]>('/notifications/mutes'),

  addMute: (projectId: string) =>
    request<NotificationMuteRead>('/notifications/mutes', {
      method: 'POST',
      body: { project_id: projectId },
    }),

  removeMute: (projectId: string) =>
    request<void>(`/notifications/mutes/${projectId}`, { method: 'DELETE' }),

  pushSubscriptions: () =>
    request<PushSubscriptionRead[]>('/notifications/push/subscriptions'),

  subscribePush: (data: PushSubscribeInput) =>
    request<PushSubscriptionRead>('/notifications/push/subscribe', {
      method: 'POST',
      body: data,
    }),

  unsubscribePush: (subscriptionId: string) =>
    request<void>(`/notifications/push/subscriptions/${subscriptionId}`, {
      method: 'DELETE',
    }),
}

// ------------------------------------------------------------- labels api

export const labelsApi = {
  list: (slug: string) => request<LabelRead[]>(`/organizations/${slug}/labels`),

  create: (slug: string, data: { name: string; color?: string | null }) =>
    request<LabelRead>(`/organizations/${slug}/labels`, { method: 'POST', body: data }),

  update: (labelId: string, data: { name?: string; color?: string | null }) =>
    request<LabelRead>(`/labels/${labelId}`, { method: 'PATCH', body: data }),

  remove: (labelId: string) =>
    request<void>(`/labels/${labelId}`, { method: 'DELETE' }),
}

// ----------------------------------------------------------- webhooks api

export const webhooksApi = {
  list: (slug: string) => request<WebhookRead[]>(`/organizations/${slug}/webhooks`),

  create: (slug: string, data: { url: string; events: string[]; description?: string | null }) =>
    request<WebhookCreated>(`/organizations/${slug}/webhooks`, {
      method: 'POST',
      body: data,
    }),

  update: (
    slug: string,
    webhookId: string,
    data: { url?: string; events?: string[]; is_active?: boolean; description?: string | null },
  ) =>
    request<WebhookRead>(`/organizations/${slug}/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, webhookId: string) =>
    request<void>(`/organizations/${slug}/webhooks/${webhookId}`, { method: 'DELETE' }),

  deliveries: (
    slug: string,
    webhookId: string,
    params?: { offset?: number; limit?: number },
  ) =>
    request<WebhookDeliveryRead[]>(
      `/organizations/${slug}/webhooks/${webhookId}/deliveries${buildQuery(
        params as Record<string, QueryValue>,
      )}`,
    ),
}

// -------------------------------------------------------------- audit api

export const auditApi = {
  list: (
    slug: string,
    params?: { action?: string; actor_id?: string; offset?: number; limit?: number },
  ) =>
    request<Page<AuditLogRead>>(
      `/organizations/${slug}/audit-logs${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  exportUrl: (slug: string, format: 'csv' | 'json') =>
    `${API_BASE_URL}/organizations/${slug}/audit-logs/export${buildQuery({ format })}`,

  async downloadExport(slug: string, format: 'csv' | 'json'): Promise<void> {
    const access = tokens.getAccess()
    const response = await fetch(
      `${API_BASE_URL}/organizations/${slug}/audit-logs/export${buildQuery({ format })}`,
      { headers: access ? { Authorization: `Bearer ${access}` } : {} },
    )
    if (!response.ok) throw await toApiError(response)
    const text = await response.text()
    downloadBlob(
      text,
      `teamflow-${slug}-audit.${format}`,
      format === 'json' ? 'application/json' : 'text/csv',
    )
  },
}

// ---------------------------------------------------------- dashboard api

export const dashboardApi = {
  get: (slug: string) => request<DashboardStats>(`/organizations/${slug}/dashboard`),
}

// ------------------------------------------------------------- workflows api

export const workflowsApi = {
  get: (projectId: string) =>
    request<WorkflowStatusRead[]>(`/projects/${projectId}/workflow`),

  save: (
    projectId: string,
    data: { statuses: WorkflowStatusInput[]; wip_enforced?: boolean },
  ) =>
    request<WorkflowStatusRead[]>(`/projects/${projectId}/workflow`, {
      method: 'PUT',
      body: data,
    }),

  listBoards: (projectId: string) =>
    request<BoardRead[]>(`/projects/${projectId}/boards`),

  createBoard: (
    projectId: string,
    data: {
      name: string
      swimlane_by?: string
      filter_query?: string | null
      columns?: string[] | null
      is_default?: boolean
    },
  ) => request<BoardRead>(`/projects/${projectId}/boards`, { method: 'POST', body: data }),

  updateBoard: (
    slug: string,
    boardId: string,
    data: {
      name?: string
      swimlane_by?: string
      filter_query?: string | null
      columns?: string[] | null
      is_default?: boolean
    },
  ) =>
    request<BoardRead>(`/organizations/${slug}/boards/${boardId}`, {
      method: 'PATCH',
      body: data,
    }),

  removeBoard: (slug: string, boardId: string) =>
    request<void>(`/organizations/${slug}/boards/${boardId}`, { method: 'DELETE' }),
}

// --------------------------------------------------------- custom fields api

export const customFieldsApi = {
  list: (projectId: string) =>
    request<CustomFieldRead[]>(`/projects/${projectId}/custom-fields`),

  create: (
    projectId: string,
    data: {
      name: string
      key?: string
      field_type: string
      options?: string[]
      is_required?: boolean
    },
  ) =>
    request<CustomFieldRead>(`/projects/${projectId}/custom-fields`, {
      method: 'POST',
      body: data,
    }),

  update: (
    projectId: string,
    fieldId: string,
    data: { name?: string; options?: string[]; is_required?: boolean; position?: number },
  ) =>
    request<CustomFieldRead>(`/projects/${projectId}/custom-fields/${fieldId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (projectId: string, fieldId: string) =>
    request<void>(`/projects/${projectId}/custom-fields/${fieldId}`, {
      method: 'DELETE',
    }),
}

// ----------------------------------------------------------------- links api

export const linksApi = {
  list: (taskId: string) => request<TaskLinkSummary>(`/tasks/${taskId}/links`),

  create: (taskId: string, data: { to_task_id: string; link_type: string }) =>
    request<TaskLinkSummary>(`/tasks/${taskId}/links`, { method: 'POST', body: data }),

  remove: (taskId: string, linkId: string) =>
    request<void>(`/tasks/${taskId}/links/${linkId}`, { method: 'DELETE' }),
}

// --------------------------------------------------------------- reports api

export const reportsApi = {
  burndown: (projectId: string, sprintId: string) =>
    request<BurndownReport>(
      `/projects/${projectId}/reports/burndown${buildQuery({ sprint_id: sprintId })}`,
    ),

  velocity: (projectId: string, limit = 6) =>
    request<VelocityReport>(
      `/projects/${projectId}/reports/velocity${buildQuery({ limit })}`,
    ),

  cumulativeFlow: (projectId: string, days = 30) =>
    request<CfdReport>(
      `/projects/${projectId}/reports/cumulative-flow${buildQuery({ days })}`,
    ),

  cycleTime: (projectId: string, days = 30) =>
    request<CycleTimeReport>(
      `/projects/${projectId}/reports/cycle-time${buildQuery({ days })}`,
    ),

  cycleTimeCsvUrl: (projectId: string, days = 30) =>
    `${API_BASE_URL}/projects/${projectId}/reports/cycle-time${buildQuery({
      days,
      format: 'csv',
    })}`,

  sprintReport: (sprintId: string) =>
    request<SprintReport>(`/sprints/${sprintId}/report`),
}

// -------------------------------------------------------------- capacity api

export const capacityApi = {
  get: (sprintId: string) =>
    request<CapacityMemberRead[]>(`/sprints/${sprintId}/capacity`),

  set: (
    sprintId: string,
    entries: { user_id: string; capacity: number | null; note?: string | null }[],
  ) =>
    request<CapacityMemberRead[]>(`/sprints/${sprintId}/capacity`, {
      method: 'PUT',
      body: { entries },
    }),
}

// -------------------------------------------------------------- worklogs api

export const worklogsApi = {
  list: (taskId: string) => request<WorklogRead[]>(`/tasks/${taskId}/worklogs`),

  create: (
    taskId: string,
    data: { minutes: number; started_at: string; description?: string | null },
  ) => request<WorklogRead>(`/tasks/${taskId}/worklogs`, { method: 'POST', body: data }),

  update: (
    slug: string,
    worklogId: string,
    data: { minutes?: number; started_at?: string; description?: string | null },
  ) =>
    request<WorklogRead>(`/organizations/${slug}/worklogs/${worklogId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, worklogId: string) =>
    request<void>(`/organizations/${slug}/worklogs/${worklogId}`, { method: 'DELETE' }),

  timesheet: (
    slug: string,
    params?: { date_from?: string; date_to?: string; user_id?: string },
  ) =>
    request<TimesheetReport>(
      `/organizations/${slug}/timesheet${buildQuery(params as Record<string, QueryValue>)}`,
    ),
}

// ------------------------------------------------------------- templates api

export const templatesApi = {
  listProjectTemplates: (slug: string) =>
    request<ProjectTemplateRead[]>(`/organizations/${slug}/project-templates`),

  createProjectFromTemplate: (
    slug: string,
    data: { name: string; template_id: string; key?: string; description?: string | null },
  ) =>
    request<ProjectRead>(`/organizations/${slug}/projects/from-template`, {
      method: 'POST',
      body: data,
    }),

  saveProjectAsTemplate: (
    projectId: string,
    data: { name: string; description?: string | null },
  ) =>
    request<ProjectTemplateRead>(`/projects/${projectId}/save-as-template`, {
      method: 'POST',
      body: data,
    }),

  removeProjectTemplate: (slug: string, templateId: string) =>
    request<void>(`/organizations/${slug}/project-templates/${templateId}`, {
      method: 'DELETE',
    }),

  listTaskTemplates: (slug: string, projectId?: string) =>
    request<TaskTemplateRead[]>(
      `/organizations/${slug}/task-templates${buildQuery({ project_id: projectId })}`,
    ),

  createTaskTemplate: (
    slug: string,
    data: {
      name: string
      title: string
      description?: string | null
      priority?: TaskPriority
      type?: TaskType
      estimate?: number | null
      checklist?: string[]
      project_id?: string | null
    },
  ) =>
    request<TaskTemplateRead>(`/organizations/${slug}/task-templates`, {
      method: 'POST',
      body: data,
    }),

  applyTaskTemplate: (
    slug: string,
    templateId: string,
    data: { project_id: string; parent_id?: string | null },
  ) =>
    request<TaskRead>(`/organizations/${slug}/task-templates/${templateId}/apply`, {
      method: 'POST',
      body: data,
    }),

  removeTaskTemplate: (slug: string, templateId: string) =>
    request<void>(`/organizations/${slug}/task-templates/${templateId}`, {
      method: 'DELETE',
    }),
}

// ----------------------------------------------------- checklist/assignees

export const checklistApi = {
  list: (taskId: string) =>
    request<ChecklistItemRead[]>(`/tasks/${taskId}/checklist`),

  add: (taskId: string, text: string) =>
    request<ChecklistItemRead>(`/tasks/${taskId}/checklist`, {
      method: 'POST',
      body: { text },
    }),

  update: (
    taskId: string,
    itemId: string,
    data: { text?: string; is_done?: boolean; position?: number },
  ) =>
    request<ChecklistItemRead>(`/tasks/${taskId}/checklist/${itemId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (taskId: string, itemId: string) =>
    request<void>(`/tasks/${taskId}/checklist/${itemId}`, { method: 'DELETE' }),

  assignees: (taskId: string) =>
    request<TaskAssigneeRead[]>(`/tasks/${taskId}/assignees`),

  setAssignees: (
    taskId: string,
    assignees: { user_id: string; role: 'assignee' | 'approver' }[],
  ) =>
    request<TaskAssigneeRead[]>(`/tasks/${taskId}/assignees`, {
      method: 'PUT',
      body: { assignees },
    }),
}

// ------------------------------------------------------------ import/export

export const dataApi = {
  importFile: async (
    slug: string,
    data: { project_id: string; format: string; dry_run?: boolean; file: File },
  ): Promise<ImportSummary> => {
    const form = new FormData()
    form.append('project_id', data.project_id)
    form.append('format', data.format)
    form.append('dry_run', String(data.dry_run ?? false))
    form.append('file', data.file)
    const access = tokens.getAccess()
    const response = await fetch(`${API_BASE_URL}/organizations/${slug}/imports`, {
      method: 'POST',
      headers: access ? { Authorization: `Bearer ${access}` } : {},
      body: form,
    })
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as ImportSummary
  },

  exportWorkspaceUrl: (slug: string, attachments = false) =>
    `${API_BASE_URL}/organizations/${slug}/export${buildQuery({ attachments })}`,

  exportProjectCsvUrl: (projectId: string) =>
    `${API_BASE_URL}/projects/${projectId}/export`,

  async downloadProjectCsv(projectId: string, filename: string): Promise<void> {
    const access = tokens.getAccess()
    const response = await fetch(`${API_BASE_URL}/projects/${projectId}/export`, {
      headers: access ? { Authorization: `Bearer ${access}` } : {},
    })
    if (!response.ok) throw await toApiError(response)
    downloadBlob(await response.text(), filename, 'text/csv')
  },

  async downloadWorkspace(slug: string, attachments = false): Promise<void> {
    const access = tokens.getAccess()
    const response = await fetch(
      `${API_BASE_URL}/organizations/${slug}/export${buildQuery({ attachments })}`,
      { headers: access ? { Authorization: `Bearer ${access}` } : {} },
    )
    if (!response.ok) throw await toApiError(response)
    downloadBlob(await response.text(), `teamflow-${slug}-export.json`, 'application/json')
  },
}

// --------------------------------------------------- M3 collaboration api

export const activityApi = {
  task: (taskId: string, params?: { offset?: number; limit?: number }) =>
    request<ActivityRead[]>(
      `/tasks/${taskId}/activity${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  project: (projectId: string, params?: { offset?: number; limit?: number }) =>
    request<ActivityRead[]>(
      `/projects/${projectId}/activity${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  org: (slug: string, params?: { offset?: number; limit?: number }) =>
    request<ActivityRead[]>(
      `/organizations/${slug}/activity${buildQuery(params as Record<string, QueryValue>)}`,
    ),
}

// ---------------------------------------------------- releases / roadmap api

export const releasesApi = {
  list: (projectId: string) =>
    request<ReleaseRead[]>(`/projects/${projectId}/releases`),

  create: (
    projectId: string,
    data: {
      name: string
      description?: string | null
      version?: string | null
      status?: ReleaseStatus
      start_date?: string | null
      release_date?: string | null
    },
  ) => request<ReleaseRead>(`/projects/${projectId}/releases`, { method: 'POST', body: data }),

  update: (
    projectId: string,
    releaseId: string,
    data: Partial<{
      name: string
      description: string | null
      version: string | null
      status: ReleaseStatus
      start_date: string | null
      release_date: string | null
    }>,
  ) =>
    request<ReleaseRead>(`/projects/${projectId}/releases/${releaseId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (projectId: string, releaseId: string) =>
    request<void>(`/projects/${projectId}/releases/${releaseId}`, { method: 'DELETE' }),

  roadmap: (projectId: string) =>
    request<RoadmapResponse>(`/projects/${projectId}/roadmap`),
}

// ------------------------------------------------------------- calendar api

export const calendarApi = {
  get: (
    slug: string,
    params?: { start?: string; end?: string; project_id?: string; assignee?: string },
  ) =>
    request<CalendarResponse>(
      `/organizations/${slug}/calendar${buildQuery(params as Record<string, QueryValue>)}`,
    ),
}

// ----------------------------------------------------------- automation api

export interface AutomationRuleInput {
  name: string
  description?: string | null
  project_id?: string | null
  trigger_type: AutomationTrigger
  trigger_config?: Record<string, unknown> | null
  conditions?: AutomationCondition[] | null
  actions: AutomationAction[]
  is_active?: boolean
}

export const automationsApi = {
  list: (slug: string, params?: { project_id?: string; active_only?: boolean }) =>
    request<AutomationRuleRead[]>(
      `/organizations/${slug}/automations${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  templates: (slug: string) =>
    request<AutomationTemplateRead[]>(`/organizations/${slug}/automations/templates`),

  executions: (
    slug: string,
    params?: { rule_id?: string; status?: string; offset?: number; limit?: number },
  ) =>
    request<AutomationExecutionRead[]>(
      `/organizations/${slug}/automations/executions${buildQuery(
        params as Record<string, QueryValue>,
      )}`,
    ),

  create: (slug: string, data: AutomationRuleInput) =>
    request<AutomationRuleRead>(`/organizations/${slug}/automations`, {
      method: 'POST',
      body: data,
    }),

  update: (slug: string, ruleId: string, data: Partial<AutomationRuleInput>) =>
    request<AutomationRuleRead>(`/organizations/${slug}/automations/${ruleId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, ruleId: string) =>
    request<void>(`/organizations/${slug}/automations/${ruleId}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------- integrations api

export const integrationsApi = {
  list: (slug: string, provider?: string) =>
    request<IntegrationRead[]>(
      `/organizations/${slug}/integrations${buildQuery({ provider })}`,
    ),

  create: (
    slug: string,
    data: {
      provider: string
      name: string
      config?: Record<string, unknown>
      events?: string[]
    },
  ) =>
    request<IntegrationCreated>(`/organizations/${slug}/integrations`, {
      method: 'POST',
      body: data,
    }),

  update: (
    slug: string,
    integrationId: string,
    data: Partial<{
      name: string
      config: Record<string, unknown>
      events: string[]
      is_active: boolean
      rotate_secret: boolean
    }>,
  ) =>
    request<IntegrationCreated>(`/organizations/${slug}/integrations/${integrationId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, integrationId: string) =>
    request<void>(`/organizations/${slug}/integrations/${integrationId}`, {
      method: 'DELETE',
    }),

  events: (
    slug: string,
    params?: { integration_id?: string; offset?: number; limit?: number },
  ) =>
    request<IntegrationEventRead[]>(
      `/organizations/${slug}/integrations/events${buildQuery(
        params as Record<string, QueryValue>,
      )}`,
    ),
}

// ---------------------------------------------------- API tokens / OAuth api

export const tokensApi = {
  list: (slug: string, mine = false) =>
    request<ApiTokenRead[]>(`/organizations/${slug}/api-tokens${buildQuery({ mine })}`),

  create: (
    slug: string,
    data: {
      name: string
      scopes: string[]
      expires_in_days?: number | null
      rate_limit_per_minute?: number | null
      service_account_id?: string | null
    },
  ) =>
    request<ApiTokenCreated>(`/organizations/${slug}/api-tokens`, {
      method: 'POST',
      body: data,
    }),

  update: (
    slug: string,
    tokenId: string,
    data: Partial<{
      name: string
      scopes: string[]
      is_active: boolean
      rate_limit_per_minute: number | null
    }>,
  ) =>
    request<ApiTokenRead>(`/organizations/${slug}/api-tokens/${tokenId}`, {
      method: 'PATCH',
      body: data,
    }),

  rotate: (slug: string, tokenId: string) =>
    request<ApiTokenCreated>(`/organizations/${slug}/api-tokens/${tokenId}/rotate`, {
      method: 'POST',
    }),

  revoke: (slug: string, tokenId: string) =>
    request<void>(`/organizations/${slug}/api-tokens/${tokenId}`, { method: 'DELETE' }),

  usage: (slug: string, tokenId: string) =>
    request<ApiTokenUsage>(`/organizations/${slug}/api-tokens/${tokenId}/usage`),

  listServiceAccounts: (slug: string) =>
    request<ServiceAccountRead[]>(`/organizations/${slug}/service-accounts`),

  createServiceAccount: (
    slug: string,
    data: { name: string; description?: string | null; scopes: string[] },
  ) =>
    request<ServiceAccountRead>(`/organizations/${slug}/service-accounts`, {
      method: 'POST',
      body: data,
    }),

  updateServiceAccount: (
    slug: string,
    accountId: string,
    data: Partial<{ name: string; description: string | null; scopes: string[]; is_active: boolean }>,
  ) =>
    request<ServiceAccountRead>(`/organizations/${slug}/service-accounts/${accountId}`, {
      method: 'PATCH',
      body: data,
    }),

  removeServiceAccount: (slug: string, accountId: string) =>
    request<void>(`/organizations/${slug}/service-accounts/${accountId}`, {
      method: 'DELETE',
    }),

  listOAuthApps: (slug: string) =>
    request<OAuthAppRead[]>(`/organizations/${slug}/oauth-apps`),

  createOAuthApp: (
    slug: string,
    data: { name: string; description?: string | null; redirect_uris?: string[]; scopes: string[] },
  ) =>
    request<OAuthAppCreated>(`/organizations/${slug}/oauth-apps`, {
      method: 'POST',
      body: data,
    }),

  updateOAuthApp: (
    slug: string,
    appId: string,
    data: Partial<{ name: string; description: string | null; redirect_uris: string[]; scopes: string[]; is_active: boolean }>,
  ) =>
    request<OAuthAppRead>(`/organizations/${slug}/oauth-apps/${appId}`, {
      method: 'PATCH',
      body: data,
    }),

  rotateOAuthSecret: (slug: string, appId: string) =>
    request<OAuthAppCreated>(`/organizations/${slug}/oauth-apps/${appId}/rotate`, {
      method: 'POST',
    }),

  removeOAuthApp: (slug: string, appId: string) =>
    request<void>(`/organizations/${slug}/oauth-apps/${appId}`, { method: 'DELETE' }),
}

// ------------------------------------------------------------ M4 sso/scim

export const ssoApi = {
  publicConfig: (slug: string) =>
    request<SsoPublicConfig>(`/auth/sso/${slug}/config`, {
      auth: false,
      retryOn401: false,
    }),

  // Browser navigation target that kicks off the OIDC redirect.
  startUrl: (slug: string): string => `${API_BASE_URL}/auth/sso/${slug}/start`,

  getConfig: (slug: string) =>
    request<SsoConfigRead>(`/organizations/${slug}/sso`),

  updateConfig: (slug: string, data: SsoConfigInput) =>
    request<SsoConfigRead>(`/organizations/${slug}/sso`, {
      method: 'PUT',
      body: data,
    }),
}

export const scimApi = {
  listTokens: (slug: string) =>
    request<ScimTokenRead[]>(`/organizations/${slug}/scim-tokens`),

  createToken: (slug: string, name: string) =>
    request<ScimTokenCreated>(`/organizations/${slug}/scim-tokens`, {
      method: 'POST',
      body: { name },
    }),

  revokeToken: (slug: string, tokenId: string) =>
    request<void>(`/organizations/${slug}/scim-tokens/${tokenId}`, {
      method: 'DELETE',
    }),
}

// --------------------------------------------------------------- roles api

export const rolesApi = {
  list: (slug: string) =>
    request<CustomRoleRead[]>(`/organizations/${slug}/roles`),

  create: (slug: string, data: CustomRoleInput) =>
    request<CustomRoleRead>(`/organizations/${slug}/roles`, {
      method: 'POST',
      body: data,
    }),

  update: (slug: string, roleId: string, data: Partial<CustomRoleInput>) =>
    request<CustomRoleRead>(`/organizations/${slug}/roles/${roleId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, roleId: string) =>
    request<void>(`/organizations/${slug}/roles/${roleId}`, { method: 'DELETE' }),
}

// ------------------------------------------------------ project members api

export const projectMembersApi = {
  list: (projectId: string) =>
    request<ProjectMemberRead[]>(`/projects/${projectId}/members`),

  add: (
    projectId: string,
    data: { user_email: string; role: ProjectMemberRole },
  ) =>
    request<ProjectMemberRead>(`/projects/${projectId}/members`, {
      method: 'POST',
      body: data,
    }),

  update: (projectId: string, userId: string, role: ProjectMemberRole) =>
    request<ProjectMemberRead>(`/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      body: { role },
    }),

  remove: (projectId: string, userId: string) =>
    request<void>(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),
}

// --------------------------------------------------------------- goals api

export const goalsApi = {
  list: (slug: string) => request<GoalRead[]>(`/organizations/${slug}/goals`),

  get: (slug: string, goalId: string) =>
    request<GoalRead>(`/organizations/${slug}/goals/${goalId}`),

  create: (slug: string, data: GoalInput) =>
    request<GoalRead>(`/organizations/${slug}/goals`, { method: 'POST', body: data }),

  update: (slug: string, goalId: string, data: Partial<GoalInput>) =>
    request<GoalRead>(`/organizations/${slug}/goals/${goalId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, goalId: string) =>
    request<void>(`/organizations/${slug}/goals/${goalId}`, { method: 'DELETE' }),

  linkTasks: (slug: string, goalId: string, taskIds: string[]) =>
    request<GoalRead>(`/organizations/${slug}/goals/${goalId}/tasks`, {
      method: 'POST',
      body: { task_ids: taskIds },
    }),

  unlinkTask: (slug: string, goalId: string, taskId: string) =>
    request<GoalRead>(`/organizations/${slug}/goals/${goalId}/tasks/${taskId}`, {
      method: 'DELETE',
    }),
}

// ---------------------------------------------------------- dashboards api

export const dashboardsApi = {
  list: (slug: string) =>
    request<DashboardRead[]>(`/organizations/${slug}/dashboards`),

  get: (slug: string, dashboardId: string) =>
    request<DashboardRead>(`/organizations/${slug}/dashboards/${dashboardId}`),

  create: (slug: string, data: DashboardInput) =>
    request<DashboardRead>(`/organizations/${slug}/dashboards`, {
      method: 'POST',
      body: data,
    }),

  update: (slug: string, dashboardId: string, data: Partial<DashboardInput>) =>
    request<DashboardRead>(`/organizations/${slug}/dashboards/${dashboardId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, dashboardId: string) =>
    request<void>(`/organizations/${slug}/dashboards/${dashboardId}`, {
      method: 'DELETE',
    }),

  data: (slug: string, dashboardId: string) =>
    request<DashboardData>(`/organizations/${slug}/dashboards/${dashboardId}/data`),
}

// --------------------------------------------------------------- forms api

export const formsApi = {
  list: (projectId: string) =>
    request<FormRead[]>(`/projects/${projectId}/forms`),

  create: (projectId: string, data: FormInput) =>
    request<FormRead>(`/projects/${projectId}/forms`, { method: 'POST', body: data }),

  update: (projectId: string, formId: string, data: Partial<FormInput>) =>
    request<FormRead>(`/projects/${projectId}/forms/${formId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (projectId: string, formId: string) =>
    request<void>(`/projects/${projectId}/forms/${formId}`, { method: 'DELETE' }),

  submissions: (projectId: string, formId: string) =>
    request<FormSubmissionRead[]>(
      `/projects/${projectId}/forms/${formId}/submissions`,
    ),

  publicGet: (slug: string) =>
    request<PublicFormRead>(`/forms/${slug}`, { auth: false, retryOn401: false }),

  submit: (slug: string, data: Record<string, unknown>) =>
    request<FormSubmitted>(`/forms/${slug}`, {
      method: 'POST',
      body: { data },
      auth: false,
      retryOn401: false,
    }),
}

// ------------------------------------------------------------- plugins api

export const pluginsApi = {
  directory: (slug: string) =>
    request<PluginDirectoryEntry[]>(`/organizations/${slug}/plugins/directory`),

  list: (slug: string) => request<PluginRead[]>(`/organizations/${slug}/plugins`),

  install: (slug: string, data: PluginInstallInput) =>
    request<PluginCreated>(`/organizations/${slug}/plugins`, {
      method: 'POST',
      body: data,
    }),

  update: (
    slug: string,
    pluginId: string,
    data: Partial<{
      name: string
      description: string
      webhook_url: string
      events: string[]
      is_active: boolean
    }>,
  ) =>
    request<PluginRead>(`/organizations/${slug}/plugins/${pluginId}`, {
      method: 'PATCH',
      body: data,
    }),

  remove: (slug: string, pluginId: string) =>
    request<void>(`/organizations/${slug}/plugins/${pluginId}`, { method: 'DELETE' }),
}

// ------------------------------------------------------------------ ai api

export const aiApi = {
  breakdown: (slug: string, description: string) =>
    request<AiBreakdownProposal>(`/organizations/${slug}/ai/breakdown`, {
      method: 'POST',
      body: { description },
    }),

  apply: (
    slug: string,
    data: { project_id: string; parent_id?: string | null; items: AiBreakdownItem[] },
  ) =>
    request<AiApplyResult>(`/organizations/${slug}/ai/breakdown/apply`, {
      method: 'POST',
      body: data,
    }),
}

export const API_BASE = API_BASE_URL

function downloadBlob(content: string, filename: string, contentType: string): void {
  const blob = new Blob([content], { type: contentType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
