<script setup lang="ts">
import ComparePanel from "../ComparePanel.vue";
import CustomSelect from "../CustomSelect.vue";
import { comparePlatformLabel } from "../../composables/useArchiveCompare";
import { displayVersionLabel } from "../../domain-presentation";
import type { ArchiveDomain, VersionSummary } from "../../types";

defineProps<{
  domainId: string;
  selectedVersion: string;
  selectedDisplayVersion: string;
  compareDomains: ArchiveDomain[];
  compareBaseVersion: string;
  compareBaseDisplayVersion: string;
  compareBaseOptions: VersionSummary[];
  compareScope: "artifacts" | "files";
}>();

const emit = defineEmits<{
  (e: "switch-domain", domain: ArchiveDomain): void;
  (e: "update-base", version: string): void;
}>();
</script>

<template>
  <div class="compare-shell">
    <div class="compare-toolbar">
      <div v-if="compareDomains.length > 1" class="compare-platform-field">
        <span>对比平台</span>
        <div class="compare-platform-tabs" role="tablist" aria-label="对比平台选择">
          <button
            v-for="item in compareDomains"
            :key="item.id"
            type="button"
            class="compare-platform-tab"
            :class="{ active: item.id === domainId }"
            @click="emit('switch-domain', item)"
          >
            {{ comparePlatformLabel(item) }}
          </button>
        </div>
      </div>
      <div v-if="compareBaseVersion" class="compare-base-field">
        <span>基准版本</span>
        <CustomSelect
          :model-value="compareBaseVersion"
          :options="compareBaseOptions.map((item) => ({ label: displayVersionLabel(item.version, item.attributes), value: item.version }))"
          size="small"
          @change="emit('update-base', String($event))"
        />
      </div>
      <div v-if="compareBaseVersion" class="compare-range-field">
        <span>对比范围</span>
        <strong>{{ compareBaseDisplayVersion }} → {{ selectedDisplayVersion }}</strong>
      </div>
      <p>{{ compareScope === 'files' ? '逐个比对两个版本的文件，路径相同但大小或 MD5 不同的算作修改。' : '逐个比对两个版本的下载包，列出新增、删除和有改动的包。这里只对比大小和校验值，下载链接请到对应页面查看。' }}</p>
    </div>
    <ComparePanel
      v-if="compareBaseVersion"
      :domain-id="domainId"
      :from-version="compareBaseVersion"
      :to-version="selectedVersion"
      :compare-scope="compareScope"
    />
    <div v-else class="empty">当前版本没有可用的对比基准。</div>
  </div>
</template>
