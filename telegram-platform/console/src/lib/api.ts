// FBA 控制面 API 层:统一走相对路径 /tg/api/v1(宿主 nginx 剥 /tg/ 前缀反代)
const BASE = '/tg/api/v1'
const TOKEN_KEY = 'TGP_TOKEN'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(`HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

interface ReqOpts {
  method?: string
  body?: any
  form?: FormData
  params?: Record<string, any>
}

async function req<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  for (const [k, v] of Object.entries(opts.params || {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  }
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) {
    body = opts.form
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await fetch(url.toString(), { method: opts.method || 'GET', headers, body })
  if (res.status === 401) {
    clearToken()
    window.location.hash = '#/login'
    throw new ApiError(401, '登录过期')
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      detail = j.msg || j.detail || detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail))
  }
  const json = await res.json()
  return (json && typeof json === 'object' && 'data' in json ? json.data : json) as T
}

export const api = {
  get: <T>(path: string, params?: Record<string, any>) => req<T>(path, { params }),
  post: <T>(path: string, body?: any) => req<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: any) => req<T>(path, { method: 'PUT', body }),
  del: <T>(path: string) => req<T>(path, { method: 'DELETE' }),
  postForm: <T>(path: string, form: FormData) => req<T>(path, { method: 'POST', form }),
}

// ---------- auth ----------
export interface CaptchaInfo {
  is_enabled: boolean
  expire_seconds: number
  uuid: string
  image: string
}
export const fetchCaptcha = () => api.get<CaptchaInfo>('/auth/captcha')
export const fetchLogin = (username: string, password: string, uuid: string, captcha: string) =>
  api.post<{ access_token: string }>('/auth/login', { username, password, uuid, captcha })
export const fetchMe = () =>
  api.get<{ id: number; username: string; nickname: string; roles: string[]; is_superuser: boolean }>('/sys/users/me')
export const fetchLogout = () => api.post<null>('/auth/logout')

// ---------- tg ----------
export interface Tenant {
  id: number
  name: string
  status: number
  remark: string | null
  created_time: string
}
export interface Project {
  id: number
  tenant_id: number
  name: string
  status: number
  remark: string | null
  created_time: string
}
export interface TgAccount {
  id: number
  uuid: string
  tenant_id: number
  project_id: number
  telegram_user_id: number | null
  phone: string | null
  username?: string | null
  desired_status: string
  observed_status: string
  remark: string | null
}
export interface ImportBatch {
  id: number
  tenant_id: number
  project_id: number
  status: string
  total: number
  created_time: string
  results?: { phone?: string; telegram_user_id?: number; grade: string; reason?: string }[]
}
export interface CloneTarget {
  id: number
  source_chat_id: number
  source_topic_id: number | null
  target_chat_id: number
  target_topic_id: number | null
  status: string
  filters?: Record<string, any> | null
  remark: string | null
}
export interface CloneRule {
  id: number
  tenant_id: number
  project_id: number
  account_id: number
  name: string
  mode: 'copy' | 'forward'
  sync_edit?: boolean
  sync_delete?: boolean
  enabled: boolean
  current_version: number
  remark: string | null
  targets?: CloneTarget[]
}
export interface DeliveryJob {
  id: string
  kind: string
  mode: string
  status: string
  source_chat_id: number
  source_message_id: number
  target_chat_id: number
  attempt_count: number
  last_error_class: string | null
  rule_id: string
  rule_version: number
  attempts?: { attempt_no: number; result_status: string | null; error_class: string | null; started_at: string | null }[]
}
export interface ReplyCandidate {
  id: number
  content: string
  content_hash: string
  version: number
  status: string
}
export interface Approval {
  id: number
  candidate_id: number
  status: string
  reason: string | null
  expires_at: string
}
export interface RuntimeCommand {
  id: number
  type: string
  account_id: number
  status: string
  result: string | null
  acked_at: string | null
  created_time: string
}

const TG = '/tg'
export const tgApi = {
  tenants: () => api.get<Tenant[]>(`${TG}/tenants`),
  createTenant: (b: any) => api.post<Tenant>(`${TG}/tenants`, b),
  deleteTenant: (id: number) => api.del(`${TG}/tenants/${id}`),
  projects: () => api.get<Project[]>(`${TG}/projects`),
  createProject: (b: any) => api.post<Project>(`${TG}/projects`, b),
  deleteProject: (id: number) => api.del(`${TG}/projects/${id}`),
  accounts: (params?: any) => api.get<TgAccount[]>(`${TG}/accounts`, params),
  updateAccount: (id: number, b: any) => api.put(`${TG}/accounts/${id}`, b),
  importAccounts: (tenantId: number, projectId: number, file: File) => {
    const f = new FormData()
    f.append('tenant_id', String(tenantId))
    f.append('project_id', String(projectId))
    f.append('file', file)
    return api.postForm<ImportBatch>(`${TG}/accounts/import`, f)
  },
  imports: () => api.get<ImportBatch[]>(`${TG}/imports`),
  importDetail: (id: number) => api.get<ImportBatch>(`${TG}/imports/${id}`),
  rules: () => api.get<CloneRule[]>(`${TG}/clone-rules`),
  rule: (id: number) => api.get<CloneRule>(`${TG}/clone-rules/${id}`),
  createRule: (b: any) => api.post<CloneRule>(`${TG}/clone-rules`, b),
  updateRule: (id: number, b: any) => api.put(`${TG}/clone-rules/${id}`, b),
  deleteRule: (id: number) => api.del(`${TG}/clone-rules/${id}`),
  addTarget: (id: number, b: any) => api.post(`${TG}/clone-rules/${id}/targets`, b),
  retireTarget: (id: number, targetId: number) => api.del(`${TG}/clone-rules/${id}/targets/${targetId}`),
  publishRule: (id: number, expectedVersion: number) =>
    api.post(`${TG}/clone-rules/${id}/publish`, { expected_version: expectedVersion }),
  ruleVersions: (id: number) => api.get<any[]>(`${TG}/clone-rules/${id}/versions`),
  deliveries: (params?: any) => api.get<DeliveryJob[]>(`${TG}/deliveries`, params),
  delivery: (id: string) => api.get<DeliveryJob>(`${TG}/deliveries/${id}`),
  retryDelivery: (id: string) => api.post(`${TG}/deliveries/${id}/retry`, {}),
  cancelDelivery: (id: string) => api.post(`${TG}/deliveries/${id}/cancel`, {}),
  approvals: (params?: any) => api.get<Approval[]>(`${TG}/approvals`, params),
  candidates: () => api.get<ReplyCandidate[]>(`${TG}/approvals/candidates`),
  approve: (id: number, b: any) => api.post(`${TG}/approvals/${id}/approve`, b),
  reject: (id: number, b: any) => api.post(`${TG}/approvals/${id}/reject`, b),
  commands: () => api.get<RuntimeCommand[]>(`${TG}/runtime/commands`),
  issueCommand: (accountId: number, b: any) => api.post(`${TG}/runtime/accounts/${accountId}/commands`, b),
  ensureWorkspace: (userId?: number) =>
    api.post<{ tenant_id: number; project_id: number }>(`${TG}/workspaces/ensure`, userId ? { user_id: userId } : {}),
}

// ---------- sys 登录账号 ----------
export interface SysUser {
  id: number
  username: string
  nickname: string | null
  status: number
  dept_id: number | null
  last_password?: string | null
  created_time?: string
}
export const sysApi = {
  users: () => api.get<{ items: SysUser[]; total: number }>('/sys/users', { size: 200 }),
  createUser: (b: { username: string; password: string; nickname?: string; dept_id: number; roles: number[] }) =>
    api.post('/sys/users', b),
  resetPassword: (id: number, password: string) => api.put(`/sys/users/${id}/password`, { password }),
  toggleStatus: (id: number) => api.put(`/sys/users/${id}/permissions?type=status`),
  updateMyPassword: (old_password: string, new_password: string) =>
    api.put('/sys/users/me/password', { old_password, new_password, confirm_password: new_password }),
  deleteUser: (id: number) => api.del(`/sys/users/${id}`),
}

// ---------- 项目成员绑定 ----------
export interface Membership {
  id: number
  tenant_id: number
  project_id: number
  user_id: number
  role: 'owner' | 'admin' | 'member'
  status: number
}
export const membershipApi = {
  list: (userId: number) => api.get<Membership[]>(`${TG}/memberships`, { user_id: userId }),
  add: (b: { tenant_id: number; project_id: number; user_id: number }) =>
    api.post(`${TG}/memberships`, { ...b, role: 'member', status: 1 }),
  remove: (id: number) => api.del(`${TG}/memberships/${id}`),
}
