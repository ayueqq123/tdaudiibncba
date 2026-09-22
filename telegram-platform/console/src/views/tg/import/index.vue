<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag } from 'naive-ui';
import { fetchImportBatches, fetchImportBatch } from '@/service/api';

defineOptions({ name: 'TgImport' });

const loading = ref(false);
const rows = ref<Api.Tg.ImportBatch[]>([]);
const detail = ref<Api.Tg.ImportBatch | null>(null);
const showDetail = ref(false);

async function load() {
  loading.value = true;
  const { data } = await fetchImportBatches();
  if (data) rows.value = data;
  loading.value = false;
}

async function openDetail(id: number) {
  const { data } = await fetchImportBatch(id);
  if (data) {
    detail.value = data;
    showDetail.value = true;
  }
}

const gradeType: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  verified: 'success',
  unverified: 'warning',
  duplicate: 'info',
  invalid: 'error',
  dead: 'error'
};

const columns = [
  { title: '批次', key: 'id', width: 70 },
  { title: '租户', key: 'tenant_id' },
  { title: '项目', key: 'project_id' },
  { title: '总数', key: 'total', render: (r: Api.Tg.ImportBatch) => r.total ?? '-' },
  { title: '状态', key: 'status', render: (r: Api.Tg.ImportBatch) => h(NTag, { size: 'small' }, { default: () => r.status }) },
  { title: '时间', key: 'created_time' },
  {
    title: '操作',
    key: 'ops',
    width: 100,
    render: (r: Api.Tg.ImportBatch) => h(NButton, { size: 'small', onClick: () => openDetail(r.id) }, { default: () => '明细' })
  }
];

const itemColumns = [
  { title: '手机号', key: 'phone', render: (r: Api.Tg.ImportBatchItem) => r.phone || '-' },
  { title: 'TG UID', key: 'telegram_user_id' },
  {
    title: '分级',
    key: 'grade',
    render: (r: Api.Tg.ImportBatchItem) => h(NTag, { type: gradeType[r.grade] || 'default', size: 'small' }, { default: () => r.grade })
  },
  { title: '原因', key: 'reason', render: (r: Api.Tg.ImportBatchItem) => r.reason || '-' }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">Session 导入批次</h2>
      <NButton @click="load">刷新</NButton>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.ImportBatch) => r.id" />

    <NModal v-model:show="showDetail" preset="card" :title="`批次 #${detail?.id} 明细`" class="w-720px">
      <NDataTable :columns="itemColumns" :data="detail?.results || []" size="small" />
    </NModal>
  </div>
</template>
