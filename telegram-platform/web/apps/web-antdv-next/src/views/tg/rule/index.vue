<script lang="ts" setup>
import type { VbenFormProps, VbenFormSchema } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgCloneRule, TgCloneRuleVersion } from '#/api/tg';

import { ref } from 'vue';

import { Page, useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';
import { $t } from '@vben/locales';

import { message, Modal } from 'antdv-next';

import { useVbenForm, z } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  addTgCloneTargetApi,
  createTgCloneRuleApi,
  deleteTgCloneRuleApi,
  dryRunTgCloneRuleApi,
  getTgCloneRuleApi,
  getTgCloneRulesApi,
  getTgCloneRuleVersionsApi,
  publishTgCloneRuleApi,
  retireTgCloneTargetApi,
} from '#/api/tg';

const detail = ref<TgCloneRule>();
const versions = ref<TgCloneRuleVersion[]>([]);

const [DetailDrawer, detailApi] = useVbenDrawer({ destroyOnClose: true });
const [VersionsDrawer, versionsApi] = useVbenDrawer({ destroyOnClose: true });

const createSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'tenant_id',
    label: $t('tg.tenantId'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'project_id',
    label: $t('tg.projectId'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'account_id',
    label: $t('tg.accountId'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'name',
    label: $t('tg.name'),
    rules: z.string().min(1),
  },
  {
    component: 'RadioGroup',
    componentProps: {
      buttonStyle: 'solid',
      options: [
        { label: 'copy', value: 'copy' },
        { label: 'forward', value: 'forward' },
      ],
      optionType: 'button',
    },
    defaultValue: 'copy',
    fieldName: 'mode',
    label: $t('tg.mode'),
  },
  { component: 'Textarea', fieldName: 'remark', label: $t('tg.remark') },
];

const targetSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'source_chat_id',
    label: $t('tg.sourceChat'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'source_topic_id',
    label: 'Source Topic ID',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'target_chat_id',
    label: $t('tg.targetChat'),
    rules: 'required',
    componentProps: { type: 'number' },
  },
  {
    component: 'Input',
    fieldName: 'target_topic_id',
    label: 'Target Topic ID',
    componentProps: { type: 'number' },
  },
  {
    component: 'Textarea',
    fieldName: 'filters',
    label: 'Filters (JSON)',
  },
  { component: 'Textarea', fieldName: 'remark', label: $t('tg.remark') },
];

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
        options: ['draft', 'published', 'disabled'].map((s) => ({
          label: s,
          value: s,
        })),
      },
      fieldName: 'status',
      label: $t('tg.status'),
    },
  ],
};

const gridOptions: VxeTableGridOptions<TgCloneRule> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 70 },
    { field: 'name', title: $t('tg.name'), align: 'left', minWidth: 140 },
    { field: 'account_id', title: $t('tg.accountId'), width: 90 },
    { field: 'mode', title: $t('tg.mode'), width: 90 },
    {
      field: 'enabled',
      title: $t('tg.enabled'),
      width: 80,
      cellRender: { name: 'CellTag' },
    },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    { field: 'current_version', title: $t('tg.version'), width: 80 },
    {
      field: 'operation',
      title: $t('tg.action'),
      align: 'center',
      fixed: 'right',
      width: 300,
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
        return await getTgCloneRulesApi(p);
      },
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

async function onDryRun(row: TgCloneRule) {
  const result = await dryRunTgCloneRuleApi(row.id);
  Modal.info({
    title: `Dry-run · next version ${result.next_version}`,
    width: 640,
    content: JSON.stringify(result, null, 2),
  });
}

async function onPublish(row: TgCloneRule) {
  Modal.confirm({
    title: `${$t('tg.publish')} v${row.current_version + 1}`,
    content: '发布会生成不可变快照;expected_version 需与当前一致。',
    onOk: async () => {
      try {
        await publishTgCloneRuleApi(row.id, row.current_version);
        message.success($t('ui.actionMessage.operationSuccess'));
        onRefresh();
      } catch {
        message.error('发布失败:版本冲突或规则已禁用');
      }
    },
  });
}

async function openDetail(row: TgCloneRule) {
  detail.value = await getTgCloneRuleApi(row.id);
  detailApi.open();
}

async function openVersions(row: TgCloneRule) {
  versions.value = await getTgCloneRuleVersionsApi(row.id);
  versionsApi.open();
}

async function onRetireTarget(row: TgCloneRule, targetId: number) {
  await retireTgCloneTargetApi(row.id, targetId);
  message.success($t('ui.actionMessage.operationSuccess'));
  detail.value = await getTgCloneRuleApi(row.id);
  onRefresh();
}

const [CreateForm, createFormApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: createSchema,
});

const [CreateModal, createModalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await createFormApi.validate();
    if (!valid) return;
    createModalApi.lock();
    const values = await createFormApi.getValues();
    try {
      await createTgCloneRuleApi({
        tenant_id: Number(values.tenant_id),
        project_id: Number(values.project_id),
        account_id: Number(values.account_id),
        name: values.name,
        mode: values.mode,
        remark: values.remark,
      });
      message.success($t('ui.actionMessage.operationSuccess'));
      await createModalApi.close();
      onRefresh();
    } finally {
      createModalApi.unlock();
    }
  },
});

const [TargetForm, targetFormApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: targetSchema,
});

const currentRuleId = ref<number>();

const [TargetModal, targetModalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await targetFormApi.validate();
    if (!valid || !currentRuleId.value) return;
    targetModalApi.lock();
    const values = await targetFormApi.getValues();
    try {
      await addTgCloneTargetApi(currentRuleId.value, {
        source_chat_id: Number(values.source_chat_id),
        source_topic_id: values.source_topic_id
          ? Number(values.source_topic_id)
          : undefined,
        target_chat_id: Number(values.target_chat_id),
        target_topic_id: values.target_topic_id
          ? Number(values.target_topic_id)
          : undefined,
        filters: values.filters ? JSON.parse(values.filters) : undefined,
        remark: values.remark,
      });
      message.success($t('ui.actionMessage.operationSuccess'));
      await targetModalApi.close();
      detail.value = await getTgCloneRuleApi(currentRuleId.value);
      onRefresh();
    } finally {
      targetModalApi.unlock();
    }
  },
});

function openAddTarget(row: TgCloneRule) {
  currentRuleId.value = row.id;
  targetModalApi.open();
}

async function onDelete(row: TgCloneRule) {
  await deleteTgCloneRuleApi(row.id);
  message.success($t('ui.actionMessage.deleteSuccess', [row.name]));
  onRefresh();
}
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #toolbar-actions>
        <VbenButton @click="createModalApi.open()">
          <MaterialSymbolsAdd class="size-5" />
          {{ $t('ui.actionTitle.create', [$t('tg.rule')]) }}
        </VbenButton>
      </template>
      <template #operation="{ row }">
        <VbenButton size="sm" variant="link" @click="openDetail(row)">
          详情
        </VbenButton>
        <VbenButton size="sm" variant="link" @click="onDryRun(row)">
          {{ $t('tg.dryRun') }}
        </VbenButton>
        <VbenButton
          size="sm"
          variant="link"
          :disabled="row.status !== 'draft'"
          @click="onPublish(row)"
        >
          {{ $t('tg.publish') }}
        </VbenButton>
        <VbenButton size="sm" variant="link" @click="openVersions(row)">
          {{ $t('tg.ruleVersions') }}
        </VbenButton>
        <VbenButton size="sm" variant="link" danger @click="onDelete(row)">
          删除
        </VbenButton>
      </template>
    </Grid>

    <CreateModal :title="$t('ui.actionTitle.create', [$t('tg.rule')])">
      <CreateForm />
    </CreateModal>

    <TargetModal title="添加路由目标">
      <TargetForm />
    </TargetModal>

    <DetailDrawer title="规则详情" class="w-[720px]">
      <div v-if="detail" class="flex flex-col gap-4 p-4">
        <VbenButton @click="openAddTarget(detail)">
          {{ $t('ui.actionTitle.create', ['目标']) }}
        </VbenButton>
        <table class="w-full text-left text-sm">
          <thead>
            <tr>
              <th>{{ $t('tg.routeId') }}</th>
              <th>{{ $t('tg.sourceChat') }}</th>
              <th>{{ $t('tg.targetChat') }}</th>
              <th>{{ $t('tg.status') }}</th>
              <th>{{ $t('tg.action') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in detail.targets" :key="t.id">
              <td>{{ t.route_id }}</td>
              <td>
                {{ t.source_chat_id
                }}<template v-if="t.source_topic_id"
                  >#{{ t.source_topic_id }}</template
                >
              </td>
              <td>
                {{ t.target_chat_id
                }}<template v-if="t.target_topic_id"
                  >#{{ t.target_topic_id }}</template
                >
              </td>
              <td>{{ t.status }}</td>
              <td>
                <a
                  v-if="t.status === 'active'"
                  class="text-red-500"
                  @click="onRetireTarget(detail!, t.id)"
                >
                  退役
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </DetailDrawer>

    <VersionsDrawer :title="$t('tg.ruleVersions')" class="w-[720px]">
      <pre
        class="m-4 max-h-full overflow-auto rounded bg-gray-50 p-4 text-xs"
        >{{ JSON.stringify(versions, null, 2) }}</pre
      >
    </VersionsDrawer>
  </Page>
</template>
