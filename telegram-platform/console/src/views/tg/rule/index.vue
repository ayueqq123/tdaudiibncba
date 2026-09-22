<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag, NSpace, useMessage } from 'naive-ui';
import {
  fetchCloneRules,
  fetchCloneRule,
  createCloneRule,
  addCloneTarget,
  publishCloneRule,
  fetchCloneRuleVersions,
  fetchTgAccounts,
  fetchTgTenants,
  fetchTgProjects
} from '@/service/api';

defineOptions({ name: 'TgRule' });

const message = useMessage();
const loading = ref(false);
const rows = ref<Api.Tg.CloneRule[]>([]);
const accounts = ref<Api.Tg.Account[]>([]);
const tenants = ref<Api.Tg.Tenant[]>([]);
const projects = ref<Api.Tg.Project[]>([]);

const showCreate = ref(false);
const form = ref<any>({ tenant_id: null, project_id: null, account_id: null, name: '', mode: 'copy', enabled: true, remark: '' });

const showTarget = ref(false);
const targetRule = ref<Api.Tg.CloneRule | null>(null);
const targetForm = ref<any>({ source_chat_id: null, source_topic_id: null, target_chat_id: null, target_topic_id: null, remark: '' });

const showVersions = ref(false);
const versions = ref<Api.Tg.CloneRuleVersion[]>([]);
const versionRule = ref<Api.Tg.CloneRule | null>(null);

async function load() {
  loading.value = true;
  const [{ data: rules }, { data: acc }, { data: ten }, { data: proj }] = await Promise.all([
    fetchCloneRules(),
    fetchTgAccounts(),
    fetchTgTenants(),
    fetchTgProjects()
  ]);
  if (rules) rows.value = rules;
  if (acc) accounts.value = acc;
  if (ten) tenants.value = ten;
  if (proj) projects.value = proj;
  loading.value = false;
}

async function doCreate() {
  const f = form.value;
  if (!f.tenant_id || !f.project_id || !f.account_id || !f.name) {
    message.warning('租户/项目/账号/名称必填');
    return;
  }
  const { error } = await createCloneRule(f);
  if (!error) {
    message.success('规则已创建(草稿)');
    showCreate.value = false;
    await load();
  }
}

function openTarget(r: Api.Tg.CloneRule) {
  targetRule.value = r;
  targetForm.value = { source_chat_id: null, source_topic_id: null, target_chat_id: null, target_topic_id: null, remark: '' };
  showTarget.value = true;
}

async function doAddTarget() {
  const r = targetRule.value;
  const t = targetForm.value;
  if (!r || t.source_chat_id === null || t.target_chat_id === null) {
    message.warning('源/目标 chat_id 必填');
    return;
  }
  const { error } = await addCloneTarget(r.id, t);
  if (!error) {
    message.success('已添加目标');
    showTarget.value = false;
    await load();
  }
}

async function doPublish(r: Api.Tg.CloneRule) {
  const { error } = await publishCloneRule(r.id, r.current_version);
  if (!error) {
    message.success('已发布新版本快照,worker 将热加载');
    await load();
  }
}

async function openVersions(r: Api.Tg.CloneRule) {
  const { data } = await fetchCloneRuleVersions(r.id);
  if (data) {
    versions.value = data;
    versionRule.value = r;
    showVersions.value = true;
  }
}

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '名称', key: 'name' },
  { title: '账号', key: 'account_id', render: (r: Api.Tg.CloneRule) => accounts.value.find(a => a.id === r.account_id)?.phone || `#${r.account_id}` },
  { title: '模式', key: 'mode', render: (r: Api.Tg.CloneRule) => h(NTag, { size: 'small', type: r.mode === 'copy' ? 'info' : 'warning' }, { default: () => r.mode }) },
  { title: '启用', key: 'enabled', render: (r: Api.Tg.CloneRule) => (r.enabled ? '是' : '否') },
  { title: '版本', key: 'current_version', render: (r: Api.Tg.CloneRule) => `v${r.current_version}` },
  { title: '目标数', key: 'targets', render: (r: Api.Tg.CloneRule) => r.targets?.length ?? '-' },
  {
    title: '操作',
    key: 'ops',
    width: 240,
    render: (r: Api.Tg.CloneRule) =>
      h(NSpace, {}, () => [
        h(NButton, { size: 'small', onClick: () => openTarget(r) }, { default: () => '加目标' }),
        h(NButton, { size: 'small', type: 'primary', onClick: () => doPublish(r) }, { default: () => '发布' }),
        h(NButton, { size: 'small', onClick: () => openVersions(r) }, { default: () => '版本' })
      ])
  }
];

const versionColumns = [
  { title: '版本', key: 'version', render: (r: Api.Tg.CloneRuleVersion) => `v${r.version}` },
  { title: '发布时间', key: 'published_at' },
  { title: '快照', key: 'snapshot', ellipsis: { tooltip: true }, render: (r: Api.Tg.CloneRuleVersion) => JSON.stringify(r.snapshot) }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">Clone 规则</h2>
      <NSpace>
        <NButton type="primary" @click="showCreate = true">新建规则</NButton>
        <NButton @click="load">刷新</NButton>
      </NSpace>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.CloneRule) => r.id" />

    <NModal v-model:show="showCreate" preset="card" title="新建 Clone 规则" class="w-480px">
      <NForm label-placement="left" label-width="80">
        <NFormItem label="租户" required>
          <NSelect v-model:value="form.tenant_id" :options="tenants.map(t => ({ label: t.name, value: t.id }))" />
        </NFormItem>
        <NFormItem label="项目" required>
          <NSelect
            v-model:value="form.project_id"
            :options="projects.filter(p => !form.tenant_id || p.tenant_id === form.tenant_id).map(p => ({ label: p.name, value: p.id }))"
          />
        </NFormItem>
        <NFormItem label="账号" required>
          <NSelect
            v-model:value="form.account_id"
            :options="accounts.filter(a => !form.project_id || a.project_id === form.project_id).map(a => ({ label: a.phone || String(a.telegram_user_id || a.id), value: a.id }))"
          />
        </NFormItem>
        <NFormItem label="名称" required><NInput v-model:value="form.name" /></NFormItem>
        <NFormItem label="模式">
          <NRadioGroup v-model:value="form.mode">
            <NRadioButton value="copy">copy</NRadioButton>
            <NRadioButton value="forward">forward</NRadioButton>
          </NRadioGroup>
        </NFormItem>
        <NFormItem label="启用"><NSwitch v-model:value="form.enabled" /></NFormItem>
        <NFormItem label="备注"><NInput v-model:value="form.remark" /></NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-12px">
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" @click="doCreate">创建</NButton>
        </div>
      </template>
    </NModal>

    <NModal v-model:show="showTarget" preset="card" :title="`为规则 ${targetRule?.name} 添加目标`" class="w-480px">
      <NForm label-placement="left" label-width="110">
        <NFormItem label="源 chat_id" required>
          <NInputNumber v-model:value="targetForm.source_chat_id" :show-button="false" class="w-full" placeholder="-100xxxx" />
        </NFormItem>
        <NFormItem label="源 topic_id">
          <NInputNumber v-model:value="targetForm.source_topic_id" :show-button="false" class="w-full" />
        </NFormItem>
        <NFormItem label="目标 chat_id" required>
          <NInputNumber v-model:value="targetForm.target_chat_id" :show-button="false" class="w-full" />
        </NFormItem>
        <NFormItem label="目标 topic_id">
          <NInputNumber v-model:value="targetForm.target_topic_id" :show-button="false" class="w-full" />
        </NFormItem>
        <NFormItem label="备注"><NInput v-model:value="targetForm.remark" /></NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-12px">
          <NButton @click="showTarget = false">取消</NButton>
          <NButton type="primary" @click="doAddTarget">添加</NButton>
        </div>
      </template>
    </NModal>

    <NModal v-model:show="showVersions" preset="card" :title="`规则 ${versionRule?.name} 发布历史`" class="w-720px">
      <NDataTable :columns="versionColumns" :data="versions" size="small" />
    </NModal>
  </div>
</template>
