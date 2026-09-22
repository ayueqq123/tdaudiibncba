import { requestClient } from '#/api/request';

/* ============ 租户 ============ */

export interface TgTenant {
  id: number;
  uuid: string;
  name: string;
  status: number;
  remark?: string;
  created_time: string;
  updated_time?: string;
}

export interface TgTenantParams {
  name: string;
  status: number;
  remark?: string;
}

export function getTgTenantsApi(params?: { name?: string; status?: number }) {
  return requestClient.get<TgTenant[]>('/api/v1/tg/tenants', { params });
}

export function getTgTenantApi(pk: number) {
  return requestClient.get<TgTenant>(`/api/v1/tg/tenants/${pk}`);
}

export function createTgTenantApi(data: TgTenantParams) {
  return requestClient.post('/api/v1/tg/tenants', data);
}

export function updateTgTenantApi(pk: number, data: TgTenantParams) {
  return requestClient.put(`/api/v1/tg/tenants/${pk}`, data);
}

export function deleteTgTenantApi(pk: number) {
  return requestClient.delete(`/api/v1/tg/tenants/${pk}`);
}

/* ============ 项目 ============ */

export interface TgProject {
  id: number;
  uuid: string;
  tenant_id: number;
  name: string;
  status: number;
  remark?: string;
  created_time: string;
  updated_time?: string;
}

export interface TgProjectParams {
  tenant_id: number;
  name: string;
  status: number;
  remark?: string;
}

export function getTgProjectsApi(params?: {
  name?: string;
  status?: number;
  tenant_id?: number;
}) {
  return requestClient.get<TgProject[]>('/api/v1/tg/projects', { params });
}

export function createTgProjectApi(data: TgProjectParams) {
  return requestClient.post('/api/v1/tg/projects', data);
}

export function updateTgProjectApi(pk: number, data: TgProjectParams) {
  return requestClient.put(`/api/v1/tg/projects/${pk}`, data);
}

export function deleteTgProjectApi(pk: number) {
  return requestClient.delete(`/api/v1/tg/projects/${pk}`);
}

/* ============ 成员 ============ */

export interface TgMembership {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  user_id: number;
  role: string;
  status: number;
  created_time: string;
}

export interface TgMembershipParams {
  tenant_id: number;
  project_id: number;
  user_id: number;
  role?: 'admin' | 'member' | 'owner';
  status?: number;
}

export function getTgMembershipsApi(params?: {
  project_id?: number;
  tenant_id?: number;
  user_id?: number;
}) {
  return requestClient.get<TgMembership[]>('/api/v1/tg/memberships', {
    params,
  });
}

export function createTgMembershipApi(data: TgMembershipParams) {
  return requestClient.post('/api/v1/tg/memberships', data);
}

export function updateTgMembershipApi(
  pk: number,
  data: { role: string; status: number },
) {
  return requestClient.put(`/api/v1/tg/memberships/${pk}`, data);
}

export function deleteTgMembershipApi(pk: number) {
  return requestClient.delete(`/api/v1/tg/memberships/${pk}`);
}

/* ============ Telegram 账号 ============ */

export interface TgAccount {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  import_batch_id?: number;
  phone?: string;
  telegram_user_id?: number;
  username?: string;
  desired_status: string;
  observed_status: string;
  last_seen_at?: string;
  last_error?: string;
  remark?: string;
  created_time: string;
  updated_time?: string;
}

export function getTgAccountsApi(params?: {
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgAccount[]>('/api/v1/tg/accounts', { params });
}

export function getTgAccountApi(pk: number) {
  return requestClient.get<TgAccount>(`/api/v1/tg/accounts/${pk}`);
}

export function updateTgAccountApi(
  pk: number,
  data: {
    desired_status: 'running' | 'stopped';
    phone?: string;
    remark?: string;
  },
) {
  return requestClient.put(`/api/v1/tg/accounts/${pk}`, data);
}

export function deleteTgAccountApi(pk: number) {
  return requestClient.delete(`/api/v1/tg/accounts/${pk}`);
}

export function importTgAccountsApi(data: {
  file: File;
  project_id: number;
  tenant_id: number;
}) {
  return requestClient.upload<TgImportBatch>(
    '/api/v1/tg/accounts/import',
    data,
  );
}

/* ============ 导入批次 ============ */

export interface TgImportBatch {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  operator_id: number;
  filename: string;
  file_sha256: string;
  status: string;
  total: number;
  verified: number;
  failed: number;
  detail?: Record<string, any>[];
  finished_at?: string;
  created_time: string;
}

export function getTgImportsApi(params?: {
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgImportBatch[]>('/api/v1/tg/imports', { params });
}

export function getTgImportApi(batchId: number) {
  return requestClient.get<TgImportBatch>(`/api/v1/tg/imports/${batchId}`);
}

/* ============ Clone 规则 ============ */

export interface TgCloneTarget {
  id: number;
  route_id: string;
  rule_id: number;
  source_chat_id: number;
  source_topic_id?: number;
  target_chat_id: number;
  target_topic_id?: number;
  filters?: Record<string, any>;
  status: string;
  remark?: string;
  created_time: string;
}

export interface TgCloneRule {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  account_id: number;
  name: string;
  mode: 'copy' | 'forward';
  enabled: boolean;
  remark?: string;
  current_version: number;
  status: string;
  targets?: TgCloneTarget[];
  created_time: string;
  updated_time?: string;
}

export interface TgCloneRuleVersion {
  id: number;
  rule_id: number;
  version: number;
  snapshot: Record<string, any>;
  published_by: number;
  published_at: string;
}

export function getTgCloneRulesApi(params?: {
  account_id?: number;
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgCloneRule[]>('/api/v1/tg/clone-rules', { params });
}

export function getTgCloneRuleApi(pk: number) {
  return requestClient.get<TgCloneRule>(`/api/v1/tg/clone-rules/${pk}`);
}

export function createTgCloneRuleApi(data: {
  account_id: number;
  enabled?: boolean;
  mode: 'copy' | 'forward';
  name: string;
  project_id: number;
  remark?: string;
  tenant_id: number;
}) {
  return requestClient.post('/api/v1/tg/clone-rules', data);
}

export function updateTgCloneRuleApi(
  pk: number,
  data: { enabled: boolean; mode: string; name: string; remark?: string },
) {
  return requestClient.put(`/api/v1/tg/clone-rules/${pk}`, data);
}

export function deleteTgCloneRuleApi(pk: number) {
  return requestClient.delete(`/api/v1/tg/clone-rules/${pk}`);
}

export function addTgCloneTargetApi(
  pk: number,
  data: {
    filters?: Record<string, any>;
    remark?: string;
    source_chat_id: number;
    source_topic_id?: number;
    target_chat_id: number;
    target_topic_id?: number;
  },
) {
  return requestClient.post(`/api/v1/tg/clone-rules/${pk}/targets`, data);
}

export function retireTgCloneTargetApi(pk: number, targetId: number) {
  return requestClient.delete(
    `/api/v1/tg/clone-rules/${pk}/targets/${targetId}`,
  );
}

export function dryRunTgCloneRuleApi(pk: number) {
  return requestClient.post(`/api/v1/tg/clone-rules/${pk}/dry-run`);
}

export function publishTgCloneRuleApi(pk: number, expectedVersion: number) {
  return requestClient.post(`/api/v1/tg/clone-rules/${pk}/publish`, {
    expected_version: expectedVersion,
  });
}

export function getTgCloneRuleVersionsApi(pk: number) {
  return requestClient.get<TgCloneRuleVersion[]>(
    `/api/v1/tg/clone-rules/${pk}/versions`,
  );
}

/* ============ 投递任务 ============ */

export interface TgDeliveryJob {
  id: string;
  tenant_id: string;
  project_id: string;
  idempotency_key: string;
  kind: string;
  route_id: string;
  rule_id: string;
  rule_version: number;
  account_id: string;
  source_scope: string;
  source_chat_id: number;
  source_message_id: number;
  revision: number;
  target_chat_id: number;
  target_topic_id?: number;
  mode: string;
  requires_approval: boolean;
  status: string;
  attempt_count: number;
  next_attempt_at?: string;
  flood_wait_until?: string;
  last_error_class?: string;
  created_at?: string;
  updated_at?: string;
}

export function getTgDeliveriesApi(params?: {
  account_id?: number;
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgDeliveryJob[]>('/api/v1/tg/deliveries', {
    params,
  });
}

export function getTgDeliveryApi(jobId: string) {
  return requestClient.get(`/api/v1/tg/deliveries/${jobId}`);
}

export function retryTgDeliveryApi(jobId: string) {
  return requestClient.post(`/api/v1/tg/deliveries/${jobId}/retry`);
}

export function cancelTgDeliveryApi(jobId: string) {
  return requestClient.post(`/api/v1/tg/deliveries/${jobId}/cancel`);
}

/* ============ 审批 ============ */

export interface TgReplyCandidate {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  account_id: number;
  agent_run_id?: string;
  rule_id?: number;
  target_chat_id: number;
  target_topic_id?: number;
  reply_to_source_id?: number;
  content: string;
  content_hash: string;
  version: number;
  expires_at: string;
  status: string;
}

export interface TgApproval {
  id: number;
  uuid: string;
  tenant_id: number;
  project_id: number;
  candidate_id: number;
  candidate_version: number;
  content_hash: string;
  expires_at: string;
  status: string;
  reviewer_id?: number;
  decided_at?: string;
  reason?: string;
}

export function getTgApprovalsApi(params?: {
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgApproval[]>('/api/v1/tg/approvals', { params });
}

export function approveTgApprovalApi(
  pk: number,
  data: { candidate_version: number; content_hash: string; reason?: string },
) {
  return requestClient.post(`/api/v1/tg/approvals/${pk}/approve`, data);
}

export function rejectTgApprovalApi(
  pk: number,
  data: { candidate_version: number; content_hash: string; reason?: string },
) {
  return requestClient.post(`/api/v1/tg/approvals/${pk}/reject`, data);
}

export function getTgCandidatesApi(params?: {
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgReplyCandidate[]>(
    '/api/v1/tg/approvals/candidates',
    {
      params,
    },
  );
}

export function createTgCandidateApi(data: {
  account_id: number;
  agent_run_id?: string;
  attachments?: Record<string, any>;
  content: string;
  content_hash: string;
  expires_at: string;
  project_id: number;
  reply_to_source_id?: number;
  rule_id?: number;
  target_chat_id: number;
  target_topic_id?: number;
  tenant_id: number;
}) {
  return requestClient.post('/api/v1/tg/approvals/candidates', data);
}

/* ============ 运行时命令 ============ */

export interface TgRuntimeCommand {
  id: number;
  uuid: string;
  dedup_key: string;
  tenant_id: number;
  project_id: number;
  account_id: number;
  type: string;
  payload?: Record<string, any>;
  expected_generation?: number;
  deadline?: string;
  trace_id?: string;
  status: string;
  result?: string;
  issued_by: number;
  acked_at?: string;
  finished_at?: string;
  created_time: string;
}

export function issueTgCommandApi(
  accountId: number,
  data: {
    dedup_key?: string;
    expected_generation?: number;
    payload?: Record<string, any>;
    type: string;
  },
) {
  return requestClient.post<TgRuntimeCommand>(
    `/api/v1/tg/runtime/accounts/${accountId}/commands`,
    data,
  );
}

export function getTgCommandsApi(params?: {
  account_id?: number;
  project_id?: number;
  status?: string;
  tenant_id?: number;
}) {
  return requestClient.get<TgRuntimeCommand[]>('/api/v1/tg/runtime/commands', {
    params,
  });
}
