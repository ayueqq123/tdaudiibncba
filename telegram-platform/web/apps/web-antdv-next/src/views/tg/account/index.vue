<script lang="ts" setup>
import type { VbenFormProps, VbenFormSchema } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgAccount, TgProject, TgTenant } from '#/api/tg';

import { ref } from 'vue';

import { Page, useVbenModal, VbenButton } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { message, Modal, Select } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  getTgAccountsApi,
  getTgProjectsApi,
  getTgTenantsApi,
  importTgAccountsApi,
  updateTgAccountApi,
} from '#/api/tg';

const tenants = ref<TgTenant[]>([]);
const projects = ref<TgProject[]>([]);
const importTenantId = ref<number>();
const importProjectId = ref<number>();
const importFile = ref<File>();
const importing = ref(false);

async function loadScope() {
  tenants.value = await getTgTenantsApi({ status: 1 });
  projects.value = await getTgProjectsApi();
}

const querySchema: VbenFormSchema[] = [
  { component: 'Input', fieldName: 'tenant_id', label: $t('tg.tenantId') },
  { component: 'Input', fieldName: 'project_id', label: $t('tg.projectId') },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: [
        'imported_quarantine',
        'activating',
        'online',
        'auth_dead',
        'banned',
        'stopped',
      ].map((s) => ({ label: s, value: s })),
    },
    fieldName: 'status',
    label: $t('tg.observedStatus'),
  },
];

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: querySchema,
};

const gridOptions: VxeTableGridOptions<TgAccount> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 70 },
    { field: 'phone', title: $t('tg.phone'), width: 140 },
    { field: 'username', title: $t('tg.username'), width: 140 },
    { field: 'telegram_user_id', title: $t('tg.tgUserId'), width: 120 },
    { field: 'project_id', title: $t('tg.projectId'), width: 90 },
    {
      field: 'desired_status',
      title: $t('tg.desiredStatus'),
      width: 110,
      cellRender: { name: 'CellTag' },
    },
    {
      field: 'observed_status',
      title: $t('tg.observedStatus'),
      width: 130,
      cellRender: { name: 'CellTag' },
    },
    {
      field: 'last_seen_at',
      title: $t('tg.lastSeenAt'),
      width: 160,
      formatter: 'formatDateTime',
    },
    {
      field: 'last_error',
      title: $t('tg.lastError'),
      align: 'left',
      minWidth: 160,
      showOverflow: 'tooltip',
    },
    {
      field: 'operation',
      title: $t('tg.action'),
      align: 'center',
      fixed: 'right',
      width: 200,
      slots: { default: 'operation' },
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => {
        const p = { ...formValues };
        p.tenant_id = p.tenant_id ? Number(p.tenant_id) : undefined;
        p.project_id = p.project_id ? Number(p.project_id) : undefined;
        return await getTgAccountsApi(p);
      },
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

async function toggleStatus(row: TgAccount) {
  const next = row.desired_status === 'running' ? 'stopped' : 'running';
  await updateTgAccountApi(row.id, { desired_status: next });
  message.success($t('ui.actionMessage.operationSuccess'));
  onRefresh();
}

const [ImportModal, importModalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    if (!importTenantId.value || !importProjectId.value || !importFile.value) {
      message.warning('请选择租户、项目和 zip 文件');
      return;
    }
    importModalApi.lock();
    importing.value = true;
    try {
      const batch = await importTgAccountsApi({
        tenant_id: importTenantId.value,
        project_id: importProjectId.value,
        file: importFile.value,
      });
      Modal.success({
        title: '导入完成',
        content: `共 ${batch.total} 条:验证通过 ${batch.verified},失败 ${batch.failed}`,
      });
      await importModalApi.close();
      onRefresh();
    } finally {
      importModalApi.unlock();
      importing.value = false;
    }
  },
});

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  importFile.value = input.files?.[0];
}

loadScope();
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #toolbar-actions>
        <VbenButton @click="importModalApi.open()">
          {{ $t('tg.importZip') }}
        </VbenButton>
      </template>
      <template #operation="{ row }">
        <VbenButton size="sm" variant="link" @click="toggleStatus(row)">
          {{
            row.desired_status === 'running'
              ? $t('tg.stopped')
              : $t('tg.running')
          }}
        </VbenButton>
      </template>
    </Grid>
    <ImportModal :title="$t('tg.importZip')">
      <div class="flex flex-col gap-3 p-2">
        <label>{{ $t('tg.tenant') }}</label>
        <Select
          v-model:value="importTenantId"
          :options="
            tenants.map((t) => ({ label: `${t.name} (${t.id})`, value: t.id }))
          "
          show-search
        />
        <label>{{ $t('tg.project') }}</label>
        <Select
          v-model:value="importProjectId"
          :options="
            projects
              .filter((p) => p.tenant_id === importTenantId)
              .map((p) => ({ label: `${p.name} (${p.id})`, value: p.id }))
          "
          show-search
        />
        <label>Session 包 (.zip)</label>
        <input type="file" accept=".zip" @change="onFileChange" />
        <p class="text-xs text-gray-500">
          上传后立即执行 connect+getMe 验证;通过账号进入 imported_quarantine。
        </p>
      </div>
    </ImportModal>
  </Page>
</template>
