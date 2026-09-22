<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag, useMessage, useDialog } from 'naive-ui';
import { fetchTgTenants, createTgTenant, deleteTgTenant } from '@/service/api';

defineOptions({ name: 'TgTenant' });

const message = useMessage();
const dialog = useDialog();
const loading = ref(false);
const rows = ref<Api.Tg.Tenant[]>([]);
const showCreate = ref(false);
const form = ref({ name: '', remark: '' });

async function load() {
  loading.value = true;
  const { data } = await fetchTgTenants();
  if (data) rows.value = data;
  loading.value = false;
}

async function doCreate() {
  if (!form.value.name) {
    message.warning('名称必填');
    return;
  }
  const { error } = await createTgTenant({ name: form.value.name, status: 1, remark: form.value.remark || null });
  if (!error) {
    message.success('已创建');
    showCreate.value = false;
    form.value = { name: '', remark: '' };
    await load();
  }
}

function doDelete(r: Api.Tg.Tenant) {
  dialog.warning({
    title: '删除租户',
    content: `删除「${r.name}」?租户下项目/账号需为空`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      const { error } = await deleteTgTenant(r.id);
      if (!error) {
        message.success('已删除');
        await load();
      }
    }
  });
}

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '名称', key: 'name' },
  { title: '状态', key: 'status', render: (r: Api.Tg.Tenant) => h(NTag, { type: r.status === 1 ? 'success' : 'default', size: 'small' }, { default: () => (r.status === 1 ? '启用' : '停用') }) },
  { title: '备注', key: 'remark', render: (r: Api.Tg.Tenant) => r.remark || '-' },
  { title: '创建时间', key: 'created_time', render: (r: Api.Tg.Tenant) => r.created_time?.slice(0, 19).replace('T', ' ') },
  {
    title: '操作',
    key: 'ops',
    width: 100,
    render: (r: Api.Tg.Tenant) => h(NButton, { size: 'small', type: 'error', onClick: () => doDelete(r) }, { default: () => '删除' })
  }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">租户管理</h2>
      <div class="flex gap-12px">
        <NButton type="primary" @click="showCreate = true">新建租户</NButton>
        <NButton @click="load">刷新</NButton>
      </div>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.Tenant) => r.id" />

    <NModal v-model:show="showCreate" preset="card" title="新建租户" class="w-420px">
      <NForm label-placement="left" label-width="60">
        <NFormItem label="名称" required><NInput v-model:value="form.name" /></NFormItem>
        <NFormItem label="备注"><NInput v-model:value="form.remark" /></NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-12px">
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" @click="doCreate">创建</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>
