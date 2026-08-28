<script setup lang="ts">
import { computed } from "vue";
import type { AvailabilityCurrent } from "../types";

const props = defineProps<{ value: AvailabilityCurrent | null }>();
const evidenceStatus = computed(() => props.value?.evidence_status || "no_evidence");
const label = computed(() => {
  const value = props.value;
  if (!value || evidenceStatus.value === "no_evidence") return "无证据";
  if (evidenceStatus.value === "stale") return "证据已陈旧";
  if (evidenceStatus.value === "expired") return "签名已过期";
  if (value.source_kind === "live_probe" && value.reason === "probe_failed") return "探测失败";
  if (evidenceStatus.value === "unverified") return "未验证";
  if (value.source_kind === "live_probe" && value.state === "unknown") return "探测未判定";
  if (value.state === "unknown") return "未探测";
  return { available: "可用", unavailable: "失效", unknown: "未判定" }[value.state];
});
</script>

<template>
  <span class="availability" :data-state="value?.state || 'unknown'" :data-evidence-status="evidenceStatus" :title="value ? `${evidenceStatus} · ${value.reason} · ${value.confidence}` : 'no_evidence'">
    {{ label }}
  </span>
</template>
