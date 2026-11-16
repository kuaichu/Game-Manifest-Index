<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { activeFileMenuId } from "../FragmentFileRow.vue";

const props = defineProps<{
  manifestUrl: string;
  baseUrl: string;
}>();

const emit = defineEmits<{
  (e: "copy-url", url: string): void;
}>();

const rawIndexMenuOpen = ref(false);
const copiedManifestUrl = ref(false);
const copiedBaseUrl = ref(false);

const wuwaManifestShort = computed(() => {
  if (!props.manifestUrl) return "indexFile.json";
  try {
    const parsed = new URL(props.manifestUrl);
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    return pathParts.at(-1) || "indexFile.json";
  } catch {
    return "indexFile.json";
  }
});

const wuwaBaseUrlShort = computed(() => {
  if (!props.baseUrl) return "pcdownload-aliyun.../zip/";
  try {
    const parsed = new URL(props.baseUrl);
    const hostPrefix = parsed.hostname.split(".")[0] || "";
    return `${hostPrefix}.../zip/`;
  } catch {
    return ".../zip/";
  }
});

function copyWuwaManifestUrl(): void {
  if (!props.manifestUrl) return;
  emit("copy-url", props.manifestUrl);
  copiedManifestUrl.value = true;
  setTimeout(() => {
    copiedManifestUrl.value = false;
  }, 1800);
}

function copyWuwaBaseUrl(): void {
  if (!props.baseUrl) return;
  emit("copy-url", props.baseUrl);
  copiedBaseUrl.value = true;
  setTimeout(() => {
    copiedBaseUrl.value = false;
  }, 1800);
}

function toggleRawIndexMenu(): void {
  rawIndexMenuOpen.value = !rawIndexMenuOpen.value;
  if (rawIndexMenuOpen.value) {
    activeFileMenuId.value = null;
    window.dispatchEvent(new CustomEvent("gmi-close-file-menus"));
  }
}

function onWindowRawIndexClick(e: MouseEvent): void {
  const target = e.target as HTMLElement | null;
  if (!target?.closest(".raw-manifest-dropdown")) {
    rawIndexMenuOpen.value = false;
  }
}

function onCloseRawIndex(): void {
  rawIndexMenuOpen.value = false;
}

function onWindowKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    rawIndexMenuOpen.value = false;
  }
}

onMounted(() => {
  window.addEventListener("click", onWindowRawIndexClick);
  window.addEventListener("keydown", onWindowKeyDown);
  window.addEventListener("gmi-close-raw-index", onCloseRawIndex);
});

onBeforeUnmount(() => {
  window.removeEventListener("click", onWindowRawIndexClick);
  window.removeEventListener("keydown", onWindowKeyDown);
  window.removeEventListener("gmi-close-raw-index", onCloseRawIndex);
});
</script>

<template>
  <div class="raw-manifest-dropdown">
    <button
      type="button"
      class="tool-button raw-index-btn"
      :class="{ active: rawIndexMenuOpen }"
      @click.stop="toggleRawIndexMenu"
    >
      <span>索引信息</span>
      <svg class="raw-chevron-icon" :class="{ open: rawIndexMenuOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <div v-if="rawIndexMenuOpen" class="raw-index-card" @click.stop>
      <div class="raw-index-card-header">
        <strong>索引信息</strong>
        <span class="raw-index-card-sub">官方 Manifest 索引源</span>
      </div>

      <!-- 清单 URL -->
      <div class="raw-index-item">
        <span class="raw-index-item-label">清单 URL</span>
        <div class="raw-index-item-row">
          <span class="raw-index-item-url" :title="manifestUrl || '暂无'">{{ wuwaManifestShort }}</span>
          <button
            type="button"
            class="raw-index-item-btn"
            :disabled="!manifestUrl"
            @click="copyWuwaManifestUrl"
          >
            {{ copiedManifestUrl ? '已复制' : '复制' }}
          </button>
        </div>
      </div>

      <!-- 资源根目录 -->
      <div class="raw-index-item">
        <span class="raw-index-item-label">资源根目录</span>
        <div class="raw-index-item-row">
          <span class="raw-index-item-url" :title="baseUrl || '暂无'">{{ wuwaBaseUrlShort }}</span>
          <button
            type="button"
            class="raw-index-item-btn"
            :disabled="!baseUrl"
            @click="copyWuwaBaseUrl"
          >
            {{ copiedBaseUrl ? '已复制' : '复制' }}
          </button>
        </div>
      </div>

      <div class="raw-index-divider"></div>

      <!-- 查看原始 JSON -->
      <a
        v-if="manifestUrl"
        class="raw-index-json-link"
        :href="manifestUrl"
        target="_blank"
        rel="noreferrer"
        @click="rawIndexMenuOpen = false"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
        <span>查看原始 JSON</span>
      </a>
    </div>
  </div>
</template>
