<script setup lang="ts">
import type { AdminOperationJob } from "../../types";

defineProps<{
  loading: boolean;
  running: boolean;
  job: AdminOperationJob | null;
  scopeText: string;
  progressPercent: number;
  currentGameLabel: string;
}>();

const emit = defineEmits<{
  start: [];
  cancel: [];
}>();
</script>

<template>
  <button
    class="admin-btn full-width"
    :class="running ? 'danger' : 'primary'"
    type="button"
    :disabled="loading || job?.status === 'cancelling'"
    @click="running ? emit('cancel') : emit('start')"
  >
    <span>{{ job?.status === 'cancelling' ? '正在取消，等待当前请求结束…' : running ? '■ 取消当前运维任务' : '▶ 启动运维任务' }}</span>
  </button>

  <div v-if="job" class="probe-progress-box">
    <div class="op-games-toolbar">
      <strong>{{ job.phase === 'discover' ? '查找新版本' : job.phase === 'probe' ? '历史版本探活' : '准备中' }} · {{ scopeText }}</strong>
      <span class="text-mono">{{ job.completed }} / {{ job.total }} · {{ progressPercent }}%</span>
    </div>
    <progress :value="job.completed" :max="Math.max(1, job.total)" style="width: 100%;"></progress>
    <div class="text-muted" style="font-size: 12px;">
      当前阶段 {{ job.phase_completed }} / {{ job.phase_total }}
      <template v-if="job.current?.game_id">
        · {{ currentGameLabel }}
        <span v-if="job.current.version" class="text-mono"> v{{ job.current.version }}</span>
      </template>
      · 成功 {{ job.succeeded }} · 失败 {{ job.failed }}
    </div>
  </div>
</template>
