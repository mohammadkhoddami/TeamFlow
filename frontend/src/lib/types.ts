export type MembershipRole = 'owner' | 'admin' | 'manager' | 'member'

export type TaskStatus = 'todo' | 'in_progress' | 'in_review' | 'done'

export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent'

export type TaskType = 'epic' | 'story' | 'task'

export interface UserRead {
  id: string
  email: string
  full_name: string
  is_active: boolean
  created_at: string
}

export interface UserBrief {
  id: string
  email: string
  full_name: string
}

export interface OrganizationRead {
  id: string
  name: string
  slug: string
  is_active: boolean
  created_at: string
  my_role?: string | null
}

export interface OrganizationMemberRead {
  organization: OrganizationRead
  role: MembershipRole
}

export interface MembershipRead {
  id: string
  role: MembershipRole
  user_id: string
  organization_id: string
  created_at: string
  user?: UserBrief | null
}

export interface InvitationRead {
  id: string
  email: string
  role: MembershipRole
  status: string
  organization_id: string
  organization_name?: string | null
  invited_by_id?: string | null
  created_at: string
}

export type EstimationUnit = 'none' | 'points' | 'hours'

export interface ProjectRead {
  id: string
  organization_id: string
  name: string
  description: string | null
  status: 'active' | 'archived'
  key: string | null
  estimation_unit: EstimationUnit
  wip_enforced: boolean
  owner_id: string | null
  created_at: string
  updated_at: string | null
}

export type TaskCategory = 'todo' | 'in_progress' | 'in_review' | 'done'

export interface WorkflowStatusRead {
  id: string | null
  key: string
  name: string
  category: TaskCategory
  wip_limit: number | null
  transitions: string[]
  position: number
}

export interface WorkflowStatusInput {
  key: string
  name: string
  category: TaskCategory
  wip_limit?: number | null
  transitions: string[]
}

export type SwimlaneBy = 'none' | 'assignee' | 'priority' | 'label'

export interface BoardRead {
  id: string
  organization_id: string
  project_id: string
  name: string
  is_default: boolean
  swimlane_by: SwimlaneBy
  filter_query: string | null
  columns: string[] | null
}

export type CustomFieldType =
  | 'text'
  | 'number'
  | 'date'
  | 'select'
  | 'multi_select'
  | 'user'
  | 'checkbox'

export interface CustomFieldRead {
  id: string
  organization_id: string
  project_id: string
  name: string
  key: string
  field_type: CustomFieldType
  options: string[]
  is_required: boolean
  position: number
  created_at: string
}

export interface CustomFieldValueRead {
  field_id: string
  key: string
  name: string
  field_type: CustomFieldType
  value: unknown
}

export interface LinkedTaskRef {
  id: string
  key: string | null
  title: string
  status: string
  status_category: TaskCategory
  project_id: string
}

export interface TaskLinkRead {
  id: string
  link_type: string
  direction: 'out' | 'in'
  task: LinkedTaskRef
  created_at: string
}

export interface TaskLinkSummary {
  blocks: TaskLinkRead[]
  blocked_by: TaskLinkRead[]
  relates_to: TaskLinkRead[]
  duplicates: TaskLinkRead[]
  clones: TaskLinkRead[]
}

export interface BurndownPoint {
  day: string
  remaining_points: number
  remaining_tasks: number
  ideal_points: number | null
}

export interface BurndownReport {
  sprint_id: string
  sprint_name: string
  start_date: string | null
  end_date: string | null
  total_points: number
  total_tasks: number
  points: BurndownPoint[]
}

export interface VelocityPoint {
  sprint_id: string
  sprint_name: string
  start_date: string | null
  end_date: string | null
  committed_points: number
  completed_points: number
  committed_tasks: number
  completed_tasks: number
}

export interface VelocityReport {
  project_id: string
  average_completed_points: number
  sprints: VelocityPoint[]
}

export interface CfdPoint {
  day: string
  todo: number
  in_progress: number
  in_review: number
  done: number
}

export interface CfdReport {
  project_id: string
  days: number
  points: CfdPoint[]
}

export interface CycleTimeItem {
  task_id: string
  key: string | null
  title: string
  lead_time_days: number
  cycle_time_days: number | null
  completed_at: string | null
}

export interface CycleTimeReport {
  project_id: string
  days: number
  count: number
  avg_lead_time_days: number | null
  p50_lead_time_days: number | null
  p85_lead_time_days: number | null
  avg_cycle_time_days: number | null
  p50_cycle_time_days: number | null
  p85_cycle_time_days: number | null
  items: CycleTimeItem[]
}

export interface SprintMemberBreakdown {
  user_id: string | null
  name: string
  assigned_tasks: number
  completed_tasks: number
  completed_points: number
}

export interface SprintReport {
  sprint_id: string
  sprint_name: string
  state: string
  start_date: string | null
  end_date: string | null
  committed_tasks: number
  committed_points: number
  completed_tasks: number
  completed_points: number
  added_during_sprint: number
  carried_over: number
  scope_change_pct: number
  members: SprintMemberBreakdown[]
}

export interface CapacityMemberRead {
  user_id: string
  name: string
  capacity: number | null
  note: string | null
  assigned_points: number
  assigned_tasks: number
  completed_points: number
  overloaded: boolean
}

export interface WorklogRead {
  id: string
  task_id: string
  user_id: string | null
  user_name: string | null
  minutes: number
  started_at: string
  description: string | null
  created_at: string
}

export interface TimesheetRow {
  day: string
  user_id: string | null
  user_name: string
  task_id: string
  task_key: string | null
  task_title: string
  minutes: number
}

export interface TimesheetReport {
  date_from: string
  date_to: string
  total_minutes: number
  rows: TimesheetRow[]
  totals_by_user: { user_id: string | null; user_name: string; minutes: number }[]
}

export interface ProjectTemplateRead {
  id: string
  name: string
  description: string | null
  is_builtin: boolean
  project_id: string | null
}

export interface TaskTemplateRead {
  id: string
  organization_id: string
  project_id: string | null
  name: string
  title: string
  description: string | null
  priority: TaskPriority
  type: TaskType
  estimate: number | null
  label_ids: string[]
  checklist: string[]
}

export interface ChecklistItemRead {
  id: string
  task_id: string
  text: string
  is_done: boolean
  position: number
}

export interface TaskAssigneeRead {
  user_id: string
  name: string
  email: string
  role: 'assignee' | 'approver'
}

export interface ImportSummary {
  format: string
  dry_run: boolean
  rows: number
  created_tasks: number
  created_labels: number
  skipped: number
  issues: { row: number; message: string }[]
}

export type SprintState = 'planned' | 'active' | 'completed'

export interface SprintRead {
  id: string
  organization_id: string
  project_id: string
  name: string
  goal: string | null
  state: SprintState
  start_date: string | null
  end_date: string | null
  completed_at: string | null
  created_at: string
  updated_at: string | null
  task_count: number
  done_task_count: number
  total_estimate: number | null
  done_estimate: number | null
  carried_over_count: number
}

export interface SavedFilterRead {
  id: string
  organization_id: string
  project_id: string | null
  owner_id: string
  name: string
  query: string
  is_shared: boolean
  created_at: string
  updated_at: string | null
}

export interface TaskSearchHit {
  id: string
  key: string | null
  title: string
  status: TaskStatus
  priority: TaskPriority
  type: TaskType
  project_id: string
  project_name: string | null
  snippet: string | null
}

export interface CommentSearchHit {
  id: string
  task_id: string
  task_title: string | null
  task_key: string | null
  project_id: string | null
  body: string
  snippet: string | null
  created_at: string
}

export interface ProjectSearchHit {
  id: string
  name: string
  key: string | null
  status: string
  snippet: string | null
}

export interface SearchResponse {
  query: string
  tasks: TaskSearchHit[]
  comments: CommentSearchHit[]
  projects: ProjectSearchHit[]
}

export interface NotificationPreferenceRead {
  email_enabled: boolean
  assigned: boolean
  mentioned: boolean
  comments: boolean
  due: boolean
  digest: 'immediate' | 'daily' | 'weekly' | 'off'
  unsubscribe_url: string | null
}

export type BulkTaskAction =
  | 'update'
  | 'move'
  | 'clone'
  | 'delete'
  | 'archive'
  | 'restore'
  | 'move_project'

export interface BulkTaskResult {
  requested: number
  updated: number
  skipped: number
  created_ids: string[]
  failures: { task_id: string; reason: string }[]
}

export interface LabelRead {
  id: string
  name: string
  color: string | null
  organization_id: string
  created_at: string
}

export interface TaskParentRef {
  id: string
  title: string
  type: TaskType
  status: TaskStatus
  priority: TaskPriority
}

export interface TaskRead {
  id: string
  organization_id: string
  project_id: string
  key: string | null
  number: number | null
  title: string
  description: string | null
  status: string
  status_category: TaskCategory
  priority: TaskPriority
  type: TaskType
  due_date: string | null
  parent_id: string | null
  created_by_id: string | null
  assignee_id: string | null
  completed_at: string | null
  created_at: string
  updated_at: string | null
  estimate: number | null
  remaining_estimate: number | null
  actual_estimate: number | null
  backlog_rank: number | null
  sprint_id: string | null
  sprint_name: string | null
  archived_at: string | null
  recurrence_rule: string | null
  recurrence_source_id: string | null
  assignee?: UserRead | null
  creator?: UserRead | null
  parent?: TaskParentRef | null
  labels: LabelRead[]
  watcher_ids: string[]
  custom_fields: CustomFieldValueRead[]
  assignees: TaskAssigneeRead[]
  checklist_total: number
  checklist_done: number
  logged_minutes: number
  is_blocked: boolean
  blocks_count: number
  blocked_by_count: number
  child_count: number
  done_child_count: number
}

export interface TaskTreeNode extends TaskRead {
  children: TaskTreeNode[]
}

export interface CommentRead {
  id: string
  task_id: string
  organization_id: string
  body: string
  author?: UserRead | null
  created_at: string
  updated_at: string | null
}

export interface AttachmentRead {
  id: string
  task_id: string
  filename: string
  content_type: string
  size: number
  status: string
  created_at: string
}

export interface UploadGrant {
  attachment: AttachmentRead
  upload_url: string
  expires_in: number
}

export interface DownloadGrant {
  download_url: string
  expires_in: number
}

export interface NotificationRead {
  id: string
  user_id: string
  organization_id: string | null
  type: string
  title: string
  body: string | null
  data: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

export interface AuditLogRead {
  id: string
  actor_id: string | null
  organization_id: string | null
  action: string
  target_type: string | null
  target_id: string | null
  ip: string | null
  meta: Record<string, unknown> | null
  created_at: string
}

export interface TasksPerMember {
  user_id: string
  full_name: string
  open_tasks: number
}

export interface DashboardStats {
  projects: number
  active_projects: number
  total_tasks: number
  completed_tasks: number
  overdue_tasks: number
  unassigned_tasks: number
  tasks_by_status: Record<TaskStatus, number>
  tasks_per_member: TasksPerMember[]
  active_members: number
}

export interface WebhookRead {
  id: string
  url: string
  events: string[]
  is_active: boolean
  description: string | null
  created_at: string
}

export interface WebhookCreated extends WebhookRead {
  secret: string
}

export interface WebhookDeliveryRead {
  id: string
  webhook_id: string
  event: string
  status: string
  attempts: number
  response_status: number | null
  last_error: string | null
  delivered_at: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export const TASK_STATUSES: readonly TaskStatus[] = [
  'todo',
  'in_progress',
  'in_review',
  'done',
]

export const TASK_TYPES: readonly TaskType[] = ['epic', 'story', 'task']

export const PRIORITIES: readonly TaskPriority[] = ['low', 'medium', 'high', 'urgent']

export const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  in_review: 'In review',
  done: 'Done',
}

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
}

export const TYPE_LABELS: Record<TaskType, string> = {
  epic: 'Epic',
  story: 'Story',
  task: 'Task',
}

export const STATUS_BADGE: Record<TaskStatus, string> = {
  todo: 'bg-slate-100 text-slate-700',
  in_progress: 'bg-sky-100 text-sky-700',
  in_review: 'bg-amber-100 text-amber-700',
  done: 'bg-emerald-100 text-emerald-700',
}

// Category badges keep custom workflow statuses visually comparable.
export const CATEGORY_BADGE: Record<TaskCategory, string> = {
  todo: 'bg-slate-100 text-slate-700',
  in_progress: 'bg-sky-100 text-sky-700',
  in_review: 'bg-amber-100 text-amber-700',
  done: 'bg-emerald-100 text-emerald-700',
}

export function statusName(
  statuses: { key: string; name: string }[] | undefined,
  key: string,
): string {
  return statuses?.find((entry) => entry.key === key)?.name ?? key
}

export function statusCategory(
  statuses: { key: string; category: TaskCategory }[] | undefined,
  key: string,
): TaskCategory {
  return statuses?.find((entry) => entry.key === key)?.category ?? 'todo'
}

export const PRIORITY_BADGE: Record<TaskPriority, string> = {
  low: 'bg-slate-100 text-slate-600',
  medium: 'bg-sky-100 text-sky-700',
  high: 'bg-amber-100 text-amber-700',
  urgent: 'bg-red-100 text-red-700',
}

export const TYPE_BADGE: Record<TaskType, string> = {
  epic: 'bg-violet-100 text-violet-700',
  story: 'bg-sky-100 text-sky-700',
  task: 'bg-slate-100 text-slate-600',
}

// Step-wise transitions enforced by the API; the current status is prepended
// by consumers so the select always shows a valid option.
export const STATUS_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  todo: ['in_progress'],
  in_progress: ['todo', 'in_review'],
  in_review: ['in_progress', 'done'],
  done: ['in_review'],
}

// Depth of each work-item type; parents must sit at a strictly lower level.
export const TYPE_LEVEL: Record<TaskType, number> = {
  epic: 0,
  story: 1,
  task: 2,
}

export const ROLE_LABELS: Record<MembershipRole, string> = {
  owner: 'Owner',
  admin: 'Admin',
  manager: 'Manager',
  member: 'Member',
}

export const ROLE_RANK: Record<MembershipRole, number> = {
  member: 1,
  manager: 2,
  admin: 3,
  owner: 4,
}

export const WEBHOOK_EVENTS: readonly string[] = [
  'task.created',
  'task.updated',
  'task.completed',
  'comment.created',
  'member.joined',
]

export function taskTypeLevel(type: string | null | undefined): number {
  return TYPE_LEVEL[type as TaskType] ?? TYPE_LEVEL.task
}

// Types allowed as a parent for a given child type (flexible levels:
// a task may nest directly under an epic).
export function allowedParentTypes(childType: TaskType): TaskType[] {
  const childLevel = taskTypeLevel(childType)
  return TASK_TYPES.filter((candidate) => taskTypeLevel(candidate) < childLevel)
}

export function isTaskType(value: string): value is TaskType {
  return (TASK_TYPES as readonly string[]).includes(value)
}

export function roleRank(role: string | null | undefined): number {
  return ROLE_RANK[role as MembershipRole] ?? 0
}

export function isAdmin(role: string | null | undefined): boolean {
  return role === 'admin' || role === 'owner'
}

export function isOwner(role: string | null | undefined): boolean {
  return role === 'owner'
}

export function canManage(role: string | null | undefined): boolean {
  return roleRank(role) >= ROLE_RANK.manager
}
