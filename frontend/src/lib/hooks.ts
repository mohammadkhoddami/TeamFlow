import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import type {
  ActivityRead,
  ApiTokenRead,
  AutomationExecutionRead,
  AutomationRuleRead,
  AutomationTemplateRead,
  BoardRead,
  CalendarResponse,
  ChecklistItemRead,
  CustomFieldRead,
  CustomRoleRead,
  DashboardData,
  DashboardRead,
  DashboardStats,
  FormRead,
  FormSubmissionRead,
  GoalRead,
  IntegrationEventRead,
  IntegrationRead,
  InvitationRead,
  LabelRead,
  MfaStatus,
  NotificationMuteRead,
  NotificationPreferenceRead,
  NotificationRead,
  OAuthAppRead,
  Page,
  PluginDirectoryEntry,
  PluginRead,
  ProjectMemberRead,
  ProjectRead,
  PushSubscriptionRead,
  ReleaseRead,
  RoadmapResponse,
  SavedFilterRead,
  ScimTokenRead,
  SearchResponse,
  ServiceAccountRead,
  SprintRead,
  SsoConfigRead,
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
  activityApi,
  auditApi,
  automationsApi,
  calendarApi,
  checklistApi,
  customFieldsApi,
  dashboardApi,
  dashboardsApi,
  formsApi,
  goalsApi,
  integrationsApi,
  invitationsApi,
  labelsApi,
  linksApi,
  membersApi,
  mfaApi,
  notificationsApi,
  organizationsApi,
  pluginsApi,
  preferencesApi,
  projectMembersApi,
  projectsApi,
  releasesApi,
  rolesApi,
  savedFiltersApi,
  scimApi,
  searchApi,
  sprintsApi,
  ssoApi,
  tasksApi,
  tokensApi,
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
  taskActivity: (taskId: string) => ['tasks', taskId, 'activity'] as const,
  projectActivity: (projectId: string) => ['projects', projectId, 'activity'] as const,
  releases: (projectId: string) => ['projects', projectId, 'releases'] as const,
  roadmap: (projectId: string) => ['projects', projectId, 'roadmap'] as const,
  calendar: (slug: string, params: string) => ['orgs', slug, 'calendar', params] as const,
  automations: (slug: string) => ['orgs', slug, 'automations'] as const,
  automationTemplates: (slug: string) => ['orgs', slug, 'automations', 'templates'] as const,
  automationExecutions: (slug: string) =>
    ['orgs', slug, 'automations', 'executions'] as const,
  integrations: (slug: string) => ['orgs', slug, 'integrations'] as const,
  integrationEvents: (slug: string) => ['orgs', slug, 'integration-events'] as const,
  notificationMutes: ['notifications', 'mutes'] as const,
  apiTokens: (slug: string) => ['orgs', slug, 'api-tokens'] as const,
  serviceAccounts: (slug: string) => ['orgs', slug, 'service-accounts'] as const,
  oauthApps: (slug: string) => ['orgs', slug, 'oauth-apps'] as const,
  mfaStatus: ['auth', 'mfa'] as const,
  ssoConfig: (slug: string) => ['orgs', slug, 'sso'] as const,
  scimTokens: (slug: string) => ['orgs', slug, 'scim-tokens'] as const,
  roles: (slug: string) => ['orgs', slug, 'roles'] as const,
  projectMembers: (projectId: string) =>
    ['projects', projectId, 'members'] as const,
  goals: (slug: string) => ['orgs', slug, 'goals'] as const,
  dashboards: (slug: string) => ['orgs', slug, 'dashboards'] as const,
  dashboardData: (slug: string, dashboardId: string) =>
    ['orgs', slug, 'dashboards', dashboardId, 'data'] as const,
  forms: (projectId: string) => ['projects', projectId, 'forms'] as const,
  formSubmissions: (formId: string) =>
    ['forms', formId, 'submissions'] as const,
  plugins: (slug: string) => ['orgs', slug, 'plugins'] as const,
  pluginDirectory: (slug: string) =>
    ['orgs', slug, 'plugins', 'directory'] as const,
  pushSubscriptions: ['notifications', 'push-subscriptions'] as const,
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
        void queryClient.invalidateQueries({ queryKey: qk.taskActivity(taskId) })
      }
    },
    [queryClient],
  )
}

// -------------------------------------------------------------- M3 hooks

export function useTaskActivity(taskId: string | null | undefined) {
  return useQuery<ActivityRead[]>({
    queryKey: qk.taskActivity(taskId ?? ''),
    queryFn: () => activityApi.task(taskId as string),
    enabled: Boolean(taskId),
  })
}

export function useProjectActivity(projectId: string | undefined) {
  return useQuery<ActivityRead[]>({
    queryKey: qk.projectActivity(projectId ?? ''),
    queryFn: () => activityApi.project(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useReleases(projectId: string | undefined) {
  return useQuery<ReleaseRead[]>({
    queryKey: qk.releases(projectId ?? ''),
    queryFn: () => releasesApi.list(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useRoadmap(projectId: string | undefined) {
  return useQuery<RoadmapResponse>({
    queryKey: qk.roadmap(projectId ?? ''),
    queryFn: () => releasesApi.roadmap(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useCalendar(
  slug: string,
  params: { start?: string; end?: string; project_id?: string },
) {
  const serialized = JSON.stringify(params)
  return useQuery<CalendarResponse>({
    queryKey: qk.calendar(slug, serialized),
    queryFn: () => calendarApi.get(slug, params),
    enabled: Boolean(slug),
  })
}

export function useAutomations(slug: string) {
  return useQuery<AutomationRuleRead[]>({
    queryKey: qk.automations(slug),
    queryFn: () => automationsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useAutomationTemplates(slug: string) {
  return useQuery<AutomationTemplateRead[]>({
    queryKey: qk.automationTemplates(slug),
    queryFn: () => automationsApi.templates(slug),
    enabled: Boolean(slug),
  })
}

export function useAutomationExecutions(slug: string) {
  return useQuery<AutomationExecutionRead[]>({
    queryKey: qk.automationExecutions(slug),
    queryFn: () => automationsApi.executions(slug, { limit: 100 }),
    enabled: Boolean(slug),
  })
}

export function useIntegrations(slug: string) {
  return useQuery<IntegrationRead[]>({
    queryKey: qk.integrations(slug),
    queryFn: () => integrationsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useIntegrationEvents(slug: string) {
  return useQuery<IntegrationEventRead[]>({
    queryKey: qk.integrationEvents(slug),
    queryFn: () => integrationsApi.events(slug, { limit: 100 }),
    enabled: Boolean(slug),
  })
}

export function useNotificationMutes() {
  return useQuery<NotificationMuteRead[]>({
    queryKey: qk.notificationMutes,
    queryFn: () => notificationsApi.listMutes(),
  })
}

export function useApiTokens(slug: string) {
  return useQuery<ApiTokenRead[]>({
    queryKey: qk.apiTokens(slug),
    queryFn: () => tokensApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useServiceAccounts(slug: string, enabled = true) {
  return useQuery<ServiceAccountRead[]>({
    queryKey: qk.serviceAccounts(slug),
    queryFn: () => tokensApi.listServiceAccounts(slug),
    enabled: Boolean(slug) && enabled,
  })
}

export function useOAuthApps(slug: string, enabled = true) {
  return useQuery<OAuthAppRead[]>({
    queryKey: qk.oauthApps(slug),
    queryFn: () => tokensApi.listOAuthApps(slug),
    enabled: Boolean(slug) && enabled,
  })
}

// -------------------------------------------------------------- M4 hooks

export function useMfaStatus() {
  return useQuery<MfaStatus>({
    queryKey: qk.mfaStatus,
    queryFn: () => mfaApi.status(),
  })
}

export function useSsoConfig(slug: string, enabled = true) {
  return useQuery<SsoConfigRead>({
    queryKey: qk.ssoConfig(slug),
    queryFn: () => ssoApi.getConfig(slug),
    enabled: Boolean(slug) && enabled,
    retry: false,
  })
}

export function useScimTokens(slug: string, enabled = true) {
  return useQuery<ScimTokenRead[]>({
    queryKey: qk.scimTokens(slug),
    queryFn: () => scimApi.listTokens(slug),
    enabled: Boolean(slug) && enabled,
  })
}

export function useRoles(slug: string, enabled = true) {
  return useQuery<CustomRoleRead[]>({
    queryKey: qk.roles(slug),
    queryFn: () => rolesApi.list(slug),
    enabled: Boolean(slug) && enabled,
  })
}

export function useProjectMembers(projectId: string | undefined, enabled = true) {
  return useQuery<ProjectMemberRead[]>({
    queryKey: qk.projectMembers(projectId ?? ''),
    queryFn: () => projectMembersApi.list(projectId as string),
    enabled: Boolean(projectId) && enabled,
  })
}

export function useGoals(slug: string) {
  return useQuery<GoalRead[]>({
    queryKey: qk.goals(slug),
    queryFn: () => goalsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useDashboards(slug: string) {
  return useQuery<DashboardRead[]>({
    queryKey: qk.dashboards(slug),
    queryFn: () => dashboardsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useDashboardData(slug: string, dashboardId: string | null) {
  return useQuery<DashboardData>({
    queryKey: qk.dashboardData(slug, dashboardId ?? ''),
    queryFn: () => dashboardsApi.data(slug, dashboardId as string),
    enabled: Boolean(slug && dashboardId),
  })
}

export function useForms(projectId: string | undefined) {
  return useQuery<FormRead[]>({
    queryKey: qk.forms(projectId ?? ''),
    queryFn: () => formsApi.list(projectId as string),
    enabled: Boolean(projectId),
  })
}

export function useFormSubmissions(
  projectId: string | undefined,
  formId: string | null,
) {
  return useQuery<FormSubmissionRead[]>({
    queryKey: qk.formSubmissions(formId ?? ''),
    queryFn: () => formsApi.submissions(projectId as string, formId as string),
    enabled: Boolean(projectId && formId),
  })
}

export function usePlugins(slug: string) {
  return useQuery<PluginRead[]>({
    queryKey: qk.plugins(slug),
    queryFn: () => pluginsApi.list(slug),
    enabled: Boolean(slug),
  })
}

export function useDirectory(slug: string) {
  return useQuery<PluginDirectoryEntry[]>({
    queryKey: qk.pluginDirectory(slug),
    queryFn: () => pluginsApi.directory(slug),
    enabled: Boolean(slug),
  })
}

export function usePushSubscriptions() {
  return useQuery<PushSubscriptionRead[]>({
    queryKey: qk.pushSubscriptions,
    queryFn: () => notificationsApi.pushSubscriptions(),
  })
}
