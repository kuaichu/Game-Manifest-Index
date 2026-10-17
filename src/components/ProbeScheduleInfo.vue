<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api";
import type { PublicProbeScheduleStatus } from "../types";

defineProps<{ checkedTime: string; globalTime: boolean }>();
const emit = defineEmits<{ refresh: [] }>();
const schedule = ref<PublicProbeScheduleStatus | null>(null);
const loaded = ref(false);
let controller: AbortController | null = null;
let interval: ReturnType<typeof setInterval> | null = null;
let timeout: ReturnType<typeof setTimeout> | null = null;
const statusText = computed(() => {
  const status = schedule.value;
  if (!status) return loaded.value ? "定时检查状态暂不可用" : "正在读取定时检查状态";
  if (status.error) return "定时检查异常";
  if (!status.enabled) return "定时检查未开启";
  if (!status.running) return "定时检查未运行";
  return `每 ${status.interval_hours} 小时检查新版本`;
});
function displayTime(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "暂无记录";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date(value)).reduce((parts, part) => {
    parts[part.type] = part.value;
    return parts;
  }, {} as Record<string, string>);
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}
async function refresh(): Promise<void> {
  controller?.abort();
  if (timeout !== null) clearTimeout(timeout);
  const request = new AbortController();
  controller = request;
  timeout = setTimeout(() => request.abort(), 10000);
  emit("refresh");
  try {
    const result = await api.probeScheduleStatus(request.signal);
    if (controller === request && !request.signal.aborted) schedule.value = result;
  } catch {
    if (controller === request) schedule.value = null;
  } finally {
    if (controller === request) {
      loaded.value = true;
      if (timeout !== null) clearTimeout(timeout);
      timeout = null;
    }
  }
}
onMounted(() => {
  void refresh();
  interval = setInterval(() => { void refresh(); }, 60000);
});
onBeforeUnmount(() => {
  controller?.abort();
  controller = null;
  if (interval !== null) clearInterval(interval);
  if (timeout !== null) clearTimeout(timeout);
});
</script>

<template>
  <div class="probe-schedule-info">
    <div class="probe-schedule-row">
      <span class="probe-schedule-badge" :class="{ 'probe-schedule-error': schedule?.error }">{{ statusText }}</span>
      <span v-if="schedule?.last_started_at" class="probe-schedule-time">最近任务启动：{{ displayTime(schedule.last_started_at) }}</span>
      <span v-if="schedule?.enabled && schedule?.next_run_at" class="probe-schedule-time">下次计划：{{ displayTime(schedule.next_run_at) }}</span>
    </div>
    <div v-if="checkedTime">{{ globalTime ? '全站链接最近实际检测' : '当前页面链接最近实际检测' }}：<b>{{ checkedTime }}</b></div>
    <details class="probe-schedule-help">
      <summary>为什么链接检测时间没有变化？</summary>
      <p v-if="schedule?.mode === 'full'">每轮复查已验证可用的链接；没有新版本时 TG 保持静默。</p>
      <p v-else-if="schedule?.mode === 'normal'">普通模式会跳过 {{ schedule.evidence_ttl_hours }} 小时内已验证可用的链接，因此链接检测时间可能不变；没有新版本时 TG 保持静默。</p>
      <p v-else>链接检测时间记录实际检测，不代表定时任务最近执行时间。</p>
      <p>以上时间均为北京时间。</p>
    </details>
  </div>
</template>

<style scoped>
.probe-schedule-info { display: grid; gap: 8px; max-width: 100%; text-align: center; font-size: 13px; color: var(--muted); line-height: 1.7; overflow-wrap: anywhere; }
.probe-schedule-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 6px 18px; }
.probe-schedule-badge { padding: 2px 9px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel-deep); color: var(--text-secondary); font-size: 12px; }
.probe-schedule-time { color: var(--muted); font-size: 12px; }
.probe-schedule-info b { color: var(--text-secondary); font-weight: 500; }
.probe-schedule-help { color: var(--muted); font-size: 12px; }
.probe-schedule-help summary { width: fit-content; max-width: 100%; margin: 0 auto; padding: 4px 0; cursor: pointer; }
.probe-schedule-help summary:hover { color: var(--text-secondary); }
.probe-schedule-help summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; border-radius: 3px; }
.probe-schedule-info p { max-width: 680px; margin: 4px auto 0; }
.probe-schedule-error { color: #fb7185; }
</style>
