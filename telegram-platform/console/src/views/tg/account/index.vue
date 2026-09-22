<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag, useMessage } from 'naive-ui';
import { fetchTgAccounts, fetchTgProjects, fetchTgTenants, updateTgAccount, importTgAccounts } from '@/service/api';

defineOptions({ name: 'TgAccount' });

const message = useMessage();
const loading = ref(false);
const rows = ref<Api.Tg.Account[]>([]);
const tenants = ref<Api.Tg.Tenant[]>([]);
const projects = ref<Api.Tg.Project[]>([]);
const filterProject = ref<number | null>(null);

const showImport = ref(false);
const importForm = ref<{ tenant_id: number | null; project_id: number | null; file: File | null }>({
  tenant_id: null,
  project_id: null,
  file: null
});
const importing = ref(false);

async function load() {
  loading.value = true;
  const [{ data: acc }, { data: ten }, { data: proj }] = await Promise.all([
    fetchTgAccounts(filterProject.value ? { project_id: filterProject.value } : {}),
    fetchTgTenants(),
    fetchTgProjects()
  ]);
  if (acc) rows.value = acc;
  if (ten) tenants.value = ten;
  if (proj) projects.value = proj;
  loading.value = false;
}

function projectName(id: number) {
  return projects.value.find(p => p.id === id)?.name ?? `#${id}`;
}

async function setDesired(row: Api.Tg.Account, status: string) {
  const { error } = await updateTgAccount(row.id, {
    tenant_id: row.tenant_id,
    project_id: row.project_id,
    desired_status: status,
    observed_status: row.observed_status
  });
  if (!error) {
    message.success(status === 'running' ? '已下发启动' : '已下发停止');
    await load();
  }
}

async function doImport() {
  if (!importForm.value.tenant_id || !importForm.value.project_id || !importForm.value.file) {
    message.warning('请选择租户、项目和 zip 文件');
    return;
  }
  importing.value = true;
  const { error } = await importTgAccounts(importForm.value.tenant_id, importForm.value.project_id, importForm.value.file);
  importing.value = false;
  if (!error) {
    message.success('导入完成,见"导入批次"页查看分级结果');
    showImport.value = false;
    await load();
  }
}

const statusType: Record<string, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
  running: 'success',
  stopped: 'default',
  imported_quarantine: 'warning',
  imported_verified: 'info',
  auth_dead: 'error',
  error: 'error'
};

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: 'TG UID', key: 'telegram_user_id' },
  { title: '手机号', key: 'phone', render: (r: Api.Tg.Account) => r.phone || '-' },
  { title: '项目', key: 'project_id', render: (r: Api.Tg.Account) => projectName(r.project_id) },
  {
    title: '期望',
    key: 'desired_status',
    render: (r: Api.Tg.Account) => h(NTag, { type: r.desired_status === 'running' ? 'success' : 'default', size: 'small' }, { default: () => r.desired_status })
  },
  {
    title: '观测',
    key: 'observed_status',
    render: (r: Api.Tg.Account) => h(NTag, { type: statusType[r.observed_status] || 'default', size: 'small' }, { default: () => r.observed_status })
  },
  { title: '备注', key: 'remark', render: (r: Api.Tg.Account) => r.remark || '-' },
  {
    title: '操作',
    key: 'ops',
    width: 160,
    render: (r: Api.Tg.Account) =>
      h('div', { class: 'flex gap-8px' }, [
        r.desired_status !== 'running'
          ? h(NButton, { size: 'small', type: 'primary', onClick: () => setDesired(r, 'running') }, { default: () => '启动' })
          : h(NButton, { size: 'small', onClick: () => setDesired(r, 'stopped') }, { default: () => '停止' })
      ])
  }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">TG 账号</h2>
      <NSpace>
        <NSelect
          v-model:value="filterProject"
          clearable
          placeholder="按项目筛选"
          class="w-200px"
          :options="projects.map(p => ({ label: p.name, value: p.id }))"
          @update:value="load"
        />
        <NButton type="primary" @click="showImport = true">导入 Session 包</NButton>
        <NButton @click="load">刷新</NButton>
      </NSpace>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.Account) => r.id" />

    <NModal v-model:show="showImport" preset="card" title="批量导入 Session 包" class="w-480px">
      <NForm label-placement="left" label-width="80">
        <NFormItem label="租户" required>
          <NSelect v-model:value="importForm.tenant_id" :options="tenants.map(t => ({ label: t.name, value: t.id }))" />
        </NFormItem>
        <NFormItem label="项目" required>
          <NSelect
            v-model:value="importForm.project_id"
            :options="projects.filter(p => !importForm.tenant_id || p.tenant_id === importForm.tenant_id).map(p => ({ label: p.name, value: p.id }))"
          />
        </NFormItem>
        <NFormItem label="zip 文件" required>
          <input type="file" accept=".zip" @change="(e: any) => (importForm.file = e.target.files?.[0] || null)" />
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-12px">
          <NButton @click="showImport = false">取消</NButton>
          <NButton type="primary" :loading="importing" @click="doImport">上传并验证</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>
