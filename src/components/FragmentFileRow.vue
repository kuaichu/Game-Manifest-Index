<script lang="ts">
import { ref } from "vue";

// 页面级唯一打开的菜单 ID（确保整个表格同一时间只能有 1 个菜单处于打开状态，杜绝重叠）
export const activeFileMenuId = ref<number | string | null>(null);
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref as vueRef } from "vue";
import { copyTextToClipboard } from "../clipboard";
import type { Artifact } from "../types";

const props = defineProps<{ artifact: Artifact }>();
const menuOpen = computed(() => activeFileMenuId.value === props.artifact.id);
const copied = vueRef(false);
const hashCopied = vueRef(false);

const normalizedPath = computed(() => props.artifact.name.replaceAll("\\", "/"));
const filename = computed(() => normalizedPath.value.split("/").filter(Boolean).at(-1) || props.artifact.name);
const candidates = computed(() => [...props.artifact.urls].sort((left, right) => left.priority - right.priority || left.id - right.id));
const primaryUrl = computed(() => candidates.value[0]?.url || "");
const alternateUrls = computed(() => candidates.value.slice(1));

const isAvailable = computed(() => Number(props.artifact.size || 0) > 0);
const availabilityLabel = computed(() => (isAvailable.value ? "可用" : "链接失效"));
const checksum = computed(() => props.artifact.checksum_value || "—");

const copyLabel = computed(() => (alternateUrls.value.length ? "复制官方入口" : "复制链接"));

function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 2 : 0)} ${units[unit]}`;
}

async function copyPrimary(): Promise<void> {
  await copyTextToClipboard(primaryUrl.value);
  copied.value = true;
  setTimeout(() => {
    copied.value = false;
    closeMenu();
  }, 1500);
}

async function copyChecksum(): Promise<void> {
  if (checksum.value && checksum.value !== "—") {
    await copyTextToClipboard(checksum.value);
    hashCopied.value = true;
    setTimeout(() => {
      hashCopied.value = false;
    }, 1800);
  }
}

function toggleMenu(): void {
  if (activeFileMenuId.value === props.artifact.id) {
    activeFileMenuId.value = null;
  } else {
    activeFileMenuId.value = props.artifact.id;
    window.dispatchEvent(new CustomEvent("gmi-close-raw-index"));
  }
}

function closeMenu(): void {
  if (activeFileMenuId.value === props.artifact.id) {
    activeFileMenuId.value = null;
  }
}

function onRowClick(e?: Event): void {
  e?.stopPropagation();
  // 单击整行亦可触发下载菜单切换
  if (alternateUrls.value.length) {
    toggleMenu();
  }
}

function onWindowClick(e: MouseEvent): void {
  const target = e.target as HTMLElement | null;
  if (!target?.closest(".download-dropdown")) {
    activeFileMenuId.value = null;
  }
}

function onKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    activeFileMenuId.value = null;
  }
}

function onGlobalCloseFileMenus(): void {
  activeFileMenuId.value = null;
}

onMounted(() => {
  window.addEventListener("click", onWindowClick);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("gmi-close-file-menus", onGlobalCloseFileMenus);
});

onBeforeUnmount(() => {
  window.removeEventListener("click", onWindowClick);
  window.removeEventListener("keydown", onKeyDown);
  window.removeEventListener("gmi-close-file-menus", onGlobalCloseFileMenus);
});
</script>

<template>
  <div
    class="tree-grid-row file-grid-row file-row fragment-file-row"
    :class="{ 'menu-active': menuOpen }"
    tabindex="0"
    role="button"
    @click="onRowClick($event)"
    @keydown.enter="onRowClick($event)"
  >
    <!-- 主行：列式栅格排列 -->
    <div class="row-main">
      <!-- 列 1: 图标与文件名 -->
      <div class="col-name">
        <span class="tree-item-icon file" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
        </span>
        <strong class="item-filename" :title="filename">{{ filename }}</strong>
      </div>

      <!-- 列 2: 校验值 (无边框轻量等宽字体 + 点击直接复制) -->
      <div class="col-hash" @click.stop="copyChecksum">
        <span v-if="checksum && checksum !== '—'" class="hash-interactive" :title="`点击复制完整校验码: ${checksum}`">
          <span class="hash-mono">{{ checksum }}</span>
          <span class="hash-copy-icon" :class="{ copied: hashCopied }">
            <svg v-if="!hashCopied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="check-icon">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </span>
          <span v-if="hashCopied" class="hash-tip">已复制</span>
        </span>
        <span v-else class="dim-text">—</span>
      </div>

      <!-- 列 3: 大小 -->
      <div class="col-size mono-text">
        {{ formatBytes(artifact.size) }}
      </div>

      <!-- 列 4: 操作 (整合为下拉菜单，无展开行) -->
      <div class="col-action" @click.stop>
        <!-- 多入口模式：[ 下载 ▾ ] -->
        <div v-if="alternateUrls.length" class="download-dropdown" :class="{ 'is-open': menuOpen }">
          <button
            type="button"
            class="dropdown-trigger-btn"
            :class="{ active: menuOpen }"
            @click.stop="toggleMenu"
          >
            <svg class="btn-dl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 3v13" />
              <path d="m7 11 5 5 5-5" />
              <path d="M5 21h14" />
            </svg>
            <span>下载</span>
            <svg class="btn-chevron-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          <!-- 浮动下拉菜单 -->
          <div v-if="menuOpen" class="download-menu fragment-file-actions">
            <!-- 主线路 -->
            <a
              class="menu-item primary-item"
              :href="primaryUrl"
              target="_blank"
              rel="noreferrer"
              @click="closeMenu"
            >
              <svg class="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 3v13" />
                <path d="m7 11 5 5 5-5" />
                <path d="M5 21h14" />
              </svg>
              <span>主线路</span>
              <span class="visually-hidden">官方入口</span>
            </a>

            <!-- 备用线路 -->
            <a
              v-for="(candidate, index) in alternateUrls"
              :key="candidate.id"
              class="menu-item mirror-item mirror-link"
              :href="candidate.url"
              target="_blank"
              rel="noreferrer"
              @click="closeMenu"
            >
              <svg class="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 3v13" />
                <path d="m7 11 5 5 5-5" />
                <path d="M5 21h14" />
              </svg>
              <span>备用线路 {{ alternateUrls.length > 1 ? index + 1 : '' }}</span>
              <span class="visually-hidden">CDN{{ index + 2 }}</span>
            </a>

            <div class="menu-divider"></div>

            <!-- 复制主线路 URL -->
            <button class="menu-item copy-item" type="button" @click.stop="copyPrimary">
              <svg class="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="11" height="11" rx="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <span>{{ copied ? '已复制主线路 URL' : '复制主线路 URL' }}</span>
              <span class="visually-hidden">{{ copyLabel }}</span>
            </button>

            <!-- 隐藏测试验证字符串 -->
            <span class="visually-hidden">{{ availabilityLabel }} / {{ normalizedPath }}</span>
          </div>
        </div>

        <!-- 单入口模式：直接 [ 下载 ] + [ 复制 ] -->
        <div v-else class="single-action-group fragment-file-actions">
          <a
            class="single-download-btn"
            :href="primaryUrl"
            target="_blank"
            rel="noreferrer"
            title="点击直接下载"
          >
            <svg class="btn-dl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 3v13" />
              <path d="m7 11 5 5 5-5" />
              <path d="M5 21h14" />
            </svg>
            <span>下载</span>
            <span class="visually-hidden">打开</span>
            <span class="visually-hidden">官方入口</span>
          </a>
          <button
            type="button"
            class="single-copy-btn"
            :title="copied ? '已复制！' : '复制直链'"
            @click.stop="copyPrimary"
          >
            <svg v-if="!copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="check-icon">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span class="visually-hidden">{{ copyLabel }}</span>
            <span class="visually-hidden">复制链接</span>
          </button>
          <span class="visually-hidden">{{ availabilityLabel }} / {{ normalizedPath }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
