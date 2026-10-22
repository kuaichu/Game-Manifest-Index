<script setup lang="ts">
import { computed, toRef, toRefs } from "vue";
import CustomSelect from "../CustomSelect.vue";
import AdminCatalogActions from "./AdminCatalogActions.vue";
import AdminCatalogShell from "./AdminCatalogShell.vue";
import AdminSectionCard from "./AdminSectionCard.vue";
import AdminIcon from "./AdminIcon.vue";
import type { AdminDomain, AdminGame } from "../../types";

interface DomainDraft {
  id: string;
  game_id: string;
  kind: string;
  platform: string;
  capabilities: string;
  adapter: string;
  is_enabled: boolean;
  sort_order: number;
}

const props = defineProps<{
  domains: AdminDomain[];
  games: AdminGame[];
  selectedDomainId: string;
  newDomain: boolean;
  domainDraft: DomainDraft;
  loading: boolean;
  catalogMutations: boolean;
  searchQuery: string;
  gameFilter: string;
  resolveGameIcon: (id: string, source?: string) => string | undefined;
  useFallbackIcon: (event: Event, id: string) => void;
}>();

const {
  games,
  searchQuery,
  gameFilter,
  resolveGameIcon,
  useFallbackIcon,
} = toRefs(props);

const emit = defineEmits<{
  (event: "select-domain", id: string): void;
  (event: "start-domain"): void;
  (event: "cancel-create"): void;
  (event: "save-domain"): void;
  (event: "remove-domain"): void;
  (event: "revert-domain"): void;
  (event: "open-content", id: string): void;
  (event: "copy-text", value: string): void;
  (event: "set-kind", kind: string): void;
  (event: "set-platform", platform: string): void;
  (event: "set-adapter", adapter: string): void;
  (event: "adjust-sort", delta: number): void;
  (event: "update:domain-draft", draft: DomainDraft): void;
  (event: "update:search-query", value: string): void;
  (event: "update:game-filter", value: string): void;
}>();

const domainDraft = toRef(props, "domainDraft");

const platformPresetValues = ["windows", "android", "ios", "web / 全平台", "web"];

const adapterPresetValues = [
  "hoyo",
  "wuwa",
  "perfectworld_patcher",
  "arknights",
  "endfield",
  "android",
  "patchersdk",
  "generic",
];

const adapterIsPreset = computed(() =>
  adapterPresetValues.includes((domainDraft.value.adapter || "").trim().toLowerCase()),
);

const platformIsPreset = computed(() =>
  platformPresetValues.includes(domainDraft.value.platform.trim().toLowerCase()),
);
const domainGameOptions = computed(() => [
  { label: "全部游戏 (" + props.domains.length + " 个模块)", value: "all" },
  ...props.games.map((game) => ({
    label: game.name + " (" + props.domains.filter((domain) => domain.game_id === game.id).length + ")",
    value: game.id,
  })),
]);

const filteredDomains = computed(() => {
  const q = props.searchQuery.trim().toLowerCase();
  let list = props.domains;
  if (props.gameFilter && props.gameFilter !== "all") {
    list = list.filter((domain) => domain.game_id === props.gameFilter);
  }
  if (!q) return list;
  return list.filter((domain) => {
    const game = getDomainGame(domain.game_id);
    const gameName = game ? game.name.toLowerCase() : "";
    return domain.id.toLowerCase().includes(q)
      || domain.kind.toLowerCase().includes(q)
      || domain.platform.toLowerCase().includes(q)
      || domain.adapter.toLowerCase().includes(q)
      || gameName.includes(q);
  });
});

function getDomainGame(gameId: string): AdminGame | null {
  return props.games.find((game) => game.id === gameId) || null;
}

const currentDomainObj = computed(() =>
  props.domains.find((domain) => domain.id === domainDraft.value.id) || null,
);

const currentDomainGameName = computed(() => {
  const gameId = domainDraft.value.game_id || currentDomainObj.value?.game_id;
  return getDomainGame(gameId || "")?.name || "未知游戏";
});

const domainCapabilityOptions = [
  { key: "packages", label: "packages 完整包", desc: "完整游戏客户端离线分卷/压缩包" },
  { key: "files", label: "files 散文件", desc: "分块离散文件及清单直链" },
  { key: "patches", label: "patches 补丁", desc: "游戏小版本增量与差分补丁" },
  { key: "chunks", label: "chunks 块存储", desc: "Chunk 流式分块与哈希元数据" },
  { key: "apk", label: "apk 安装包", desc: "移动端官方原版与渠道安装包" },
  { key: "resources", label: "resources 资源", desc: "游戏客户端运行时资源与扩展包" },
  { key: "archive", label: "archive 归档", desc: "全部历史版本数据全量归档浏览" },
  { key: "compare", label: "compare 对比", desc: "跨版本文件 / 资源差异对比" },
];

const selectedCapabilityLabels = computed(() =>
  domainCapabilityOptions
    .filter((option) => isDomainCapabilityActive(option.key))
    .map((option) => option.label),
);

function updateDraftField<K extends keyof DomainDraft>(key: K, value: DomainDraft[K]): void {
  emit("update:domain-draft", { ...domainDraft.value, [key]: value });
}

function updateTextField(key: keyof DomainDraft, event: Event): void {
  updateDraftField(key, (event.target as HTMLInputElement).value as never);
}

function updateNumberField(key: "sort_order", event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  updateDraftField(key, Number.isFinite(value) ? value : 0);
}

function updateEnabled(event: Event): void {
  updateDraftField("is_enabled", (event.target as HTMLInputElement).checked);
}

function isDomainCapabilityActive(capability: string): boolean {
  return domainDraft.value.capabilities
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .includes(capability.toLowerCase());
}

function toggleDomainCapability(capability: string): void {
  const list = domainDraft.value.capabilities.split(",").map((item) => item.trim()).filter(Boolean);
  const index = list.findIndex((item) => item.toLowerCase() === capability.toLowerCase());
  if (index >= 0) list.splice(index, 1);
  else list.push(capability);
  updateDraftField("capabilities", list.join(", "));
}

function updateGameFilter(value: unknown): void {
  emit("update:game-filter", String(value));
}

function selectDomain(id: string): void { emit("select-domain", id); }
function startDomain(): void { emit("start-domain"); }
function saveDomain(): void { emit("save-domain"); }
function removeDomain(): void { emit("remove-domain"); }
function revertDomain(): void { emit("revert-domain"); }
function openContent(id: string): void { emit("open-content", id); }
function copyText(value: string): void { emit("copy-text", value); }
function setKind(kind: string): void { emit("set-kind", kind); }
function setPlatform(platform: string): void { emit("set-platform", platform); }
function setAdapter(adapter: string): void { emit("set-adapter", adapter); }
function adjustSort(delta: number): void { emit("adjust-sort", delta); }
</script>

<template>
  <AdminCatalogShell
    workspace-class="domain-workspace"
    list-pane-class="domain-list-pane"
    form-pane-class="domain-form-pane"
    kicker="MODULES"
    :count-label="`${filteredDomains.length} 个数据分发模块`"
    create-label="新增模块"
    :catalog-mutations="catalogMutations"
    :search-query="searchQuery"
    search-placeholder="搜索游戏、模块 ID 或类型…"
    :item-count="filteredDomains.length"
    empty-icon=""
    empty-title="未找到匹配的数据模块"
    empty-hint="可点击上方「新增模块」创建入口"
    @start="startDomain"
    @submit="saveDomain"
    @update:search-query="emit('update:search-query', $event)"
  >
    <!-- 游戏级联选择器 -->
    <template #filters>
      <div class="pane-game-select">
        <CustomSelect
          :model-value="gameFilter"
          :options="domainGameOptions"
          size="small"
          @change="updateGameFilter($event)"
        />
      </div>
    </template>

    <button
      v-for="item in filteredDomains"
      :key="item.id"
      class="admin-list-item domain-item"
      :class="{ active: item.id === selectedDomainId && !newDomain }"
      type="button"
      @click="selectDomain(item.id)"
    >
      <!-- 真实游戏图标容器 (替代 emoji 占位) -->
      <div class="item-domain-icon-box">
        <img
          v-if="getDomainGame(item.game_id) && resolveGameIcon(item.game_id, getDomainGame(item.game_id)?.icon_source)"
          :class="{ 'endfield-icon': item.game_id === 'endfield' }"
          :src="resolveGameIcon(item.game_id, getDomainGame(item.game_id)?.icon_source)"
          :alt="getDomainGame(item.game_id)?.name || item.id"
          @error="useFallbackIcon($event, item.game_id)"
          class="domain-game-avatar"
        />
        <div v-else class="domain-fallback-icon">
          {{ (getDomainGame(item.game_id)?.name || item.id).slice(0, 1).toUpperCase() }}
        </div>
        <span class="status-indicator" :class="{ off: !item.is_enabled }" :title="item.is_enabled ? '正常展示中' : '已隐藏停用'"></span>
      </div>
      <div class="item-info">
        <div class="item-primary-row">
          <strong class="item-name">{{ getDomainGame(item.game_id)?.name || item.id }}</strong>
          <span class="version-count-pill">{{ item.version_count }} 版本</span>
        </div>
        <div class="item-secondary-row">
          <code class="item-id-tag">{{ item.id }}</code>
          <span class="item-kind-pill" :class="item.kind">{{ item.kind }}</span>
          <span class="item-adapter-pill">{{ item.adapter }}</span>
        </div>
      </div>
      <div class="item-slot-right">
        <span class="item-sort-badge" title="显示排序权重">#{{ item.sort_order }}</span>
      </div>
    </button>

    <template #form>
      <!-- 头部 Hero 横幅 -->
      <div class="domain-hero-banner">
        <div class="hero-identity">
          <div class="hero-icon-container">
            <img
              v-if="domainDraft.game_id && resolveGameIcon(domainDraft.game_id, getDomainGame(domainDraft.game_id)?.icon_source)"
              :class="{ 'endfield-icon': domainDraft.game_id === 'endfield' }"
              :src="resolveGameIcon(domainDraft.game_id, getDomainGame(domainDraft.game_id)?.icon_source)"
              :alt="currentDomainGameName"
              class="hero-game-avatar"
            />
            <AdminIcon v-else class="hero-kind-icon" name="box" :size="26" />
          </div>
          <div class="hero-text-block">
            <div class="hero-title-row">
              <h2>{{ newDomain ? '创建数据模块' : domainDraft.id }}</h2>
              <span v-if="!newDomain" class="hero-game-badge">
                {{ currentDomainGameName }} · {{ domainDraft.platform }}
              </span>
              <span class="hero-state-pill" :class="{ off: !domainDraft.is_enabled }">
                <span class="state-dot"></span>
                <span>{{ domainDraft.is_enabled ? '前台公开展示中' : '前台已隐藏停用' }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 上半部 2 列网格：基础信息 + 驱动与能力 -->
      <div class="domain-cards-grid">
        <!-- 块 1: 基础信息 -->
        <AdminSectionCard
          title="基础信息"
          subtitle="模块唯一主键、所属游戏与主类型，创建后不可更改"
          extra-class="block-identity"
        >
          <div class="admin-field-grid">
            <!-- 模块 ID -->
            <div class="admin-field">
              <div class="field-label-row">
                <span class="field-label">模块 ID <b class="text-rose">*</b></span>
                <button
                  v-if="!newDomain && domainDraft.id"
                  type="button"
                  class="field-action-link"
                  @click="copyText(domainDraft.id)"
                >
                  复制 ID
                </button>
              </div>
              <div class="id-input-container">
                <span v-if="newDomain" class="id-prefix-icon">新建</span>
                <input
                  :value="domainDraft.id"
                  @input="updateTextField('id', $event)"
                  class="admin-input text-mono id-input"
                  :class="{ 'has-prefix': newDomain }"
                  :disabled="!newDomain"
                  required
                  placeholder="例如: hk4e-pc 或 wuwa-android"
                />
              </div>
              <small class="field-tip">
                {{ newDomain ? '推荐: 游戏代号-平台/形态，创建后不可变' : '系统唯一主键，用于数据隔离与目录索引' }}
              </small>
            </div>

            <!-- 所属游戏 -->
            <div class="admin-field">
              <div class="field-label-row">
                <span class="field-label">所属游戏 <b class="text-rose">*</b></span>
              </div>
              <CustomSelect
                :model-value="domainDraft.game_id"
                :options="games.map((g) => ({ label: `${g.name} (${g.id})`, value: g.id }))"
                :disabled="!newDomain"
                placeholder="选择所属游戏"
                @update:model-value="updateDraftField('game_id', String($event))"
              />
              <small class="field-tip">定义该模块关联的具体游戏产品与资产库。</small>
            </div>

            <!-- 模块主类型 -->
            <div class="admin-field full-width">
              <div class="field-label-row">
                <span class="field-label">模块主类型 <b class="text-rose">*</b></span>
              </div>
              <div class="kind-selector-row">
                <button
                  v-for="k in [
                    { key: 'packages', label: '完整包 packages' },
                    { key: 'apk', label: '官方安装包 apk' },
                    { key: 'chunks', label: 'Chunk 块存储' },
                    { key: 'patches', label: '增量补丁 patches' },
                    { key: 'files', label: '散文件 files' },
                    { key: 'resources', label: '热更资源 resources' },
                    { key: 'mixed', label: '混合分发 mixed' },
                  ]"
                  :key="k.key"
                  type="button"
                  class="kind-chip"
                  :class="{ active: domainDraft.kind === k.key }"
                  @click="setKind(k.key)"
                >
                  <span class="chip-label">{{ k.label }}</span>
                </button>
              </div>
            </div>

            <!-- 平台 -->
            <div class="admin-field full-width">
              <div class="field-label-row">
                <span class="field-label">平台 <b class="text-rose">*</b></span>
              </div>
              <div class="platform-input-row">
                <div class="platform-presets">
                  <button
                    v-for="p in ['Windows', 'Android', 'iOS', 'Web / 全平台']"
                    :key="p"
                    type="button"
                    class="preset-pill-btn"
                    :class="{ active: domainDraft.platform.toLowerCase() === p.toLowerCase() || (p.includes('Android') && domainDraft.platform.toLowerCase() === 'android') }"
                    @click="setPlatform(p.includes('Android') ? 'android' : (p.includes('Windows') ? 'Windows' : p))"
                  >
                    {{ p }}
                  </button>
                </div>
                <input
                  v-if="!platformIsPreset"
                  :value="domainDraft.platform"
                  @input="updateTextField('platform', $event)"
                  class="admin-input platform-input"
                  required
                  placeholder="自定义平台标识"
                />
              </div>
            </div>
          </div>

          <!-- 版本内容库：入库版本数 + 版本管理入口，放在基础信息卡底部 -->
          <div class="identity-version-footer">
            <div class="version-stat-group">
              <span class="version-stat-num">{{ currentDomainObj?.version_count ?? 0 }}</span>
              <span class="version-stat-unit">个已入库版本</span>
            </div>
            <button
              v-if="!newDomain && domainDraft.id"
              type="button"
              class="admin-btn primary small version-portal-btn"
              @click="openContent(domainDraft.id)"
            >
              <span>前往版本管理</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
            <span v-else class="version-portal-hint">创建保存后可录入版本</span>
          </div>
        </AdminSectionCard>

        <!-- 块 2: 数据驱动与能力 -->
        <AdminSectionCard
          title="驱动与能力"
          subtitle="适配器决定解析方式，能力决定可维护的内容形态"
          extra-class="block-driver"
        >
          <div class="admin-field-grid">
            <!-- Adapter 源 -->
            <div class="admin-field full-width">
              <div class="field-label-row">
                <span class="field-label">Adapter 源 <b class="text-rose">*</b></span>
                <span class="field-badge-tip">驱动引擎标识</span>
              </div>
              <div class="adapter-input-group">
                <div class="adapter-presets">
                  <button
                    v-for="a in ['hoyo', 'wuwa', 'perfectworld_patcher', 'arknights', 'endfield', 'android', 'patchersdk', 'generic']"
                    :key="a"
                    type="button"
                    class="adapter-chip"
                    :class="{ active: domainDraft.adapter.toLowerCase() === a.toLowerCase() }"
                    @click="setAdapter(a)"
                  >
                    {{ a }}
                  </button>
                </div>
                <input
                  v-if="!adapterIsPreset"
                  :value="domainDraft.adapter"
                  @input="updateTextField('adapter', $event)"
                  class="admin-input text-mono adapter-input"
                  required
                  placeholder="自定义适配器标识"
                />
              </div>
              <small class="field-tip">选择驱动引擎解析下载清单结构与探活校验规则。</small>
            </div>

            <!-- 功能模式 Capabilities (交互式矩阵) -->
            <div class="admin-field full-width">
              <div class="field-label-row">
                <span class="field-label">功能模式 Capabilities <b class="text-rose">*</b></span>
                <span class="field-badge-tip">点击卡片切换能力模式</span>
              </div>

              <!-- 交互式能力标签矩阵 -->
              <div class="capabilities-matrix">
                <button
                  v-for="cap in domainCapabilityOptions"
                  :key="cap.key"
                  type="button"
                  class="capability-toggle-card"
                  :class="{ active: isDomainCapabilityActive(cap.key) }"
                  @click="toggleDomainCapability(cap.key)"
                >
                  <div class="cap-card-top">
                    <span class="cap-key">{{ cap.key }}</span>
                    <span class="cap-check-dot"></span>
                  </div>
                  <span class="cap-desc">{{ cap.desc }}</span>
                </button>
              </div>
              <p class="cap-selection-summary">
                <template v-if="selectedCapabilityLabels.length">
                  已选 {{ selectedCapabilityLabels.length }} 项：{{ selectedCapabilityLabels.join('、') }}
                </template>
                <template v-else>尚未选择能力模式</template>
              </p>
            </div>

            <!-- 底层标识字符串（默认折叠，属于排查用字段） -->
            <details class="admin-advanced">
              <summary>底层契约配置串</summary>
              <div class="admin-field full-width">
                <div class="raw-config-container">
                  <div class="raw-row-item">
                    <span class="raw-prefix-badge">capabilities</span>
                    <input
                      :value="domainDraft.capabilities"
                      @input="updateTextField('capabilities', $event)"
                      class="admin-input text-mono raw-cap-input"
                      placeholder="例如: apk, archive 或 packages, files"
                      required
                    />
                  </div>
                </div>
                <small class="field-tip">底层能力枚举标识串，用于 API 契约协议分发与解析。</small>
              </div>
            </details>
          </div>
        </AdminSectionCard>
      </div>

      <!-- 下半部卡片：3. 展示与发布 -->
      <AdminSectionCard
        title="发布"
        subtitle="控制前台排序与前台可见性"
        extra-class="block-publish"
      >
        <!-- 展示与发布 Bento 网格 -->
        <div class="publish-bento-grid">
          <!-- 1. 显示排序与权重 -->
          <div class="publish-bento-cell">
            <div class="cell-label-row">
              <span class="cell-label">显示排序</span>
            </div>
            <div class="sort-stepper-container">
              <div class="stepper-control">
                <button
                  type="button"
                  class="stepper-btn dec"
                  :disabled="(domainDraft.sort_order ?? 0) <= 0"
                  @click="adjustSort(-5)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                </button>
                <div class="stepper-input-wrap">
                  <input
                    :value="domainDraft.sort_order"
                    @input="updateNumberField('sort_order', $event)"
                    class="stepper-input"
                    type="number"
                    min="0"
                    step="1"
                  />
                </div>
                <button
                  type="button"
                  class="stepper-btn inc"
                  @click="adjustSort(5)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                </button>
              </div>
              <div class="sort-quick-presets">
                <button
                  v-for="s in [0, 10, 20, 30]"
                  :key="s"
                  type="button"
                  class="preset-pill-btn micro"
                  :class="{ active: domainDraft.sort_order === s }"
                  @click="updateDraftField('sort_order', s)"
                >
                  #{{ s }}{{ s === 0 ? ' (置顶)' : '' }}
                </button>
              </div>
            </div>
            <small class="field-tip">数字越小排序越靠前（前台导航标签展示顺序）。</small>
          </div>

          <!-- 2. 是否公开展示 -->
          <div class="publish-bento-cell">
            <div class="cell-label-row">
              <span class="cell-label">前台可见</span>
            </div>
            <div class="visibility-toggle-card mini" :class="{ enabled: domainDraft.is_enabled }">
              <div class="vis-info">
                <span class="vis-icon" :class="domainDraft.is_enabled ? 'is-on' : 'is-off'">●</span>
                <div>
                  <strong>{{ domainDraft.is_enabled ? '前台公开展示中' : '前台已隐藏停用' }}</strong>
                  <p>{{ domainDraft.is_enabled ? '在前台游戏页与导航栏中公开展示。' : '仅管理员可见，对普通访客隐藏。' }}</p>
                </div>
              </div>
              <label class="admin-toggle-label">
                <input :checked="domainDraft.is_enabled" class="admin-toggle-checkbox" type="checkbox" @change="updateEnabled" />
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>
        </div>

        <AdminCatalogActions
          :can-delete="!newDomain && Boolean(domainDraft.id)"
          :delete-title="currentDomainObj && currentDomainObj.version_count > 0 ? '仅无版本的空模块可删除' : '彻底删除此空模块'"
          delete-label="删除空模块"
          :delete-disabled="Boolean(currentDomainObj && currentDomainObj.version_count > 0)"
          :show-revert="!newDomain"
          :cancel-label="newDomain ? '取消新建' : ''"
          :loading="loading"
          :save-disabled="loading || !domainDraft.id"
          :save-label="loading ? '保存中…' : (newDomain ? '立即创建数据模块' : '保存模块配置')"
          @remove="removeDomain"
          @revert="revertDomain"
          @cancel="emit('cancel-create')"
        />
      </AdminSectionCard>
    </template>
  </AdminCatalogShell>
</template>
