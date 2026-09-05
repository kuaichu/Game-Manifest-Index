<script setup lang="ts">
import { computed, toRef, toRefs } from "vue";
import CustomSelect from "../CustomSelect.vue";
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
  domains,
  games,
  selectedDomainId,
  newDomain,
  loading,
  catalogMutations,
  searchQuery,
  gameFilter,
  resolveGameIcon,
  useFallbackIcon,
} = toRefs(props);

const emit = defineEmits<{
  (event: "select-domain", id: string): void;
  (event: "start-domain"): void;
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
const domainGameOptions = computed(() => [
  { label: "🌟 全部游戏 (" + props.domains.length + " 个模块)", value: "all" },
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
  { key: "packages", label: "packages 完整包", icon: "📦", desc: "完整游戏客户端离线分卷/压缩包" },
  { key: "files", label: "files 散文件", icon: "📄", desc: "分块离散文件及清单直链" },
  { key: "patches", label: "patches 补丁", icon: "🔄", desc: "游戏小版本增量与差分补丁" },
  { key: "chunks", label: "chunks 块存储", icon: "🧩", desc: "Chunk 流式分块与哈希元数据" },
  { key: "apk", label: "apk 安装包", icon: "📱", desc: "移动端官方原版与渠道安装包" },
  { key: "resources", label: "resources 资源", icon: "🎨", desc: "游戏客户端运行时资源与扩展包" },
  { key: "archive", label: "archive 归档", icon: "🗄️", desc: "全部历史版本数据全量归档浏览" },
];

function domainKindIcon(kind: string): string {
  if (kind === "apk") return "📱";
  if (kind === "chunks") return "🧩";
  if (kind === "patches") return "🔄";
  if (kind === "files") return "📄";
  if (kind === "resources") return "🎨";
  if (kind === "mixed") return "🔀";
  return "📦";
}

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

function updateSearchQuery(event: Event): void {
  emit("update:search-query", (event.target as HTMLInputElement).value);
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

function preventEnterSubmit(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && target.tagName === "INPUT") event.preventDefault();
}
</script>

<template>
        <section class="admin-master-detail domain-workspace">
          <!-- 左侧索引栏 -->
          <aside class="admin-list-pane domain-list-pane">
            <div class="pane-header">
              <div class="pane-title">
                <span class="pane-kicker">MODULES</span>
                <strong>{{ filteredDomains.length }} 个数据分发模块</strong>
              </div>
              <button v-if="catalogMutations" class="admin-btn primary small create-module-btn" type="button" @click="startDomain">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>新增模块</span>
              </button>
            </div>

            <!-- 游戏级联选择器 -->
            <div class="pane-game-select">
              <div class="pane-select-header">
                <span class="select-label">筛选游戏范围</span>
                <span class="game-badge-chip">{{ gameFilter === 'all' ? '全部游戏' : (games.find(g => g.id === gameFilter)?.name || '全部') }}</span>
              </div>
              <CustomSelect
                :model-value="gameFilter"
                :options="domainGameOptions"
                size="small"
                @change="updateGameFilter($event)"
              />
            </div>

            <div class="pane-search">
              <div class="search-input-wrapper">
                <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8"/>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input
                  :value="searchQuery"
                  @input="updateSearchQuery"
                  class="admin-input search-styled"
                  placeholder="搜索游戏、模块 ID 或类型…"
                  type="search"
                />
              </div>
            </div>

            <div class="pane-scroll-list">
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
              <div v-if="!filteredDomains.length" class="admin-empty-state">
                <div class="empty-icon">📂</div>
                <span>未找到匹配的数据模块</span>
                <span>当前目录为只读</span>
              </div>
            </div>
          </aside>

          <!-- 右侧卡片化编辑器 -->
          <form v-if="catalogMutations" class="admin-form-pane domain-form-pane" @keydown.enter="preventEnterSubmit" @submit.prevent="saveDomain">
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
                  <span v-else class="hero-kind-icon">{{ domainKindIcon(domainDraft.kind) }}</span>
                </div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row">
                    <span class="kicker-tag">{{ newDomain ? 'NEW DISTRIBUTION MODULE' : 'DISTRIBUTION MODULE' }}</span>
                    <span class="hero-state-pill" :class="{ off: !domainDraft.is_enabled }">
                      <span class="state-dot"></span>
                      <span>{{ domainDraft.is_enabled ? '前台公开展示中' : '前台已隐藏停用' }}</span>
                    </span>
                  </div>
                  <div class="hero-title-row">
                    <h2>{{ newDomain ? '创建新数据模块' : domainDraft.id }}</h2>
                    <span v-if="!newDomain" class="hero-game-badge">
                      {{ currentDomainGameName }} · {{ domainDraft.platform }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 上半部 2 列网格：1. 基础身份 (左) + 2. 数据驱动与能力 (右) -->
            <div class="domain-cards-grid">
              <!-- 块 1: 基础身份 -->
              <div class="form-section-card domain-card block-identity">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🏷️</span>
                    <div>
                      <div class="section-card-title">1. 基础身份</div>
                      <p class="section-card-subtitle">回答：这个模块是谁，归谁，属于什么类型</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">IDENTITY</span>
                  </div>
                </div>

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
                      <span class="id-prefix-icon">{{ newDomain ? '✏️' : '🔒' }}</span>
                      <input
                        :value="domainDraft.id"
                        @input="updateTextField('id', $event)"
                        class="admin-input text-mono id-input"
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

                  <!-- 模块主类型 (Kind) -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">模块主类型 (Kind) <b class="text-rose">*</b></span>
                      <span class="field-badge-tip">当前选定: <b>{{ domainDraft.kind }}</b></span>
                    </div>
                    <div class="kind-selector-row">
                      <button
                        v-for="k in [
                          { key: 'packages', label: '完整包 packages', icon: '📦' },
                          { key: 'apk', label: '官方安装包 apk', icon: '📱' },
                          { key: 'chunks', label: 'Chunk 块存储', icon: '🧩' },
                          { key: 'patches', label: '增量补丁 patches', icon: '🔄' },
                          { key: 'files', label: '散文件 files', icon: '📄' },
                          { key: 'resources', label: '热更资源 resources', icon: '🎨' },
                          { key: 'mixed', label: '混合分发 mixed', icon: '🔀' },
                        ]"
                        :key="k.key"
                        type="button"
                        class="kind-chip"
                        :class="{ active: domainDraft.kind === k.key }"
                        @click="setKind(k.key)"
                      >
                        <span class="chip-icon">{{ k.icon }}</span>
                        <span class="chip-label">{{ k.label }}</span>
                      </button>
                    </div>
                  </div>

                  <!-- 平台 (Platform) -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">平台 (Platform) <b class="text-rose">*</b></span>
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
                        :value="domainDraft.platform"
                        @input="updateTextField('platform', $event)"
                        class="admin-input platform-input"
                        required
                        placeholder="Windows / Android / iOS / 全平台"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 块 2: 数据驱动与能力 -->
              <div class="form-section-card domain-card block-driver">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">⚙️</span>
                    <div>
                      <div class="section-card-title">2. 数据驱动与能力</div>
                      <p class="section-card-subtitle">回答：这个模块靠什么适配，提供什么能力</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">DRIVER & CAPABILITIES</span>
                  </div>
                </div>

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
                          v-for="a in ['hoyo', 'wuwa', 'arknights', 'endfield', 'android', 'patchersdk', 'generic']"
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
                        :value="domainDraft.adapter"
                        @input="updateTextField('adapter', $event)"
                        class="admin-input text-mono adapter-input"
                        required
                        placeholder="hoyo / wuwa / arknights / generic"
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
                          <span class="cap-icon">{{ cap.icon }}</span>
                          <span class="cap-key">{{ cap.key }}</span>
                          <span class="cap-check-dot"></span>
                        </div>
                        <span class="cap-desc">{{ cap.desc }}</span>
                      </button>
                    </div>
                  </div>

                  <!-- 底层标识字符串 -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">底层契约配置串 (Capabilities)</span>
                    </div>
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
                </div>
              </div>
            </div>

            <!-- 下半部卡片：3. 展示与发布 -->
            <div class="form-section-card domain-card block-publish">
              <div class="section-card-header">
                <div class="section-header-left">
                  <span class="section-icon">🚀</span>
                  <div>
                    <div class="section-card-title">3. 展示与发布</div>
                    <p class="section-card-subtitle">回答：这个模块在前台怎么显示，是否启用，怎么发布</p>
                  </div>
                </div>
                <div class="section-header-badge">
                  <span class="block-tag-pill">PUBLISH & OPERATIONS</span>
                </div>
              </div>

              <!-- 展示与发布 Bento 网格 -->
              <div class="publish-bento-grid">
                <!-- 1. 显示排序与权重 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台显示排序 (sort_order)</span>
                    <span class="sort-tag-val">权重: <b>#{{ domainDraft.sort_order ?? 0 }}</b></span>
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
                    <span class="cell-label">前台公开展示状态</span>
                  </div>
                  <div class="visibility-toggle-card mini" :class="{ enabled: domainDraft.is_enabled }">
                    <div class="vis-info">
                      <span class="vis-icon">{{ domainDraft.is_enabled ? '🟢' : '⚪' }}</span>
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

                <!-- 3. 入库版本数与版本管理入口 -->
                <div class="publish-bento-cell version-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">版本内容库</span>
                  </div>
                  <div class="version-portal-box">
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
                </div>
              </div>

              <!-- 4. 保存 / 还原与危险删除操作栏 -->
              <div class="publish-actions-row">
                <div class="actions-left">
                  <button
                    v-if="!newDomain && domainDraft.id"
                    type="button"
                    class="admin-btn danger outline"
                    :title="currentDomainObj && currentDomainObj.version_count > 0 ? '仅无版本的空模块可删除' : '彻底删除此空模块'"
                    @click="removeDomain"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    <span>删除空模块</span>
                  </button>
                </div>

                <div class="actions-right">
                  <button
                    v-if="!newDomain"
                    type="button"
                    class="admin-btn secondary"
                    :disabled="loading"
                    @click="revertDomain"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                      <path d="M3 3v5h5"/>
                    </svg>
                    <span>还原配置</span>
                  </button>

                  <button
                    class="admin-btn primary domain-save-btn"
                    type="submit"
                    :disabled="loading || !domainDraft.id"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                      <polyline points="17 21 17 13 7 13 7 21"/>
                      <polyline points="7 3 7 8 15 8"/>
                    </svg>
                    <span>{{ loading ? '保存中…' : (newDomain ? '立即创建数据模块' : '保存模块配置') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
          <div v-else class="admin-form-pane domain-form-pane">
            <div class="domain-hero-banner">
              <div class="hero-identity">
                <div class="hero-icon-container"><span class="hero-kind-icon">{{ domainKindIcon(domainDraft.kind) }}</span></div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row"><span class="kicker-tag">READ-ONLY CATALOG</span></div>
                  <div class="hero-title-row"><h2>{{ domainDraft.id || '未选择数据模块' }}</h2></div>
                </div>
              </div>
            </div>
            <div class="admin-alert info">
              数据模块目录由现有 canonical 数据和适配器能力投影生成；后端尚未提供创建、编辑或删除能力。
            </div>
            <div v-if="domainDraft.id" class="form-section-card">
              <div class="section-card-title">模块信息</div>
              <div class="admin-field-grid compact-3col">
                <div class="admin-field"><span class="field-label">所属游戏</span><strong>{{ currentDomainGameName }}</strong></div>
                <div class="admin-field"><span class="field-label">平台 / 类型</span><strong>{{ domainDraft.platform }} / {{ domainDraft.kind }}</strong></div>
                <div class="admin-field"><span class="field-label">能力</span><code>{{ domainDraft.capabilities || '—' }}</code></div>
                <div class="admin-field"><span class="field-label">适配器</span><code>{{ domainDraft.adapter || '—' }}</code></div>
                <div class="admin-field"><span class="field-label">版本数</span><strong>{{ currentDomainObj?.version_count ?? 0 }}</strong></div>
              </div>
              <div class="form-actions-bar">
                <div class="actions-left"><span>目录配置不可在当前控制台修改</span></div>
                <div class="actions-right">
                  <button class="admin-btn primary" type="button" @click="openContent(domainDraft.id)">查看版本</button>
                </div>
              </div>
            </div>
          </div>
        </section>
</template>
