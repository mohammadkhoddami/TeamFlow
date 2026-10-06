import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import type {
  BoardRead,
  ChecklistItemRead,
  CustomFieldRead,
  DashboardStats,
  InvitationRead,
  LabelRead,
  NotificationPreferenceRead,
  NotificationRead,
  Page,
  ProjectRead,
  SavedFilterRead,
  SearchResponse,
  SprintRead,
  TaskAssigneeRead,
  TaskLinkSummary,
  TaskRead,
  TaskTreeNode,
  WebhookDeliveryRead,
  WebhookRead,
  WorkflowStatusRead,
  WorklogRead,
} from './types'
import {
  auditApi,
  checklistApi,
  customFieldsApi,
  dashboardApi,
  invitationsApi,
  labelsApi,
  linksApi,
  membersApi,
  notificationsApi,
  organizationsApi,
  preferencesApi,
  projectsApi,
  savedFiltersApi,
  searchApi,
  sprintsApi,
  tasksApi,
  webhooksApi,
  workflowsApi,
  worklogsApi,
} from './api'
import type { TaskFilters } from './api'

export const qk = {
  orgs: ['orgs'] as const,
  org: (slug: string) => ['orgs', slug] as const,
  members: (slug: string) => ['orgs', slug, 'members'] as const,
  invitationsOrg: (slug: string) => ['orgs', slug, 'invitations'] as const,
  dashboard: (slug: string) => ['orgs', slug, 'dashboard'] as const,
  labels: (slug: string) => ['orgs', slug, 'labels'] as const,
  projects: (slug: string, status?: string) =>
    ['orgs', slug, 'projects', status ?? 'all'] as const,
  project: (projectId: string) => ['projects', projectId] as const,
  tasks: (slug: string, filters: TaskFilters) =>
    ['orgs', slug, 'tasks', filters] as const,
  task: (taskId: string) => ['tasks', taskId] as const,
  taskChildren: (taskId: string) => ['tasks', taskId, 'children'] as const,
  taskTree: (projectId: string) => ['projects', projectId, 'task-tree'] as const,
  comments: (taskId: string) => ['tasks', taskId, 'comments'] as const,
  attachments: (taskId: string) => ['tasks', taskId, 'attachments'] as const,
  notifications: (unreadOnly?: boolean) => ['notifications', unreadOnly ?? false] as const,
  unreadCount: ['notifications', 'unread-count'] as const,
  invitationsMine: ['invitations', 'me'] as const,
  audit: (slug: string, action: string, offset: number, limit: number) =>
    ['orgs', slug, 'audit', { action, offset, limit }] as const,
  webhooks: (slug: string) => ['orgs', slug, 'webhooks'] as const,
  webhookDeliveries: (slug: string, webhookId: string) =>
    ['orgs', slug, 'webhooks', webhookId, 'deliveries'] as const,
  sprints: (projectId: string) => ['projects', projectId, 'sprints'] as const,
  backlog: (projectId: string, limit: number) =>
    ['projects', projectId, 'backlog', limit] as const,
  savedFilters: (slug: string) => ['orgs', slug, 'saved-filters'] as const,
  search: (slug: string, q: string) => ['orgs', slug, 'search', q] as const,
  preferences: ['auth', 'notification-preferences'] as const,
  workflow: (projectId: string) => ['projects', projectId, 'workflow'] as const,
  boards: (projectId: string) => ['projects', projectId, 'boards'] as const,
  customFields: (projectId: string) =>
    ['projects', projectId, 'custom-fields'] as const,
  taskLinks: (taskId: string) => ['tasks', taskId, 'links'] as const,
  taskChecklist: (taskId: string) => ['tasks', taskId, 'checklist'] as const,
  taskAssignees: (taskId: string) => ['tasks', taskId, 'assignees'] as const,
  taskWorklogs: (taskId: string) => ['tasks', taskId, 'worklogs'] as const,
}

const NOTIFICATION_POLL_MS = 30_000

export function useOrganizations() {
  return useQuery({
    queryKey: qk.orgs,
    queryFn: () => organizationsApi.list(),
  })
}

export function useOrgMembers(slug: string | undefined) {
  return useQuery({
    queryKey: qk.members(slug ?? ''),
    queryFn: () => membersApi.list(slug as string),
    enabled: Boolean(slug),
  })
}

export function useDashboard(slug: string) {
  return useQuery<DashboardStats>({
    queryKey: qk.dashboard(slug),
    queryFn: () => dashboardApi.get(slug),
    enabled: Boolean(slug),
  })
}

export function useProjects(slug: string, status?: string) {
  return useQuery<ProjectRead[]>({
    queryKey: qk.projects(slug, status),
    queryFn: () => projectsApi.list(slug, status || undefined),
    enabled: Boolean(slug),
  })
}

export function useProject(projectId: string | undefined) {
  return useQuery<ProjectRead>({
    queryKey: qk.project(projectId ?? ''),
    queryFn: () => projectsApi.get(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useTasks(slug: string, filters: TaskFilters) {
  return useQuery<Page<TaskRead>>({
    queryKey: qk.tasks(slug, filters),
    queryFn: () => tasksApi.list(slug, filters),
    enabled: Boolean(slug),
  })
}

export function useTaskChildren(taskId: string | null | undefined) {
  return useQuery<TaskRead[]>({
    queryKey: qk.taskChildren(taskId ?? ''),
    queryFn: () => tasksApi.children(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useTaskTree(projectId: string | undefined) {
  return useQuery<TaskTreeNode[]>({
    queryKey: qk.taskTree(projectId ?? ''),
    queryFn: () => tasksApi.tree(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useLabels(slug: string) {
  return useQuery<LabelRead[]>({
    queryKey: qk.labels(slug),
    queryFn: () => labelsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useNotifications(unreadOnly: boolean) {
  return useQuery<Page<NotificationRead>>({
    queryKey: qk.notifications(unreadOnly),
    queryFn: () => notificationsApi.list({ unread_only: unreadOnly, limit: 50 }),
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

export function useUnreadCount() {
  return useQuery<{ unread: number }>({
    queryKey: qk.unreadCount,
    queryFn: () => notificationsApi.unreadCount(),
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

export function useMyInvitations() {
  return useQuery<InvitationRead[]>({
    queryKey: qk.invitationsMine,
    queryFn: () => invitationsApi.listMine(),
  })
}

export function useOrgInvitations(slug: string) {
  return useQuery<InvitationRead[]>({
    queryKey: qk.invitationsOrg(slug),
    queryFn: () => invitationsApi.listOrg(slug),
    enabled: Boolean(slug),
  })
}

export function useAuditLogs(
  slug: string,
  action: string,
  offset: number,
  limit: number,
) {
  return useQuery({
    queryKey: qk.audit(slug, action, offset, limit),
    queryFn: () =>
      auditApi.list(slug, { action: action || undefined, offset, limit }),
    enabled: Boolean(slug),
  })
}

export function useWebhooks(slug: string) {
  return useQuery<WebhookRead[]>({
    queryKey: qk.webhooks(slug),
    queryFn: () => webhooksApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useWebhookDeliveries(slug: string, webhookId: string | undefined) {
  return useQuery<WebhookDeliveryRead[]>({
    queryKey: qk.webhookDeliveries(slug, webhookId ?? ''),
    queryFn: () => webhooksApi.deliveries(slug, webhookId as string),
    enabled: Boolean(slug && webhookId),
  })
}

export function useSprints(projectId: string | undefined) {
  return useQuery<SprintRead[]>({
    queryKey: qk.sprints(projectId ?? ''),
    queryFn: () => sprintsApi.list(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useBacklog(projectId: string | undefined, limit = 100) {
  return useQuery<Page<TaskRead>>({
    queryKey: qk.backlog(projectId ?? '', limit),
    queryFn: () => sprintsApi.backlog(projectId as string, { limit }),
    enabled: Boolean(projectId),
  })
}

export function useSavedFilters(slug: string) {
  return useQuery<SavedFilterRead[]>({
    queryKey: qk.savedFilters(slug),
    queryFn: () => savedFiltersApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useGlobalSearch(slug: string, query: string) {
  const trimmed = query.trim()
  return useQuery<SearchResponse>({
    queryKey: qk.search(slug, trimmed),
    queryFn: () => searchApi.global(slug, trimmed),
    enabled: Boolean(slug) && trimmed.length >= 2,
    staleTime: 5_000,
  })
}

export function useNotificationPreferences() {
  return useQuery<NotificationPreferenceRead>({
    queryKey: qk.preferences,
    queryFn: () => preferencesApi.get(),
  })
}

export function useWorkflow(projectId: string | undefined) {
  return useQuery<WorkflowStatusRead[]>({
    queryKey: qk.workflow(projectId ?? ''),
    queryFn: () => workflowsApi.get(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useBoards(projectId: string | undefined) {
  return useQuery<BoardRead[]>({
    queryKey: qk.boards(projectId ?? ''),
    queryFn: () => workflowsApi.listBoards(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useCustomFields(projectId: string | undefined) {
  return useQuery<CustomFieldRead[]>({
    queryKey: qk.customFields(projectId ?? ''),
    queryFn: () => customFieldsApi.list(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useTaskLinks(taskId: string | null | undefined) {
  return useQuery<TaskLinkSummary>({
    queryKey: qk.taskLinks(taskId ?? ''),
    queryFn: () => linksApi.list(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useTaskChecklist(taskId: string | null | undefined) {
  return useQuery<ChecklistItemRead[]>({
    queryKey: qk.taskChecklist(taskId ?? ''),
    queryFn: () => checklistApi.list(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useTaskAssignees(taskId: string | null | undefined) {
  return useQuery<TaskAssigneeRead[]>({
    queryKey: qk.taskAssignees(taskId ?? ''),
    queryFn: () => checklistApi.assignees(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useTaskWorklogs(taskId: string | null | undefined) {
  return useQuery<WorklogRead[]>({
    queryKey: qk.taskWorklogs(taskId ?? ''),
    queryFn: () => worklogsApi.list(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useInvalidateTasks() {
  const queryClient = useQueryClient()
  return useCallback(
    (slug: string, taskId?: string) => {
      void queryClient.invalidateQueries({ queryKey: ['orgs', slug, 'tasks'] })
      if (taskId) {
        void queryClient.invalidateQueries({ queryKey: qk.task(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.comments(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.attachments(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.taskChecklist(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.taskLinks(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.taskWorklogs(taskId) })
        void queryClient.invalidateQueries({ queryKey: qk.taskAssignees(taskId) })
      }
    },
    [queryClient],
  )
}
