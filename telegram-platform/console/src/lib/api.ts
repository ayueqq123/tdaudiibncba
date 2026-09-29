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
  _retried?: boolean
}

// access_token 过期后走 refresh cookie 静默续期;并发请求共享同一个刷新
let refreshing: Promise<boolean> | null = null
export function tryRefreshToken(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(new URL(`${BASE}/auth/refresh`, window.location.origin).toString(), { method: 'POST' })
      .then(async (r) => {
        if (!r.ok) return false
        const j = await r.json().catch(() => null)
        const t = j?.data?.access_token
        if (!t) return false
        setToken(t)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
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
    if (!opts._retried && (await tryRefreshToken())) {
      return req<T>(path, { ...opts, _retried: true })
    }
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
export interface ApiCredential {
  api_id: number
  api_hash: string
  account_count: number
  phones: string[]
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
export interface TgAlert {
  key: string
  level: 'error' | 'warning'
  category: 'account' | 'heartbeat' | 'route' | 'delivery' | 'uncertain' | 'ai'
  title: string
  detail: string
  account_label: string
  count: number
  last_at: string | null
  link: string
  handled: boolean
  handled_at: string | null
  handled_by: string | null
}
export interface CloneTarget {
  id: number
  source_chat_id: number
  source_topic_id: number | null
  target_chat_id: number
  target_topic_id: number | null
  source_chat_ref?: string | null
  target_chat_ref?: string | null
  health?: string | null
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
  source_scope: string
  source_chat_id: number
  source_message_id: number
  revision: number
  target_chat_id: number
  target_topic_id: number | null
  attempt_count: number
  last_error_class: string | null
  rule_id: string
  rule_version: number
  account_id: string
  account_label: string | null
  idempotency_key: string
  payload_ref: string | null
  requires_approval: boolean
  next_attempt_at: string | null
  flood_wait_until: string | null
  created_at: string | null
  updated_at: string | null
  attempts?: { attempt_no: number; result_status: string | null; error_class: string | null; started_at: string | null; finished_at: string | null }[]
}
export interface DeliveryPage {
  total: number
  page: number
  size: number
  items: DeliveryJob[]
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
  updateTarget: (id: number, targetId: number, b: any) => api.put(`${TG}/clone-rules/${id}/targets/${targetId}`, b),
  checkRule: (id: number) =>
    api.post<{ target_id: number; ok: boolean; reason: string | null }[]>(`${TG}/clone-rules/${id}/check`, {}),
  retireTarget: (id: number, targetId: number) => api.del(`${TG}/clone-rules/${id}/targets/${targetId}`),
  publishRule: (id: number, expectedVersion: number) =>
    api.post(`${TG}/clone-rules/${id}/publish`, { expected_version: expectedVersion }),
  ruleVersions: (id: number) => api.get<any[]>(`${TG}/clone-rules/${id}/versions`),
  alerts: () => api.get<TgAlert[]>(`${TG}/alerts`),
  ackAlerts: (keys: string[]) => api.post<{ count: number }>(`${TG}/alerts/ack`, { keys }),
  deliveries: (params?: any) => api.get<DeliveryPage>(`${TG}/deliveries`, params),
  delivery: (id: string) => api.get<DeliveryJob>(`${TG}/deliveries/${id}`),
  retryDelivery: (id: string) => api.post(`${TG}/deliveries/${id}/retry`, {}),
  cancelDelivery: (id: string) => api.post(`${TG}/deliveries/${id}/cancel`, {}),
  approvals: (params?: any) => api.get<Approval[]>(`${TG}/approvals`, params),
  candidates: () => api.get<ReplyCandidate[]>(`${TG}/approvals/candidates`),
  approve: (id: number, b: any) => api.post(`${TG}/approvals/${id}/approve`, b),
  reject: (id: number, b: any) => api.post(`${TG}/approvals/${id}/reject`, b),
  commands: () => api.get<RuntimeCommand[]>(`${TG}/runtime/commands`),
  issueCommand: (accountId: number, b: any) => api.post(`${TG}/runtime/accounts/${accountId}/commands`, b),
  apiCredentials: () => api.get<ApiCredential[]>(`${TG}/accounts/api-credentials`),
  loginStart: (b: { tenant_id: number; project_id: number; phone: string; api_id: number; api_hash: string; device?: string; app_version?: string }) =>
    api.post<{ login_id: string; ttl: number }>(`${TG}/accounts/login/start`, b),
  loginComplete: (b: { login_id: string; code: string; password?: string }) =>
    api.post<{ account_id?: number; need_password?: boolean; username?: string }>(`${TG}/accounts/login/complete`, b),
  ensureWorkspace: (userId?: number) =>
    api.post<{ tenant_id: number; project_id: number }>(`${TG}/workspaces/ensure`, userId ? { user_id: userId } : {}),
  aiBindings: () => api.get<AiBinding[]>(`${TG}/ai/bindings`),
  createAiBinding: (b: any) => api.post<AiBinding>(`${TG}/ai/bindings`, b),
  updateAiBinding: (id: number, b: any) => api.put<AiBinding>(`${TG}/ai/bindings/${id}`, b),
  deleteAiBinding: (id: number) => api.del(`${TG}/ai/bindings/${id}`),
  aiGroups: () => api.get<AiGroup[]>(`${TG}/ai/groups`),
  createAiGroup: (b: any) => api.post<AiGroup>(`${TG}/ai/groups`, b),
  updateAiGroup: (id: number, b: any) => api.put<AiGroup>(`${TG}/ai/groups/${id}`, b),
  deleteAiGroup: (id: number) => api.del(`${TG}/ai/groups/${id}`),
  aiGroupMessages: (id: number) => api.get<AiGroupMessage[]>(`${TG}/ai/groups/${id}/messages`),
  aiGroupRuns: (id: number) => api.get<AiGroupRun[]>(`${TG}/ai/groups/${id}/runs`),
  aiGroupWarmup: (id: number) => api.post<{ started: boolean }>(`${TG}/ai/groups/${id}/warmup`, {}),
  aiMembers: (id: number) => api.get<AiMember[]>(`${TG}/ai/groups/${id}/members`),
  addAiMember: (id: number, b: any) => api.post(`${TG}/ai/groups/${id}/members`, b),
  updateAiMember: (id: number, mid: number, b: any) => api.put(`${TG}/ai/groups/${id}/members/${mid}`, b),
  deleteAiMember: (id: number, mid: number) => api.del(`${TG}/ai/groups/${id}/members/${mid}`),
  aiScripts: (id: number) => api.get<AiScript[]>(`${TG}/ai/groups/${id}/scripts`),
  createAiScript: (id: number, b: any) => api.post<AiScript>(`${TG}/ai/groups/${id}/scripts`, b),
  updateAiScript: (id: number, sid: number, b: any) => api.put<AiScript>(`${TG}/ai/groups/${id}/scripts/${sid}`, b),
  deleteAiScript: (id: number, sid: number) => api.del(`${TG}/ai/groups/${id}/scripts/${sid}`),
  startAiScript: (id: number, sid: number) => api.post(`${TG}/ai/groups/${id}/scripts/${sid}/start`, {}),
  stopAiScript: (id: number, sid: number) => api.post(`${TG}/ai/groups/${id}/scripts/${sid}/stop`, {}),
  aiPersonas: () => api.get<AiPersona[]>(`${TG}/ai/personas`),
  createAiPersona: (b: any) => api.post<AiPersona>(`${TG}/ai/personas`, b),
  deleteAiPersona: (id: number) => api.del(`${TG}/ai/personas/${id}`),
  aiPrivateReplies: () => api.get<AiPrivateReply[]>(`${TG}/ai/private-replies`),
  saveAiPrivateReply: (accountId: number, b: any) => api.put<AiPrivateReply>(`${TG}/ai/private-replies/${accountId}`, b),
  setAutoApprove: (tenant_id: number, project_id: number, enabled: boolean) =>
    api.put<{ updated: number; enabled: boolean }>(`${TG}/ai/auto-approve`, { tenant_id, project_id, enabled }),
}

export interface AiGroup {
  id: number
  tenant_id: number
  project_id: number
  name: string
  chat_id: number
  chat_ref: string | null
  topic_id: number | null
  theme: string | null
  base_url: string
  provider_model: string | null
  has_provider_key: boolean
  status: string
  reply_min: number
  reply_max: number
  account_cooldown_s: number
  account_hourly_max: number
  stale_max_messages: number
  context_max_messages: number
  bot_chain_max: number
  active_start_hour: number
  active_end_hour: number
  mention_bypass_hours: boolean
  idle_warmup_min: number
  quote_prob: number
  punct_space_prob: number
  blocked_words: string[]
  max_reply_chars: number
  auto_approve: boolean
  last_message_at: string | null
  last_warmup_at: string | null
  remark: string | null
  member_count: number
  active_member_count: number
  today_replies: number
  pending_approvals: number
}

export interface AiMember {
  id: number
  group_id: number
  account_id: number
  role_name: string | null
  persona: string | null
  talkativeness: number
  reply_delay_s: number
  provider_model: string | null
  base_url: string
  has_provider_key: boolean
  status: string
  account_label: string
  account_running: boolean
}

export interface AiGroupMessage {
  mid: number
  sid: number | null
  sender: string
  text: string
  ours?: boolean
  ts?: number
}

export interface AiGroupRun {
  id: number
  created_time: string
  status: string
  mode: string
  member_id: number | null
  role_name: string | null
  account_label: string
  trigger_text: string
  trigger_sender: string | null
  content: string | null
  candidate_status: string | null
  last_error: string | null
  model: string | null
}

export interface AiScript {
  id: number
  group_id: number
  name: string
  lines: { member_id: number; text: string }[]
  interval_s: number
  rewrite: boolean
  status: string
  cursor: number
}

export interface AiPersona {
  id: number
  tenant_id: number
  project_id: number
  name: string
  role_name: string | null
  persona: string
  talkativeness: number
}

export interface AiPrivateReply {
  id: number
  tenant_id: number
  project_id: number
  account_id: number
  enabled: boolean
  reply_text: string | null
  reply_cooldown_min: number
  forward_chat_id: number | null
}

export interface AiBinding {
  id: number
  uuid: string
  tenant_id: number
  project_id: number
  account_id: number
  engine: string
  base_url: string
  chat_id: number | null
  topic_id: number | null
  persona: string | null
  provider_model: string | null
  has_provider_key: boolean
  speak_policy: string
  reply_delay_s?: number
  random_prob?: number
  context_max_messages?: number
  auto_approve?: boolean
  status: string
  remark: string | null
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
