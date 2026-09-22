<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag, NSpace, useMessage, useDialog } from 'naive-ui';
import { fetchDeliveries, fetchDelivery, retryDelivery, cancelDelivery } from '@/service/api';

defineOptions({ name: 'TgDelivery' });

const message = useMessage();
const dialog = useDialog();
const loading = ref(false);
const rows = ref<Api.Tg.DeliveryJob[]>([]);
const statusFilter = ref<string | null>(null);

const showDetail = ref(false);
const detail = ref<Api.Tg.DeliveryJob | null>(null);

async function load() {
  loading.value = true;
  const { data } = await fetchDeliveries(statusFilter.value ? { status: statusFilter.value } : {});
  if (data) rows.value = data;
  loading.value = false;
}

async function openDetail(id: string) {
  const { data } = await fetchDelivery(id);
  if (data) {
    detail.value = data;
    showDetail.value = true;
  }
}

function act(row: Api.Tg.DeliveryJob, kind: 'retry' | 'cancel') {
  dialog.warning({
    title: kind === 'retry' ? '重试投递' : '取消投递',
    content: `job ${row.id.slice(0, 8)}(${row.status})`,
    positiveText: '确认',
    negativeText: '取消',
    onPositiveClick: async () => {
      const fn = kind === 'retry' ? retryDelivery : cancelDelivery;
      const { error } = await fn(row.id);
      if (!error) {
        message.success('已执行');
        await load();
      }
    }
  });
}

const statusType: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  succeeded: 'success',
  ready: 'info',
  in_flight: 'warning',
  retry_scheduled: 'warning',
  failed_permanent: 'error',
  dead_letter: 'error',
  cancelled: 'default',
  gated_approval: 'warning'
};

const columns = [
  { title: 'JOB', key: 'id', render: (r: Api.Tg.DeliveryJob) => r.id.slice(0, 8) },
  { title: '类型', key: 'kind' },
  { title: '模式', key: 'mode' },
  { title: '源', key: 'src', render: (r: Api.Tg.DeliveryJob) => `${r.source_chat_id}:${r.source_message_id}` },
  { title: '目标', key: 'target_chat_id' },
  {
    title: '状态',
    key: 'status',
    render: (r: Api.Tg.DeliveryJob) => h(NTag, { type: statusType[r.status] || 'default', size: 'small' }, { default: () => r.status })
  },
  { title: '尝试', key: 'attempt_count', width: 70 },
  { title: '错误', key: 'last_error_class', render: (r: Api.Tg.DeliveryJob) => r.last_error_class || '-' },
  {
    title: '操作',
    key: 'ops',
    width: 200,
    render: (r: Api.Tg.DeliveryJob) =>
      h(NSpace, {}, () => [
        h(NButton, { size: 'small', onClick: () => openDetail(r.id) }, { default: () => '明细' }),
        h(NButton, { size: 'small', disabled: !['failed_permanent', 'dead_letter', 'cancelled'].includes(r.status), onClick: () => act(r, 'retry') }, { default: () => '重试' }),
        h(NButton, { size: 'small', disabled: ['succeeded', 'cancelled', 'dead_letter'].includes(r.status), onClick: () => act(r, 'cancel') }, { default: () => '取消' })
      ])
  }
];

const attemptColumns = [
  { title: '#', key: 'attempt_no', width: 50 },
  { title: 'worker代', key: 'worker_generation' },
  { title: '开始', key: 'started_at' },
  { title: '结束', key: 'finished_at' },
  {
    title: '结果',
    key: 'result_status',
    render: (r: Api.Tg.DeliveryAttempt) => h(NTag, { size: 'small', type: r.result_status === 'success' ? 'success' : 'error' }, { default: () => r.result_status || '-' })
  },
  { title: '错误分类', key: 'error_class', render: (r: Api.Tg.DeliveryAttempt) => r.error_class || '-' }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">投递任务</h2>
      <NSpace>
        <NSelect
          v-model:value="statusFilter"
          clearable
          placeholder="按状态筛选"
          class="w-200px"
          :options="['ready', 'in_flight', 'retry_scheduled', 'gated_approval', 'succeeded', 'failed_permanent', 'dead_letter', 'cancelled'].map(s => ({ label: s, value: s }))"
          @update:value="load"
        />
        <NButton @click="load">刷新</NButton>
      </NSpace>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.DeliveryJob) => r.id" />

    <NModal v-model:show="showDetail" preset="card" :title="`投递 ${detail?.id?.slice(0, 8)} 明细`" class="w-720px">
      <NDescriptions bordered :column="2" size="small" class="mb-12px">
        <NDescriptionsItem label="job">{{ detail?.id }}</NDescriptionsItem>
        <NDescriptionsItem label="规则">{{ detail?.rule_id }} v{{ detail?.rule_version }}</NDescriptionsItem>
        <NDescriptionsItem label="route">{{ detail?.route_id }}</NDescriptionsItem>
        <NDescriptionsItem label="scope">{{ detail?.source_scope }}</NDescriptionsItem>
      </NDescriptions>
      <NDataTable :columns="attemptColumns" :data="detail?.attempts || []" size="small" />
    </NModal>
  </div>
</template>
