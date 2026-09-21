<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgDeliveryJob } from '#/api/tg';

import { ref } from 'vue';

import { Page, useVbenDrawer, VbenButton } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  cancelTgDeliveryApi,
  getTgDeliveriesApi,
  getTgDeliveryApi,
  retryTgDeliveryApi,
} from '#/api/tg';

const detail = ref<any>();
const [DetailDrawer, detailApi] = useVbenDrawer({ destroyOnClose: true });

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: [
    { component: 'Input', fieldName: 'tenant_id', label: $t('tg.tenantId') },
    { component: 'Input', fieldName: 'project_id', label: $t('tg.projectId') },
    { component: 'Input', fieldName: 'account_id', label: $t('tg.accountId') },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: [
          'pending',
          'waiting_approval',
          'ready',
          'leased',
          'sending',
          'succeeded',
          'retry_wait',
          'blocked',
          'failed_permanent',
          'dead_letter',
          'uncertain',
          'cancelled',
          'expired',
          'superseded',
        ].map((s) => ({ label: s, value: s })),
      },
      fieldName: 'status',
      label: $t('tg.status'),
    },
  ],
};

const gridOptions: VxeTableGridOptions<TgDeliveryJob> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 100, showOverflow: 'tooltip' },
    { field: 'kind', title: $t('tg.kind'), width: 90 },
    { field: 'route_id', title: $t('tg.routeId'), width: 90 },
    {
      field: 'source_chat_id',
      title: $t('tg.sourceChat'),
      width: 110,
      formatter: ({ row }) =>
        `${row.source_chat_id}/${row.source_message_id}${row.revision ? ` r${row.revision}` : ''}`,
    },
    {
      field: 'target_chat_id',
      title: $t('tg.targetChat'),
      width: 110,
      formatter: ({ row }) =>
        `${row.target_chat_id}${row.target_topic_id ? `#${row.target_topic_id}` : ''}`,
    },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    { field: 'attempt_count', title: $t('tg.attemptCount'), width: 80 },
    {
      field: 'next_attempt_at',
      title: $t('tg.nextAttemptAt'),
      width: 160,
      formatter: 'formatDateTime',
    },
    {
      field: 'last_error_class',
      title: $t('tg.lastError'),
      align: 'left',
      minWidth: 140,
      showOverflow: 'tooltip',
    },
    {
      field: 'operation',
      title: $t('tg.action'),
      align: 'center',
      fixed: 'right',
      width: 220,
      slots: { default: 'operation' },
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => {
        const p = { ...formValues };
        for (const k of ['tenant_id', 'project_id', 'account_id']) {
          p[k] = p[k] ? Number(p[k]) : undefined;
        }
        return await getTgDeliveriesApi(p);
      },
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

async function openDetail(row: TgDeliveryJob) {
  detail.value = await getTgDeliveryApi(row.id);
  detailApi.open();
}

async function onRetry(row: TgDeliveryJob) {
  try {
    await retryTgDeliveryApi(row.id);
    message.success($t('ui.actionMessage.operationSuccess'));
    onRefresh();
  } catch (e: any) {
    message.error(e?.message ?? '不可重试(uncertain 需人工核实)');
  }
}

async function onCancel(row: TgDeliveryJob) {
  Modal.confirm({
    title: `${$t('tg.cancel')} ${row.id}`,
    onOk: async () => {
      try {
        await cancelTgDeliveryApi(row.id);
        message.success($t('ui.actionMessage.operationSuccess'));
        onRefresh();
      } catch (e: any) {
        message.error(e?.message ?? '当前状态不可取消');
      }
    },
  });
}
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #operation="{ row }">
        <VbenButton size="sm" variant="link" @click="openDetail(row)">
          详情
        </VbenButton>
        <VbenButton
          size="sm"
          variant="link"
          :disabled="!['failed_permanent', 'dead_letter'].includes(row.status)"
          @click="onRetry(row)"
        >
          {{ $t('tg.retry') }}
        </VbenButton>
        <VbenButton
          size="sm"
          variant="link"
          danger
          :disabled="
            ![
              'pending',
              'waiting_approval',
              'ready',
              'retry_wait',
              'blocked',
              'uncertain',
            ].includes(row.status)
          "
          @click="onCancel(row)"
        >
          {{ $t('tg.cancel') }}
        </VbenButton>
      </template>
    </Grid>
    <DetailDrawer title="投递任务详情" class="w-[720px]">
      <pre
        v-if="detail"
        class="m-4 max-h-full overflow-auto rounded bg-gray-50 p-4 text-xs"
        >{{ JSON.stringify(detail, null, 2) }}</pre
      >
    </DetailDrawer>
  </Page>
</template>
