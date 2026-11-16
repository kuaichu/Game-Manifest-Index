<script setup lang="ts">
import VersionPicker from "../VersionPicker.vue";
import { domainModeLabel } from "../../domain-presentation";
import type { ArchiveDomain, VersionSummary } from "../../types";

export interface VisibleArchiveMode {
  domain: ArchiveDomain;
  capability: string;
}

defineProps<{
  versions: VersionSummary[];
  selectedVersion: string;
  domain: ArchiveDomain | null;
  domainId: string;
  mode: string;
  visibleModes: VisibleArchiveMode[];
  controlStripDensity: string;
  searchableMode: boolean;
  query: string;
  suppressAvailabilityPresentation: boolean;
}>();

const emit = defineEmits<{
  (e: "select-version", version: string): void;
  (e: "select-mode", domain: ArchiveDomain, capability: string): void;
  (e: "update:query", value: string): void;
}>();
</script>

<template>
  <section class="control-strip" :class="controlStripDensity">
    <VersionPicker
      :versions="versions"
      :model-value="selectedVersion"
      :domain="domain"
      :mode="mode"
      :label-override="mode === 'legacy' ? '候选线索' : undefined"
      :show-availability="mode !== 'files' && !suppressAvailabilityPresentation"
      @select="emit('select-version', $event)"
    />
    <div class="mode-field">
      <div class="mode-tabs" :class="{ 'mode-tabs-grid': visibleModes.length === 6 }" role="tablist" aria-label="数据视图">
        <button
          v-for="item in visibleModes"
          :key="`${item.domain.id}:${item.capability}`"
          class="mode-tab"
          :class="{
            active: item.capability === 'compare'
              ? mode === 'compare'
              : (item.domain.id === domainId && item.capability === mode)
          }"
          @click="emit('select-mode', item.domain, item.capability)"
        >
          {{ domainModeLabel(item.domain, item.capability) }}
        </button>
      </div>
    </div>
    <label v-if="searchableMode" class="search-box">
      <span>搜索</span>
      <div class="search-input-wrap">
        <input
          :value="query"
          placeholder="文件名 / MD5 / URL"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        />
        <button
          v-if="query"
          type="button"
          class="search-clear-btn"
          aria-label="清除搜索"
          title="清除搜索"
          @click.prevent="emit('update:query', '')"
        >
          ✕
        </button>
      </div>
    </label>
  </section>
</template>
