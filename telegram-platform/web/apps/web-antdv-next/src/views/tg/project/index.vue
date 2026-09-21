<script lang="ts" setup>
import type { VbenFormProps, VbenFormSchema } from '@vben/common-ui';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { TgProject } from '#/api/tg';

import { computed, ref } from 'vue';

import { Page, useVbenModal, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';
import { $t } from '@vben/locales';

import { message } from 'antdv-next';

import { useVbenForm, z } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  createTgProjectApi,
  deleteTgProjectApi,
  getTgProjectsApi,
  getTgTenantsApi,
  updateTgProjectApi,
} from '#/api/tg';

const tenantOptions = ref<{ label: string; value: number }[]>([]);

async function loadTenants() {
  const rows = await getTgTenantsApi({ status: 1 });
  tenantOptions.value = rows.map((t) => ({
    label: `${t.name} (${t.id})`,
    value: t.id,
  }));
}

const schema: VbenFormSchema[] = [
  {
    component: 'Select',
    componentProps: { options: tenantOptions, showSearch: true },
    fieldName: 'tenant_id',
    label: $t('tg.tenantId'),
    rules: 'required',
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
        { label: '正常', value: 1 },
        { label: '停用', value: 0 },
      ],
      optionType: 'button',
    },
    defaultValue: 1,
    fieldName: 'status',
    label: $t('tg.status'),
  },
  { component: 'Textarea', fieldName: 'remark', label: $t('tg.remark') },
];

const formOptions: VbenFormProps = {
  collapsed: true,
  showCollapseButton: true,
  submitButtonOptions: { content: $t('common.form.query') },
  schema: [
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () =>
          (await getTgTenantsApi({ status: 1 })).map((t) => ({
            label: t.name,
            value: t.id,
          })),
        resultField: '',
        labelField: 'label',
        valueField: 'value',
      },
      fieldName: 'tenant_id',
      label: $t('tg.tenantId'),
    },
    { component: 'Input', fieldName: 'name', label: $t('tg.name') },
  ],
};

const gridOptions: VxeTableGridOptions<TgProject> = {
  rowConfig: { keyField: 'id' },
  height: 'auto',
  toolbarConfig: { refresh: true, refreshOptions: { code: 'query' } },
  columns: [
    { field: 'id', title: 'ID', width: 80 },
    { field: 'tenant_id', title: $t('tg.tenantId'), width: 100 },
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
      query: async (_, formValues) => await getTgProjectsApi({ ...formValues }),
    },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

function onActionClick({ code, row }: { code: string; row: TgProject }) {
  switch (code) {
    case 'delete': {
      deleteTgProjectApi(row.id).then(() => {
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

type FormTgProject = Partial<TgProject>;

const formData = ref<FormTgProject>();

const modalTitle = computed(() =>
  formData.value?.id
    ? $t('ui.actionTitle.edit', [$t('tg.project')])
    : $t('ui.actionTitle.create', [$t('tg.project')]),
);

const [Modal, modalApi] = useVbenModal({
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    modalApi.lock();
    const data = await formApi.getValues<TgProject>();
    try {
      await (formData.value?.id
        ? updateTgProjectApi(formData.value.id, data)
        : createTgProjectApi(data));
      message.success($t('ui.actionMessage.operationSuccess'));
      await modalApi.close();
      onRefresh();
    } finally {
      modalApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (isOpen) {
      const data = modalApi.getData<FormTgProject>();
      formApi.resetForm();
      formData.value = data ?? undefined;
      if (data) formApi.setValues(data);
    }
  },
});

loadTenants();
</script>

<template>
  <Page auto-content-height>
    <Grid>
      <template #toolbar-actions>
        <VbenButton @click="() => modalApi.setData(null).open()">
          <MaterialSymbolsAdd class="size-5" />
          {{ $t('ui.actionTitle.create', [$t('tg.project')]) }}
        </VbenButton>
      </template>
    </Grid>
    <Modal :title="modalTitle">
      <Form />
    </Modal>
  </Page>
</template>
