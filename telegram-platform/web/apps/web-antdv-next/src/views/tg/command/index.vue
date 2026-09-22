<script lang="ts" setup>
import type { VbenFormProps, VbenFormSchema } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgRuntimeCommand } from '#/api/tg';

import { Page, useVbenModal, VbenButton } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getTgCommandsApi, issueTgCommandApi } from '#/api/tg';

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
        options: ['pending', 'acknowledged', 'done', 'rejected', 'expired'].map(
          (s) => ({ label: s, value: s }),
        ),
      },
      fieldName: 'status',
      label: $t('tg.status'),
    },
  ],
};

const gridOptions: VxeTableGridOptions<TgRuntimeCommand> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 70 },
    { field: 'account_id', title: $t('tg.accountId'), width: 90 },
    { field: 'type', title: $t('tg.commandType'), width: 140 },
    {
      field: 'dedup_key',
      title: $t('tg.dedupKey'),
      width: 140,
      showOverflow: 'tooltip',
    },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    { field: 'result', title: $t('tg.result'), align: 'left', minWidth: 160 },
    {
      field: 'deadline',
      title: $t('tg.deadline'),
      width: 160,
      formatter: 'formatDateTime',
    },
    {
      field: 'created_time',
      title: $t('tg.createdTime'),
      width: 160,
      formatter: 'formatDateTime',
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => {
        const p = { ...formValues };
        for (const k of ['tenant_id', 'project_id', 'account_id']) {
          p[k] = p[k] ? Number(p[k]) : undefined;
        }
        return await getTgCommandsApi(p);
      },
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

const issueSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'account_id',
    label: $t('tg.accountId'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Select',
    componentProps: {
      options: [
        'StartAccount',
        'StopAccount',
        'ReloadConfig',
        'SyncChats',
        'ReconcileSource',
        'CancelJob',
      ].map((s) => ({ label: s, value: s })),
    },
    fieldName: 'type',
    label: $t('tg.commandType'),
    rules: 'required',
  },
  { component: 'Textarea', fieldName: 'payload', label: 'Payload (JSON)' },
  { component: 'Input', fieldName: 'dedup_key', label: $t('tg.dedupKey') },
];

const [IssueForm, issueFormApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: issueSchema,
});

const [IssueModal, issueModalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await issueFormApi.validate();
    if (!valid) return;
    issueModalApi.lock();
    const values = await issueFormApi.getValues();
    try {
      await issueTgCommandApi(Number(values.account_id), {
        type: values.type,
        payload: values.payload ? JSON.parse(values.payload) : undefined,
        dedup_key: values.dedup_key || undefined,
      });
      message.success($t('ui.actionMessage.operationSuccess'));
      await issueModalApi.close();
      gridApi.query();
    } finally {
      issueModalApi.unlock();
    }
  },
});
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #toolbar-actions>
        <VbenButton @click="issueModalApi.open()">
          {{ $t('tg.issueCommand') }}
        </VbenButton>
      </template>
    </Grid>
    <IssueModal :title="$t('tg.issueCommand')">
      <IssueForm />
    </IssueModal>
  </Page>
</template>
