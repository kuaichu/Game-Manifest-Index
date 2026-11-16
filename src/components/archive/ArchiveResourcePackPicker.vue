<script setup lang="ts">
import { computed } from "vue";
import { formatBytes } from "../../domain-presentation";
import type { ResourcePacks } from "../../types";

const props = defineProps<{ resourcePacks: ResourcePacks; selected: string }>();
const emit = defineEmits<{ (e: "select", identity: string): void }>();

const PACK_LABELS: Record<string, string> = { common: "公共包", sd: "SD 画质包", hd: "HD 画质包", uhd: "UHD 画质包" };

const bundleSummary = computed(() => props.resourcePacks.bundles.map((item) => `${item.name} ${formatBytes(item.size)}`).join(" · "));
</script>

<template>
  <div class="resource-pack-picker">
    <div class="cfb-identity-chips" role="group" aria-label="资源包选择">
      <button
        v-for="item in resourcePacks.packs"
        :key="item.identity"
        type="button"
        class="cfb-chip"
        :class="{ active: selected === item.identity }"
        :aria-pressed="selected === item.identity"
        @click="emit('select', item.identity)"
      >
        <span class="cfb-chip-dot"></span>
        <span>{{ PACK_LABELS[item.pack] || item.pack.toUpperCase() }}</span>
        <b>{{ formatBytes(item.size) }}</b>
      </button>
    </div>
    <p v-if="bundleSummary" class="resource-pack-bundles dim-text">安装组合：{{ bundleSummary }}（公共包 + 对应画质包）</p>
  </div>
</template>
