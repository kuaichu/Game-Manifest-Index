<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import "../styles/admin.css";
import { ApiError, adminApi } from "../api";
import { adminUiCapabilities } from "../admin-ui-capabilities";
import { gameIcons } from "../game-icons";
import AdminGameCatalog from "../components/admin/AdminGameCatalog.vue";
import AdminDomainCatalog from "../components/admin/AdminDomainCatalog.vue";
import AdminContentPanel from "../components/admin/AdminContentPanel.vue";
import AdminProbePanel from "../components/admin/AdminProbePanel.vue";
import AdminConfirmDialog, {
  type ConfirmDialogRequest,
} from "../components/admin/AdminConfirmDialog.vue";
import AdminLoginView from "../components/admin/AdminLoginView.vue";
import AdminRail from "../components/admin/AdminRail.vue";
import type { AdminShell, AdminTab as Tab } from "../composables/admin-shell";
import { useAdminContent } from "../composables/useAdminContent";
import { useAdminOperations } from "../composables/useAdminOperations";
import { useAdminProbe } from "../composables/useAdminProbe";
import { useAvailabilityInvalidation } from "../composables/useAvailabilityInvalidation";
import type {
  AdminCatalog,
  AdminDomain,
  AdminSyncStatus,
} from "../types";

const TOKEN_STORAGE_KEY = "game-manifest-index-web-admin-token-v1";

const router = useRouter();
const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY) || "");
const authenticated = ref(false);
const catalog = ref<AdminCatalog>({ games: [], domains: [] });
const tab = ref<Tab>("games");
const loading = ref(false);
const error = ref("");
const success = ref("");

interface PendingConfirm extends ConfirmDialogRequest {
  resolve: (accepted: boolean) => void;
}

const pendingConfirm = ref<PendingConfirm | null>(null);

function askConfirm(
  message: string,
  options: Partial<Omit<ConfirmDialogRequest, "message">> = {},
): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    pendingConfirm.value = {
      title: options.title ?? "请确认操作",
      message,
      confirmLabel: options.confirmLabel ?? "确认",
      cancelLabel: options.cancelLabel ?? "取消",
      tone: options.tone ?? "default",
      resolve,
    };
  });
}

function resolveConfirm(accepted: boolean): void {
  const pending = pendingConfirm.value;
  pendingConfirm.value = null;
  pending?.resolve(accepted);
}

const currentTabMeta = computed(() => {
  switch (tab.value) {
    case "games":
      return {
        title: "游戏入口目录",
        subtitle: "维护游戏入口、图标资源、展示排序与前台可见性",
      };
    case "domains":
      return {
        title: "数据模块目录",
        subtitle: "维护数据模块、适配器契约与版本能力",
      };
    case "content":
      return {
        title: "版本内容控制",
        subtitle: "管理各模块的版本发布、文件分卷、下载直链与元数据",
      };
    case "probe":
      return {
        title: "采集与探活监控",
        subtitle: "监控各模块自动同步任务状态、定时探活与链接可用性",
      };
    default:
      return {
        title: "归档控制台",
        subtitle: "统一游戏文件索引与分发后台管理",
      };
  }
});

const gameSearchQuery = ref("");
const domainSearchQuery = ref("");

const selectedGameId = ref("");
const selectedDomainId = ref("");
const syncStatus = ref<AdminSyncStatus | null>(null);
const newGame = ref(false);
const newDomain = ref(false);

async function copyText(text: string): Promise<void> {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    success.value = `已复制到剪贴板：${text}`;
  } catch {
    error.value = "复制失败，请手动选择复制。";
  }
}

let controller: AbortController | null = null;

const gameDraft = ref({
  id: "",
  name: "",
  sub_name: "",
  platform: "PC",
  icon_source: "",
  is_enabled: true,
  sort_order: 0,
});
const domainDraft = ref({
  id: "",
  game_id: "",
  kind: "packages",
  platform: "Windows",
  capabilities: "packages",
  adapter: "generic",
  is_enabled: true,
  sort_order: 0,
});


const gameDomains = computed(() => catalog.value.domains.filter((item) => item.game_id === selectedGameId.value));

const domainGameFilter = ref<string>("all");

const shell: AdminShell = {
  token,
  authenticated,
  catalog,
  tab,
  loading,
  error,
  success,
  selectedGameId,
  selectedDomainId,
  gameDomains,
  askConfirm,
  withLoading,
  showError,
  selectGame,
  selectDomain,
};

const availability = useAvailabilityInvalidation();
const probe = useAdminProbe(shell);
const ops = useAdminOperations(shell, { probe, availability, refreshAllData });
const content = useAdminContent(shell, { stopProbePolling: probe.stopProbePolling, availability });

const { stopProbePolling, openProbe, loadSyncRunStatus } = probe;
const { stopOperationPolling, resumeAdminOperation } = ops;
const { versions, selectedVersion, loadEditableVersion, openContent, handleGlobalDropdownClick } = content;

async function refreshAllData(): Promise<void> {
  await withLoading(async (signal) => {
    await loadCatalog(signal);
    if (selectedDomainId.value) {
      const response = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = response.items;
      if (selectedVersion.value) {
        await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
      }
    }
    success.value = "数据已全部刷新至最新状态。";
  });
}

function resolveGameIcon(id: string, source?: string): string | undefined {
  const clean = source?.trim();
  if (clean?.startsWith("builtin:")) return gameIcons[clean.slice("builtin:".length)] || gameIcons[id];
  return clean || gameIcons[id];
}

function useFallbackIcon(event: Event, id: string): void {
  const image = event.currentTarget as HTMLImageElement;
  const fallback = gameIcons[id];
  if (fallback && image.src !== fallback) image.src = fallback;
  else image.hidden = true;
}

function abortAndCreate(): AbortController {
  controller?.abort();
  controller = new AbortController();
  return controller;
}

function showError(reason: unknown): void {
  if (reason instanceof DOMException && reason.name === "AbortError") return;
  error.value = reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : String(reason);
  success.value = "";
  if (reason instanceof ApiError && reason.status === 401) authenticated.value = false;
}

async function withLoading(action: (signal: AbortSignal) => Promise<void>): Promise<void> {
  loading.value = true;
  error.value = "";
  success.value = "";
  const request = abortAndCreate();
  try {
    await action(request.signal);
  } catch (reason) {
    showError(reason);
  } finally {
    loading.value = false;
  }
}

async function loadCatalog(signal?: AbortSignal): Promise<void> {
  catalog.value = await adminApi.catalog(token.value.trim(), signal);
  selectedGameId.value = catalog.value.games.some((item) => item.id === selectedGameId.value)
    ? selectedGameId.value
    : catalog.value.games[0]?.id || "";
  selectedDomainId.value = catalog.value.domains.some((item) => item.id === selectedDomainId.value)
    ? selectedDomainId.value
    : gameDomains.value[0]?.id || catalog.value.domains[0]?.id || "";
  if (catalog.value.games.length) selectGame(selectedGameId.value);
}

async function login(): Promise<void> {
  if (!token.value.trim()) {
    error.value = "请输入管理员密码 / Token。";
    return;
  }
  await withLoading(async (signal) => {
    await loadCatalog(signal);
    localStorage.setItem(TOKEN_STORAGE_KEY, token.value.trim());
    authenticated.value = true;
    syncStatus.value = await adminApi.syncStatus(token.value.trim(), signal).catch(() => null);
    await loadSyncRunStatus();
    await resumeAdminOperation();
  });
}

function logout(): void {
  stopProbePolling();
  stopOperationPolling();
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  token.value = "";
  authenticated.value = false;
  catalog.value = { games: [], domains: [] };
  versions.value = [];
  syncStatus.value = null;
}

onMounted(async () => {
  document.title = "管理控制台 | GMI";
  document.addEventListener("click", handleGlobalDropdownClick);
  if (token.value.trim()) {
    await withLoading(async (signal) => {
      await loadCatalog(signal);
      localStorage.setItem(TOKEN_STORAGE_KEY, token.value.trim());
      authenticated.value = true;
      syncStatus.value = await adminApi.syncStatus(token.value.trim(), signal).catch(() => null);
      await loadSyncRunStatus();
      await resumeAdminOperation();
    });
  }
});

function openGames(): void {
  tab.value = "games";
  stopProbePolling();
  selectGame(selectedGameId.value);
}

function selectGame(id: string): void {
  selectedGameId.value = id;
  newGame.value = false;
  const item = catalog.value.games.find((row) => row.id === id);
  if (item) {
    gameDraft.value = {
      id: item.id,
      name: item.name,
      sub_name: item.sub_name,
      platform: item.platform,
      icon_source: item.icon_source,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order ?? 0,
    };
  }
  const available = catalog.value.domains.filter((row) => row.game_id === id);
  if (!available.some((row) => row.id === selectedDomainId.value)) selectedDomainId.value = available[0]?.id || "";
}

function startGame(): void {
  if (!adminUiCapabilities.catalogMutations) return;
  newGame.value = true;
  gameDraft.value = {
    id: "",
    name: "",
    sub_name: "",
    platform: "PC",
    icon_source: "",
    is_enabled: true,
    sort_order: catalog.value.games.length * 10,
  };
}

function cancelCreateGame(): void {
  if (!newGame.value) return;
  newGame.value = false;
  const target = selectedGameId.value || catalog.value.games[0]?.id;
  if (target) {
    selectGame(target);
  } else {
    gameDraft.value = {
      id: "",
      name: "",
      sub_name: "",
      platform: "PC",
      icon_source: "",
      is_enabled: true,
      sort_order: 0,
    };
  }
}


async function saveGame(): Promise<void> {
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启游戏目录写入能力。";
    return;
  }
  const actionText = newGame.value
    ? `确定要创建新游戏【${gameDraft.value.name || gameDraft.value.id}】吗？`
    : `确定要保存游戏【${gameDraft.value.name || gameDraft.value.id}】的配置修改吗？`;
  if (!(await askConfirm(actionText, {
    title: newGame.value ? "创建游戏入口" : "保存游戏配置",
    confirmLabel: newGame.value ? "创建" : "保存",
  })))
    return;

  await withLoading(async (signal) => {
    const payload = { ...gameDraft.value };
    if (newGame.value) await adminApi.createGame(payload, token.value, signal);
    else await adminApi.updateGame(payload.id, payload, token.value, signal);
    await loadCatalog(signal);
    selectGame(payload.id);
    success.value = newGame.value ? "游戏已成功创建。" : "游戏配置已成功保存。";
    newGame.value = false;
  });
}

async function removeGame(): Promise<void> {
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启游戏目录写入能力。";
    return;
  }
  if (
    !newGame.value &&
    !(await askConfirm(
      `确定要彻底删除空游戏【${gameDraft.value.name || gameDraft.value.id}】吗？仅空游戏可删除，此操作不可撤销。`,
      { title: "删除空游戏", confirmLabel: "永久删除", tone: "danger" },
    ))
  )
    return;
  await withLoading(async (signal) => {
    await adminApi.deleteGame(gameDraft.value.id, token.value, signal);
    await loadCatalog(signal);
    success.value = "空游戏已删除。";
  });
}

function revertGameDraft(): void {
  if (newGame.value) {
    startGame();
  } else {
    selectGame(gameDraft.value.id);
  }
  success.value = "已还原游戏配置。";
}

function adjustGameSort(delta: number): void {
  const current = gameDraft.value.sort_order ?? 0;
  gameDraft.value.sort_order = Math.max(0, current + delta);
}

function setGamePlatform(platform: string): void {
  gameDraft.value.platform = platform;
}

function setGameIconPreset(preset: string): void {
  gameDraft.value.icon_source = preset;
}

function openDomainsForGame(gameId: string): void {
  domainGameFilter.value = gameId;
  selectedGameId.value = gameId;
  tab.value = "domains";
  const target = catalog.value.domains.find((item) => item.game_id === gameId);
  if (target) selectDomain(target.id);
  else startDomain();
}

const currentGameDomainCount = computed(() =>
  catalog.value.domains.filter((d) => d.game_id === gameDraft.value.id).length
);

function selectDomain(id: string): void {
  selectedDomainId.value = id;
  newDomain.value = false;
  const item = catalog.value.domains.find((row) => row.id === id);
  if (item) {
    domainDraft.value = {
      id: item.id,
      game_id: item.game_id,
      kind: item.kind,
      platform: item.platform,
      capabilities: item.capabilities.join(", "),
      adapter: item.adapter,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order ?? 0,
    };
  }
}

function startDomain(): void {
  if (!adminUiCapabilities.catalogMutations) return;
  newDomain.value = true;
  const targetGameId = (domainGameFilter.value && domainGameFilter.value !== "all")
    ? domainGameFilter.value
    : (selectedGameId.value || catalog.value.games[0]?.id || "");
  domainDraft.value = {
    id: "",
    game_id: targetGameId,
    kind: "packages",
    platform: "Windows",
    capabilities: "packages",
    adapter: "generic",
    is_enabled: true,
    sort_order: catalog.value.domains.length * 10,
  };
}

function cancelCreateDomain(): void {
  if (!newDomain.value) return;
  newDomain.value = false;
  const target = selectedDomainId.value
    || catalog.value.domains.find((item) => item.id === selectedDomainId.value)?.id
    || catalog.value.domains[0]?.id;
  if (target) {
    selectDomain(target);
    return;
  }
  domainDraft.value = {
    id: "",
    game_id: selectedGameId.value || catalog.value.games[0]?.id || "",
    kind: "packages",
    platform: "Windows",
    capabilities: "packages",
    adapter: "generic",
    is_enabled: true,
    sort_order: 0,
  };
}

function openDomains(): void {
  tab.value = "domains";
  stopProbePolling();
  const target = catalog.value.domains.find((item) => item.id === selectedDomainId.value) || catalog.value.domains[0];
  if (target) selectDomain(target.id);
  else startDomain();
}

function setDomainKind(k: string): void {
  domainDraft.value.kind = k;
  if (!domainDraft.value.capabilities || domainDraft.value.capabilities === "packages") {
    if (k === "apk") domainDraft.value.capabilities = "apk, archive";
    else if (k === "chunks") domainDraft.value.capabilities = "chunks, archive";
    else if (k === "patches") domainDraft.value.capabilities = "patches, archive";
    else if (k === "resources") domainDraft.value.capabilities = "resources, archive";
    else if (k === "files") domainDraft.value.capabilities = "files, archive";
  }
}

function setDomainPlatform(platform: string): void {
  domainDraft.value.platform = platform;
}

function setDomainAdapter(adapter: string): void {
  domainDraft.value.adapter = adapter;
}

function adjustDomainSort(delta: number): void {
  const current = Number(domainDraft.value.sort_order) || 0;
  domainDraft.value.sort_order = Math.max(0, current + delta);
}

function revertDomainDraft(): void {
  if (selectedDomainId.value && !newDomain.value) {
    selectDomain(selectedDomainId.value);
    success.value = "已还原为已保存的模块配置。";
  }
}

function domainPayload(): Partial<AdminDomain> {
  return {
    ...domainDraft.value,
    capabilities: domainDraft.value.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
  };
}

async function saveDomain(): Promise<void> {
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启数据模块写入能力。";
    return;
  }
  const actionText = newDomain.value
    ? `确定要创建新数据模块【${domainDraft.value.id}】吗？`
    : `确定要保存数据模块【${domainDraft.value.id}】的配置修改吗？`;
  if (!(await askConfirm(actionText, {
    title: newDomain.value ? "新建数据模块" : "保存模块配置",
    confirmLabel: newDomain.value ? "新建" : "保存",
  })))
    return;

  await withLoading(async (signal) => {
    const payload = domainPayload();
    if (newDomain.value) await adminApi.createDomain(payload, token.value, signal);
    else await adminApi.updateDomain(payload.id || "", payload, token.value, signal);
    await loadCatalog(signal);
    selectDomain(payload.id || "");
    success.value = newDomain.value ? "数据模块已创建。" : "数据模块配置已保存。";
    newDomain.value = false;
  });
}

async function removeDomain(): Promise<void> {
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启数据模块写入能力。";
    return;
  }
  if (
    !(await askConfirm(
      `确定要彻底删除空模块【${domainDraft.value.id}】吗？仅没有版本和候选记录的空模块可删除，此操作不可撤销。`,
      { title: "删除空模块", confirmLabel: "永久删除", tone: "danger" },
    ))
  )
    return;
  await withLoading(async (signal) => {
    await adminApi.deleteDomain(domainDraft.value.id, token.value, signal);
    await loadCatalog(signal);
    success.value = "空模块已删除。";
  });
}

function openTab(next: Tab): void {
  if (next === "games") {
    openGames();
    return;
  }
  if (next === "domains") {
    openDomains();
    return;
  }
  if (next === "content") {
    void openContent();
    return;
  }
  void openProbe();
}

onBeforeUnmount(() => {
  document.removeEventListener("click", handleGlobalDropdownClick);
  controller?.abort();
  stopProbePolling();
  stopOperationPolling();
});
</script>

<template>
  <div class="admin-app" :class="{ 'is-unauthenticated': !authenticated }">
    <AdminRail
      v-if="authenticated"
      :active-tab="tab"
      @select="openTab"
      @logout="logout"
    />

    <!-- 主工作区 Main Dashboard -->
    <main class="admin-main">
      <AdminLoginView
        v-if="!authenticated"
        v-model="token"
        :error="error"
        :loading="loading"
        @submit="login"
        @back="router.push('/')"
      />

      <!-- 已登录主工作区 -->
      <template v-else>
        <!-- 顶栏 TopBar (仅在登录后展示) -->
        <header class="admin-topbar">
          <div class="topbar-left">
            <div class="topbar-title-group">
              <h1>{{ currentTabMeta.title }}</h1>
              <p class="topbar-sub">{{ currentTabMeta.subtitle }}</p>
            </div>
          </div>
          <div class="admin-header-actions">
            <button class="admin-btn secondary small" type="button" :disabled="loading" @click="refreshAllData">
              <svg class="admin-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
              </svg>
              <span>刷新数据</span>
            </button>
            <button class="admin-btn secondary small" type="button" @click="router.push('/')">
              <svg class="admin-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="19" y1="12" x2="5" y2="12"></line>
                <polyline points="12 19 5 12 12 5"></polyline>
              </svg>
              <span>返回前台</span>
            </button>
          </div>
        </header>
        <!-- 全局通知 Toast / Alert -->
        <div v-if="error" class="admin-alert error">
          <span>{{ error }}</span>
          <button class="alert-close" type="button" @click="error = ''">✕</button>
        </div>
        <div v-if="success" class="admin-alert success">
          <span>{{ success }}</span>
          <button class="alert-close" type="button" @click="success = ''">✕</button>
        </div>

        <!-- 模块 1：游戏入口管理 (Games Master-Detail) -->
        <AdminGameCatalog
          v-if="tab === 'games'"
          :games="catalog.games"
          :selected-game-id="selectedGameId"
          :new-game="newGame"
          :game-draft="gameDraft"
          :game-domains-count="currentGameDomainCount"
          :loading="loading"
          :catalog-mutations="adminUiCapabilities.catalogMutations"
          :search-query="gameSearchQuery"
          :resolve-game-icon="resolveGameIcon"
          :use-fallback-icon="useFallbackIcon"
          @select-game="selectGame"
          @start-game="startGame"
          @cancel-create="cancelCreateGame"
          @save-game="saveGame"
          @remove-game="removeGame"
          @revert-game="revertGameDraft"
          @adjust-sort="adjustGameSort"
          @set-platform="setGamePlatform"
          @set-icon-preset="setGameIconPreset"
          @open-domains="openDomainsForGame"
          @copy-text="copyText"
          @update:game-draft="gameDraft = $event"
          @update:search-query="gameSearchQuery = $event"
        />

        <!-- 模块 2：数据模块管理 (Domains Master-Detail) -->
        <AdminDomainCatalog
          v-if="tab === 'domains'"
          :domains="catalog.domains"
          :games="catalog.games"
          :selected-domain-id="selectedDomainId"
          :new-domain="newDomain"
          :domain-draft="domainDraft"
          :loading="loading"
          :catalog-mutations="adminUiCapabilities.catalogMutations"
          :search-query="domainSearchQuery"
          :game-filter="domainGameFilter"
          :resolve-game-icon="resolveGameIcon"
          :use-fallback-icon="useFallbackIcon"
          @select-domain="selectDomain"
          @start-domain="startDomain"
          @cancel-create="cancelCreateDomain"
          @save-domain="saveDomain"
          @remove-domain="removeDomain"
          @revert-domain="revertDomainDraft"
          @open-content="openContent"
          @copy-text="copyText"
          @set-kind="setDomainKind"
          @set-platform="setDomainPlatform"
          @set-adapter="setDomainAdapter"
          @adjust-sort="adjustDomainSort"
          @update:domain-draft="domainDraft = $event"
          @update:search-query="domainSearchQuery = $event"
          @update:game-filter="domainGameFilter = $event"
        />
        <!-- 模块 3：版本内容管理 (Content Management) -->
        <AdminContentPanel
          v-else-if="tab === 'content'"
          :content="content"
          :loading="loading"
          :selected-game-id="selectedGameId"
          :selected-domain-id="selectedDomainId"
          :game-domains="gameDomains"
          :resolve-game-icon="resolveGameIcon"
        />

        <!-- 模块 4：采集与探活监控中心 (Operations & Probe Console) -->
        <AdminProbePanel
          v-else-if="tab === 'probe'"
          :probe="probe"
          :ops="ops"
          :catalog="catalog"
          :loading="loading"
          :resolve-game-icon="resolveGameIcon"
          :use-fallback-icon="useFallbackIcon"
        />
      </template>
    </main>

    <AdminConfirmDialog :request="pendingConfirm" @resolve="resolveConfirm" />
  </div>
</template>
