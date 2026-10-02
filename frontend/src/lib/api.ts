import { SESSION_EXPIRED_EVENT, tokens } from './tokens'
import type {
  AttachmentRead,
  AuditLogRead,
  CommentRead,
  DashboardStats,
  DownloadGrant,
  InvitationRead,
  LabelRead,
  MembershipRead,
  MembershipRole,
  NotificationRead,
  OrganizationMemberRead,
  OrganizationRead,
  Page,
  ProjectRead,
  TaskPriority,
  TaskRead,
  TaskStatus,
  TaskTreeNode,
  TaskType,
  TokenPair,
  UploadGrant,
  UserRead,
  WebhookCreated,
  WebhookDeliveryRead,
  WebhookRead,
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
}

export interface TaskUpdateInput {
  title?: string
  description?: string | null
  status?: TaskStatus
  priority?: TaskPriority
  type?: TaskType
  parent_id?: string | null
  due_date?: string | null
  assignee_id?: string | null
  label_ids?: string[]
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

  async login(email: string, password: string): Promise<TokenPair> {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }).toString(),
    })
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as TokenPair
  },

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

  updateMe: (data: { email?: string; full_name?: string }) =>
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

// ------------------------------------------------------- organizations api

export const organizationsApi = {
  list: (params?: { offset?: number; limit?: number }) =>
    request<OrganizationMemberRead[]>(
      `/organizations${buildQuery(params as Record<string, QueryValue>)}`,
    ),

  get: (slug: string) => request<OrganizationRead>(`/organizations/${slug}`),

  create: (data: { name: string; slug: string }) =>
    request<OrganizationRead>('/organizations', { method: 'POST', body: data }),

  update: (slug: string, data: { name?: string; is_active?: boolean }) =>
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

  updateRole: (slug: string, userId: string, role: string) =>
    request<MembershipRead>(`/organizations/${slug}/members/${userId}`, {
      method: 'PATCH',
      body: { role },
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
    data: { name?: string; description?: string | null; status?: 'active' | 'archived' },
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

  move: (taskId: string, status: TaskStatus) =>
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
}

// ----------------------------------------------------------- comments api

export const commentsApi = {
  list: (taskId: string) => request<CommentRead[]>(`/tasks/${taskId}/comments`),

  create: (taskId: string, body: string) =>
    request<CommentRead>(`/tasks/${taskId}/comments`, { method: 'POST', body: { body } }),

  update: (commentId: string, body: string) =>
    request<CommentRead>(`/comments/${commentId}`, { method: 'PATCH', body: { body } }),

  remove: (commentId: string) =>
    request<void>(`/comments/${commentId}`, { method: 'DELETE' }),
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
}

// ---------------------------------------------------------- dashboard api

export const dashboardApi = {
  get: (slug: string) => request<DashboardStats>(`/organizations/${slug}/dashboard`),
}
