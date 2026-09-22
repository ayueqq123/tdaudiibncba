import { request } from '../request';

const TG = '/tg';

// ---------- 租户 / 项目 ----------

export function fetchTgTenants() {
  return request<Api.Tg.Tenant[]>({ url: `${TG}/tenants` });
}
export function createTgTenant(data: { name: string; status: number; remark?: string | null }) {
  return request<Api.Tg.Tenant>({ url: `${TG}/tenants`, method: 'post', data });
}
export function deleteTgTenant(pk: number) {
  return request<null>({ url: `${TG}/tenants/${pk}`, method: 'delete' });
}

export function fetchTgProjects(tenantId?: number) {
  return request<Api.Tg.Project[]>({ url: `${TG}/projects`, params: tenantId ? { tenant_id: tenantId } : {} });
}
export function createTgProject(data: { name: string; tenant_id: number; status: number; remark?: string | null }) {
  return request<Api.Tg.Project>({ url: `${TG}/projects`, method: 'post', data });
}
export function deleteTgProject(pk: number) {
  return request<null>({ url: `${TG}/projects/${pk}`, method: 'delete' });
}

// ---------- 账号 / 导入 ----------

export function fetchTgAccounts(params?: { tenant_id?: number; project_id?: number; status?: string }) {
  return request<Api.Tg.Account[]>({ url: `${TG}/accounts`, params });
}
export function updateTgAccount(pk: number, data: Record<string, any>) {
  return request<null>({ url: `${TG}/accounts/${pk}`, method: 'put', data });
}
export function importTgAccounts(tenantId: number, projectId: number, file: File) {
  const form = new FormData();
  form.append('tenant_id', String(tenantId));
  form.append('project_id', String(projectId));
  form.append('file', file);
  return request<Api.Tg.ImportBatch>({ url: `${TG}/accounts/import`, method: 'post', data: form });
}

export function fetchImportBatches(params?: { tenant_id?: number; project_id?: number }) {
  return request<Api.Tg.ImportBatch[]>({ url: `${TG}/imports`, params });
}
export function fetchImportBatch(id: number) {
  return request<Api.Tg.ImportBatch>({ url: `${TG}/imports/${id}` });
}

// ---------- Clone 规则 ----------

export function fetchCloneRules(params?: { tenant_id?: number; project_id?: number }) {
  return request<Api.Tg.CloneRule[]>({ url: `${TG}/clone-rules`, params });
}
export function fetchCloneRule(pk: number) {
  return request<Api.Tg.CloneRule>({ url: `${TG}/clone-rules/${pk}` });
}
export function createCloneRule(data: Record<string, any>) {
  return request<Api.Tg.CloneRule>({ url: `${TG}/clone-rules`, method: 'post', data });
}
export function updateCloneRule(pk: number, data: Record<string, any>) {
  return request<Api.Tg.CloneRule>({ url: `${TG}/clone-rules/${pk}`, method: 'put', data });
}
export function deleteCloneRule(pk: number) {
  return request<null>({ url: `${TG}/clone-rules/${pk}`, method: 'delete' });
}
export function addCloneTarget(pk: number, data: Record<string, any>) {
  return request<Api.Tg.CloneTarget>({ url: `${TG}/clone-rules/${pk}/targets`, method: 'post', data });
}
export function publishCloneRule(pk: number, expectedVersion: number) {
  return request<Api.Tg.CloneRuleVersion>({
    url: `${TG}/clone-rules/${pk}/publish`,
    method: 'post',
    data: { expected_version: expectedVersion }
  });
}
export function fetchCloneRuleVersions(pk: number) {
  return request<Api.Tg.CloneRuleVersion[]>({ url: `${TG}/clone-rules/${pk}/versions` });
}
export function dryRunCloneRule(pk: number, data?: Record<string, any>) {
  return request<Record<string, any>>({ url: `${TG}/clone-rules/${pk}/dry-run`, method: 'post', data });
}

// ---------- 投递 ----------

export function fetchDeliveries(params?: { tenant_id?: number; project_id?: number; account_id?: number; status?: string }) {
  return request<Api.Tg.DeliveryJob[]>({ url: `${TG}/deliveries`, params });
}
export function fetchDelivery(id: string) {
  return request<Api.Tg.DeliveryJob>({ url: `${TG}/deliveries/${id}` });
}
export function retryDelivery(id: string, reason?: string) {
  return request<Api.Tg.DeliveryJob>({ url: `${TG}/deliveries/${id}/retry`, method: 'post', data: { reason } });
}
export function cancelDelivery(id: string, reason?: string) {
  return request<Api.Tg.DeliveryJob>({ url: `${TG}/deliveries/${id}/cancel`, method: 'post', data: { reason } });
}

// ---------- 审批 ----------

export function fetchApprovals(params?: { tenant_id?: number; project_id?: number; status?: string }) {
  return request<Api.Tg.Approval[]>({ url: `${TG}/approvals`, params });
}
export function fetchCandidates(params?: { tenant_id?: number; project_id?: number; status?: string }) {
  return request<Api.Tg.ReplyCandidate[]>({ url: `${TG}/approvals/candidates`, params });
}
export function approveApproval(pk: number, data: { candidate_version: number; content_hash: string; reason?: string }) {
  return request<Api.Tg.Approval>({ url: `${TG}/approvals/${pk}/approve`, method: 'post', data });
}
export function rejectApproval(pk: number, data: { candidate_version: number; content_hash: string; reason?: string }) {
  return request<Api.Tg.Approval>({ url: `${TG}/approvals/${pk}/reject`, method: 'post', data });
}

// ---------- 运行时命令 ----------

export function fetchRuntimeCommands(params?: { tenant_id?: number; project_id?: number; account_id?: number }) {
  return request<Api.Tg.RuntimeCommand[]>({ url: `${TG}/runtime/commands`, params });
}
export function issueRuntimeCommand(accountId: number, data: { type: Api.Tg.RuntimeCommandType; payload?: Record<string, any> | null; dedup_key?: string }) {
  return request<Api.Tg.RuntimeCommand>({ url: `${TG}/runtime/accounts/${accountId}/commands`, method: 'post', data });
}
