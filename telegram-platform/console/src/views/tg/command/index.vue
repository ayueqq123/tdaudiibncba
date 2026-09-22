<script setup lang="ts">
import { onMounted, ref, h } from 'vue';
import { NButton, NTag, NSpace, useMessage } from 'naive-ui';
import { fetchRuntimeCommands, issueRuntimeCommand, fetchTgAccounts } from '@/service/api';

defineOptions({ name: 'TgCommand' });

const message = useMessage();
const loading = ref(false);
const rows = ref<Api.Tg.RuntimeCommand[]>([]);
const accounts = ref<Api.Tg.Account[]>([]);

const issueForm = ref<{ account_id: number | null; type: Api.Tg.RuntimeCommandType; payloadText: string }>({
  account_id: null,
  type: 'SyncChats',
  payloadText: ''
});
const issuing = ref(false);

const types: Api.Tg.RuntimeCommandType[] = ['StartAccount', 'StopAccount', 'ReloadConfig', 'SyncChats', 'ReconcileSource', 'CancelJob'];

async function load() {
  loading.value = true;
  const [{ data: cmds }, { data: acc }] = await Promise.all([fetchRuntimeCommands(), fetchTgAccounts()]);
  if (cmds) rows.value = cmds;
  if (acc) accounts.value = acc;
  loading.value = false;
}

async function issue() {
  const f = issueForm.value;
  if (!f.account_id) {
    message.warning('请选择账号');
    return;
  }
  let payload: Record<string, any> | undefined;
  if (f.payloadText.trim()) {
    try {
      payload = JSON.parse(f.payloadText);
    } catch {
      message.error('payload 必须是合法 JSON');
      return;
    }
  }
  issuing.value = true;
  const { error } = await issueRuntimeCommand(f.account_id, {
    type: f.type,
    payload,
    dedup_key: `console-${f.account_id}-${f.type}-${Date.now()}`
  });
  issuing.value = false;
  if (!error) {
    message.success('命令已下发');
    await load();
  }
}

const statusType: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  pending: 'warning',
  delivered: 'info',
  acked: 'success',
  failed: 'error',
  expired: 'default'
};

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '类型', key: 'type', render: (r: Api.Tg.RuntimeCommand) => h(NTag, { size: 'small', type: 'info' }, { default: () => r.type }) },
  {
    title: '账号',
    key: 'account_id',
    render: (r: Api.Tg.RuntimeCommand) => accounts.value.find(a => a.id === r.account_id)?.phone || `#${r.account_id}`
  },
  {
    title: '状态',
    key: 'status',
    render: (r: Api.Tg.RuntimeCommand) => h(NTag, { type: statusType[r.status] || 'default', size: 'small' }, { default: () => r.status })
  },
  { title: '结果', key: 'result', ellipsis: { tooltip: true }, render: (r: Api.Tg.RuntimeCommand) => r.result || '-' },
  { title: 'ack时间', key: 'acked_at', render: (r: Api.Tg.RuntimeCommand) => r.acked_at?.slice(0, 19).replace('T', ' ') || '-' },
  { title: '下发时间', key: 'created_time', render: (r: Api.Tg.RuntimeCommand) => r.created_time?.slice(0, 19).replace('T', ' ') }
];

onMounted(load);
</script>

<template>
  <div class="p-16px">
    <div class="mb-16px flex items-center justify-between">
      <h2 class="text-18px font-600">运行时命令</h2>
      <NButton @click="load">刷新</NButton>
    </div>

    <NCard class="mb-16px" title="下发命令">
      <div class="flex flex-wrap items-end gap-12px">
        <NSelect
          v-model:value="issueForm.account_id"
          placeholder="账号"
          class="w-200px"
          :options="accounts.map(a => ({ label: a.phone || String(a.telegram_user_id || a.id), value: a.id }))"
        />
        <NSelect v-model:value="issueForm.type" class="w-200px" :options="types.map(t => ({ label: t, value: t }))" />
        <NInput v-model:value="issueForm.payloadText" placeholder="payload JSON(可选)" class="w-320px" />
        <NButton type="primary" :loading="issuing" @click="issue">下发</NButton>
      </div>
    </NCard>

    <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(r: Api.Tg.RuntimeCommand) => r.id" />
  </div>
</template>
