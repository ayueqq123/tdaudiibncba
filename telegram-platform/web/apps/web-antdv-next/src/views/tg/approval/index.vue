<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgApproval } from '#/api/tg';

import { ref } from 'vue';

import { Page, useVbenModal, VbenButton } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { Input, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  approveTgApprovalApi,
  getTgApprovalsApi,
  rejectTgApprovalApi,
} from '#/api/tg';

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: [
    { component: 'Input', fieldName: 'tenant_id', label: $t('tg.tenantId') },
    { component: 'Input', fieldName: 'project_id', label: $t('tg.projectId') },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: ['pending', 'approved', 'rejected', 'expired'].map((s) => ({
          label: s,
          value: s,
        })),
      },
      fieldName: 'status',
      label: $t('tg.status'),
    },
  ],
};

const gridOptions: VxeTableGridOptions<TgApproval> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 70 },
    { field: 'candidate_id', title: '候选 ID', width: 90 },
    { field: 'candidate_version', title: $t('tg.version'), width: 70 },
    {
      field: 'content_hash',
      title: $t('tg.contentHash'),
      width: 160,
      showOverflow: 'tooltip',
    },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    {
      field: 'expires_at',
      title: $t('tg.expiresAt'),
      width: 160,
      formatter: 'formatDateTime',
    },
    { field: 'reviewer_id', title: $t('tg.reviewer'), width: 90 },
    {
      field: 'decided_at',
      title: $t('tg.decidedAt'),
      width: 160,
      formatter: 'formatDateTime',
    },
    { field: 'reason', title: $t('tg.reason'), align: 'left', minWidth: 140 },
    {
      field: 'operation',
      title: $t('tg.action'),
      align: 'center',
      fixed: 'right',
      width: 180,
      slots: { default: 'operation' },
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => {
        const p = { ...formValues };
        p.tenant_id = p.tenant_id ? Number(p.tenant_id) : undefined;
        p.project_id = p.project_id ? Number(p.project_id) : undefined;
        return await getTgApprovalsApi(p);
      },
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

const decideTarget = ref<TgApproval>();
const decideAction = ref<'approve' | 'reject'>('approve');
const decideReason = ref('');

const [DecideModal, decideModalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const row = decideTarget.value;
    if (!row) return;
    decideModalApi.lock();
    const data = {
      candidate_version: row.candidate_version,
      content_hash: row.content_hash,
      reason: decideReason.value || undefined,
    };
    try {
      await (decideAction.value === 'approve'
        ? approveTgApprovalApi(row.id, data)
        : rejectTgApprovalApi(row.id, data));
      message.success($t('ui.actionMessage.operationSuccess'));
      await decideModalApi.close();
      onRefresh();
    } catch (e: any) {
      message.error(e?.message ?? '决定失败(版本/hash 不一致或已过期)');
    } finally {
      decideModalApi.unlock();
    }
  },
});

function openDecide(row: TgApproval, action: 'approve' | 'reject') {
  decideTarget.value = row;
  decideAction.value = action;
  decideReason.value = '';
  decideModalApi.open();
}
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #operation="{ row }">
        <VbenButton
          size="sm"
          variant="link"
          :disabled="row.status !== 'pending'"
          @click="openDecide(row, 'approve')"
        >
          {{ $t('tg.approve') }}
        </VbenButton>
        <VbenButton
          size="sm"
          variant="link"
          danger
          :disabled="row.status !== 'pending'"
          @click="openDecide(row, 'reject')"
        >
          {{ $t('tg.reject') }}
        </VbenButton>
      </template>
    </Grid>
    <DecideModal
      :title="decideAction === 'approve' ? $t('tg.approve') : $t('tg.reject')"
    >
      <div class="flex flex-col gap-3 p-2">
        <p class="text-xs text-gray-500">
          审批绑定 candidate v{{ decideTarget?.candidate_version }} · hash
          {{ decideTarget?.content_hash }};若内容已变更则提交将返回 409。
        </p>
        <Input v-model:value="decideReason" :placeholder="$t('tg.reason')" />
      </div>
    </DecideModal>
  </Page>
</template>
