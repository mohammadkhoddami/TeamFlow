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

export interface ProjectRead {
  id: string
  organization_id: string
  name: string
  description: string | null
  status: 'active' | 'archived'
  owner_id: string | null
  created_at: string
  updated_at: string | null
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
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  type: TaskType
  due_date: string | null
  parent_id: string | null
  created_by_id: string | null
  assignee_id: string | null
  completed_at: string | null
  created_at: string
  updated_at: string | null
  assignee?: UserRead | null
  creator?: UserRead | null
  parent?: TaskParentRef | null
  labels: LabelRead[]
  watcher_ids: string[]
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
