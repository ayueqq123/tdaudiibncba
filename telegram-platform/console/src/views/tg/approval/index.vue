<script setup lang="ts">
import { computed, onMounted, ref, h } from 'vue';
import { NButton, NTag, NSpace, useMessage } from 'naive-ui';
import { fetchApprovals, fetchCandidates, approveApproval, rejectApproval } from '@/service/api';

defineOptions({ name: 'TgApproval' });

const message = useMessage();
const loading = ref(false);
const rows = ref<Api.Tg.Approval[]>([]);
const candidates = ref<Record<number, Api.Tg.ReplyCandidate>>({});
const statusFilter = ref<string | null>('pending');
const reasonMap = ref<Record<number, string>>({});

const pendingCount = computed(() => rows.value.filter(r => r.status === 'pending').length);

async function load() {
  loading.value = true;
  const [{ data: appr }, { data: cand }] = await Promise.all([
    fetchApprovals(statusFilter.value ? { status: statusFilter.value } : {}),
    fetchCandidates()
  ]);
  if (appr) rows.value = appr;
  if (cand) {
    const m: Record<number, Api.Tg.ReplyCandidate> = {};
    cand.forEach(c => (m[c.id] = c));
    candidates.value = m;
  }
  loading.value = false;
}

async function decide(row: Api.Tg.Approval, kind: 'approve' | 'reject') {
  const cand = candidates.value[row.candidate_id];
  if (!cand) {
    message.error('找不到对应候选,无法决定');
    return;
  }
  const payload = {
    candidate_version: cand.version,
    content_hash: cand.content_hash,
    reason: reasonMap.value[row.id] || undefined
  };
  const fn = kind === 'approve' ? approveApproval : rejectApproval;
  const { error } = await fn(row.id, payload);
  if (!error) {
    message.success(kind === 'approve' ? '已通过(将进入投递队列)' : '已拒绝');
    await load();
  }
}

const statusType: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
  expired: 'default'
};

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '候选', key: 'candidate_id' },
  {
    title: '内容',
    key: 'content',
    ellipsis: { tooltip: true },
    render: (r: Api.Tg.Approval) => candidates.value[r.candidate_id]?.content || '(候选已清理)'
  },
  { title: 'hash', key: 'content_hash', width: 90, render: (r: Api.Tg.Approval) => r.content_hash.slice(0, 8) },
  {
    title: '状态',
    key: 'status',
    render: (r: Api.Tg.Approval) => h(NTag, { type: statusType[r.status] || 'default', size: 'small' }, { default: () => r.status })
  },
  { title: '过期', key: 'expires_at', render: (r: Api.Tg.Approval) => r.expires_at?.slice(0, 19).replace('T', ' ') },
  {
    title: '理由',
    key: 'reason',
    render: (r: Api.Tg.Approval) =>
      h('input', {
        class: 'w-140px rounded-4px border border-#ffffff20 bg-transparent px-8px py-4px text-13px',
        placeholder: '可选理由',
        value: reasonMap.value[r.id] || '',
        onInput: (e: any) => (reasonMap.value[r.id] = e.target.value)
      })
  },
  {
    title: '操作',
    key: 'ops',
    width: 160,
    render: (r: Api.Tg.Approval) =>
      r.status === 'pending'
        ? h(NSpace, {}, () => [
            h(NButton, { size: 'small', type: 'primary', onClick: () => decide(r, 'approve') }, { default: () => '通过' }),
            h(NButton, { size: 'small', type: 'error', onClick: () => decide(r, 'reject') }, { default: () => '拒绝' })
          ])
        : null
  }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">
        AI 回复审批
        <NTag v-if="pendingCount" type="warning" class="ml-8px">{{ pendingCount }} 待审</NTag>
      </h2>
      <NSpace>
        <NSelect
          v-model:value="statusFilter"
          clearable
          placeholder="按状态筛选"
          class="w-160px"
          :options="['pending', 'approved', 'rejected', 'expired'].map(s => ({ label: s, value: s }))"
          @update:value="load"
        />
        <NButton @click="load">刷新</NButton>
      </NSpace>
    </div>
    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.Approval) => r.id" />
  </div>
</template>
