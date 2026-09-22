<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgImportBatch } from '#/api/tg';

import { ref } from 'vue';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getTgImportApi, getTgImportsApi } from '#/api/tg';

const detail = ref<TgImportBatch>();

const [DetailDrawer, detailApi] = useVbenDrawer({ destroyOnClose: true });

async function openDetail(row: TgImportBatch) {
  detail.value = await getTgImportApi(row.id);
  detailApi.open();
}

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: [
    { component: 'Input', fieldName: 'tenant_id', label: $t('tg.tenantId') },
    { component: 'Input', fieldName: 'project_id', label: $t('tg.projectId') },
  ],
};

const gridOptions: VxeTableGridOptions<TgImportBatch> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 80 },
    { field: 'uuid', title: 'UUID', width: 280, showOverflow: 'tooltip' },
    { field: 'tenant_id', title: $t('tg.tenantId'), width: 90 },
    { field: 'project_id', title: $t('tg.projectId'), width: 90 },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    { field: 'total', title: $t('tg.totalCount'), width: 90 },
    { field: 'verified', title: $t('tg.verifiedCount'), width: 90 },
    { field: 'failed', title: $t('tg.failedCount'), width: 90 },
    {
      field: 'created_time',
      title: $t('tg.createdTime'),
      width: 168,
      formatter: 'formatDateTime',
    },
    {
      field: 'operation',
      title: $t('tg.action'),
      align: 'center',
      fixed: 'right',
      width: 100,
      slots: { default: 'operation' },
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => {
        const p = { ...formValues };
        p.tenant_id = p.tenant_id ? Number(p.tenant_id) : undefined;
        p.project_id = p.project_id ? Number(p.project_id) : undefined;
        return await getTgImportsApi(p);
      },
    },
  },
};

const [Grid] = useVbenVxeGrid({ formOptions, gridOptions });
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #operation="{ row }">
        <a @click="openDetail(row)">详情</a>
      </template>
    </Grid>
    <DetailDrawer title="导入批次明细" class="w-[720px]">
      <pre
        v-if="detail"
        class="m-4 max-h-full overflow-auto rounded bg-gray-50 p-4 text-xs"
        >{{ JSON.stringify(detail.detail ?? detail, null, 2) }}</pre
      >
    </DetailDrawer>
  </Page>
</template>
