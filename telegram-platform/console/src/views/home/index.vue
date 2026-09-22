<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { fetchTgAccounts, fetchDeliveries, fetchApprovals, fetchRuntimeCommands } from '@/service/api';

defineOptions({ name: 'Home' });

const stats = ref({ accounts: 0, running: 0, deliveries: 0, succeeded: 0, pendingApprovals: 0, commands: 0 });

onMounted(async () => {
  const [{ data: acc }, { data: del }, { data: appr }, { data: cmd }] = await Promise.all([
    fetchTgAccounts(),
    fetchDeliveries(),
    fetchApprovals({ status: 'pending' }),
    fetchRuntimeCommands()
  ]);
  if (acc) {
    stats.value.accounts = acc.length;
    stats.value.running = acc.filter(a => a.desired_status === 'running').length;
  }
  if (del) {
    stats.value.deliveries = del.length;
    stats.value.succeeded = del.filter(d => d.status === 'succeeded').length;
  }
  if (appr) stats.value.pendingApprovals = appr.length;
  if (cmd) stats.value.commands = cmd.length;
});
</script>

<template>
  <div class="p-16px">
    <NCard class="mb-16px">
      <h2 class="text-20px font-600">TG 自动化运营平台</h2>
      <p class="mt-8px text-14px op-70">多账号 Userbot · 消息 Clone · AI 群聊 · 审批工作台</p>
    </NCard>
    <NGrid cols="2 s:3 m:4" responsive="screen" :x-gap="16" :y-gap="16">
      <NGi>
        <NCard title="TG 账号">
          <div class="text-28px font-600">{{ stats.running }}/{{ stats.accounts }}</div>
          <div class="op-60">运行中 / 总数</div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="投递任务">
          <div class="text-28px font-600">{{ stats.succeeded }}/{{ stats.deliveries }}</div>
          <div class="op-60">成功 / 总数</div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="待审批">
          <div class="text-28px font-600">{{ stats.pendingApprovals }}</div>
          <div class="op-60">AI 回复候选</div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="运行时命令">
          <div class="text-28px font-600">{{ stats.commands }}</div>
          <div class="op-60">累计下发</div>
        </NCard>
      </NGi>
    </NGrid>
  </div>
</template>
