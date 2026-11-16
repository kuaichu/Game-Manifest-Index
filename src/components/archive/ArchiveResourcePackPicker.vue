<script setup lang="ts">
import { computed } from "vue";
import { formatBytes } from "../../domain-presentation";
import type { ResourcePacks } from "../../types";

const props = defineProps<{ resourcePacks: ResourcePacks; selected: string }>();
const emit = defineEmits<{ (e: "select", identity: string): void }>();

const PACK_LABELS: Record<string, string> = { common: "公共包", sd: "SD 画质包", hd: "HD 画质包", uhd: "UHD 画质包" };

const selectedPack = computed(() => props.resourcePacks.packs.find((item) => item.identity === props.selected)?.pack || "");
// A bundle is "related" when it contains the pack being browsed (common belongs to every bundle).
const bundles = computed(() => props.resourcePacks.bundles.map((item) => ({
  ...item,
  related: Boolean(selectedPack.value) && item.packs.includes(selectedPack.value),
})));
</script>

<template>
  <div class="resource-pack-picker">
    <div class="rp-row">
      <span class="rp-label">画质包</span>
      <div class="rp-chips" role="radiogroup" aria-label="选择要浏览的资源包">
        <button
          v-for="item in resourcePacks.packs"
          :key="item.identity"
          type="button"
          role="radio"
          class="rp-chip"
          :class="{ active: selected === item.identity }"
          :aria-checked="selected === item.identity"
          @click="emit('select', item.identity)"
        >
          <span class="rp-dot" aria-hidden="true"></span>
          <span class="rp-name">{{ PACK_LABELS[item.pack] || item.pack.toUpperCase() }}</span>
          <b class="rp-size">{{ formatBytes(item.size) }}</b>
        </button>
      </div>
    </div>
    <p v-if="bundles.length" class="resource-pack-bundles">安装组合：<template v-for="(item, index) in bundles" :key="item.name"><template v-if="index"> · </template><span class="rp-bundle" :class="{ related: item.related }">{{ item.name }} {{ formatBytes(item.size) }}</span></template>（公共包 + 对应画质包）</p>
  </div>
</template>

<style scoped>
.resource-pack-picker {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}

.rp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rp-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.rp-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rp-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-secondary, #cbd5e1);
  font-size: 12.5px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.rp-chip:hover {
  background: rgba(56, 189, 248, 0.08);
  border-color: rgba(56, 189, 248, 0.35);
  color: #f1f5f9;
}

.rp-chip.active {
  background: rgba(56, 189, 248, 0.18);
  border-color: #38bdf8;
  color: #e0f2fe;
  box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.35), 0 0 12px rgba(56, 189, 248, 0.22);
}

.rp-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.25);
}

.rp-chip.active .rp-dot {
  background: #38bdf8;
  box-shadow: 0 0 6px #38bdf8;
}

.rp-size {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
  opacity: 0.7;
}

.rp-chip.active .rp-size {
  color: #7dd3fc;
  opacity: 1;
}

.resource-pack-bundles {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.rp-bundle.related {
  color: #7dd3fc;
  font-weight: 700;
}
</style>
