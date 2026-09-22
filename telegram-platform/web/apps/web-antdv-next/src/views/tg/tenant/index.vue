<script lang="ts" setup>
import type { VbenFormProps, VbenFormSchema } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgTenant } from '#/api/tg';

import { computed, ref } from 'vue';

import { Page, useVbenModal, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';
import { $t } from '@vben/locales';

import { message } from 'antdv-next';

import { useVbenForm, z } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  createTgTenantApi,
  deleteTgTenantApi,
  getTgTenantsApi,
  updateTgTenantApi,
} from '#/api/tg';

const schema: VbenFormSchema[] = [
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
        { label: '正常', value: 1 },
        { label: '停用', value: 0 },
      ],
      optionType: 'button',
    },
    defaultValue: 1,
    fieldName: 'status',
    label: $t('tg.status'),
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: $t('tg.remark'),
  },
];

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: [
    { component: 'Input', fieldName: 'name', label: $t('tg.name') },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: [
          { label: '正常', value: 1 },
          { label: '停用', value: 0 },
        ],
      },
      fieldName: 'status',
      label: $t('tg.status'),
    },
  ],
};

const gridOptions: VxeTableGridOptions<TgTenant> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 80 },
    { field: 'name', title: $t('tg.name'), align: 'left' },
    {
      field: 'status',
      title: $t('tg.status'),
      cellRender: { name: 'CellTag' },
    },
    { field: 'remark', title: $t('tg.remark'), align: 'left' },
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
      width: 160,
      cellRender: {
        attrs: { nameField: 'name', onClick: onActionClick },
        name: 'CellOperation',
        options: ['edit', 'delete'],
      },
    },
  ],
  proxyConfig: {
    ajax: {
      query: async (_, formValues) => await getTgTenantsApi({ ...formValues }),
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

function onActionClick({ code, row }: { code: string; row: TgTenant }) {
  switch (code) {
    case 'delete': {
      deleteTgTenantApi(row.id).then(() => {
        message.success($t('ui.actionMessage.deleteSuccess', [row.name]));
        onRefresh();
      });
      break;
    }
    case 'edit': {
      modalApi.setData(row).open();
      break;
    }
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema,
});

type FormTgTenant = Partial<TgTenant>;

const formData = ref<FormTgTenant>();

const modalTitle = computed(() =>
  formData.value?.id
    ? $t('ui.actionTitle.edit', [$t('tg.tenant')])
    : $t('ui.actionTitle.create', [$t('tg.tenant')]),
);

const [Modal, modalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    modalApi.lock();
    const data = await formApi.getValues<TgTenant>();
    try {
      await (formData.value?.id
        ? updateTgTenantApi(formData.value.id, data)
        : createTgTenantApi(data));
      message.success($t('ui.actionMessage.operationSuccess'));
      await modalApi.close();
      onRefresh();
    } finally {
      modalApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (isOpen) {
      const data = modalApi.getData<FormTgTenant>();
      formApi.resetForm();
      formData.value = data ?? undefined;
      if (data) formApi.setValues(data);
    }
  },
});
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #toolbar-actions>
        <VbenButton @click="() => modalApi.setData(null).open()">
          <MaterialSymbolsAdd class="size-5" />
          {{ $t('ui.actionTitle.create', [$t('tg.tenant')]) }}
        </VbenButton>
      </template>
    </Grid>
    <Modal :title="modalTitle">
      <Form />
    </Modal>
  </Page>
</template>
