<script setup lang="ts">
import { computed, toRef } from "vue";
import type { AdminGame } from "../../types";

interface GameDraft {
  id: string;
  name: string;
  sub_name: string;
  platform: string;
  icon_source: string;
  is_enabled: boolean;
  sort_order: number;
}

const props = defineProps<{
  games: AdminGame[];
  selectedGameId: string;
  newGame: boolean;
  gameDraft: GameDraft;
  gameDomainsCount: number;
  loading: boolean;
  catalogMutations: boolean;
  searchQuery: string;
  resolveGameIcon: (id: string, source?: string) => string | undefined;
  useFallbackIcon: (event: Event, id: string) => void;
}>();

const emit = defineEmits<{
  (event: "select-game", id: string): void;
  (event: "start-game"): void;
  (event: "save-game"): void;
  (event: "remove-game"): void;
  (event: "revert-game"): void;
  (event: "adjust-sort", delta: number): void;
  (event: "set-platform", platform: string): void;
  (event: "set-icon-preset", preset: string): void;
  (event: "open-domains", gameId: string): void;
  (event: "copy-text", value: string): void;
  (event: "update:game-draft", draft: GameDraft): void;
  (event: "update:search-query", value: string): void;
}>();

const gameDraft = toRef(props, "gameDraft");
const filteredGames = computed(() => {
  const q = props.searchQuery.trim().toLowerCase();
  if (!q) return props.games;
  return props.games.filter(
    (game) => game.name.toLowerCase().includes(q)
      || game.id.toLowerCase().includes(q)
      || (game.sub_name && game.sub_name.toLowerCase().includes(q)),
  );
});

const gameIconPreview = computed(() => props.resolveGameIcon(gameDraft.value.id, gameDraft.value.icon_source));

function preventEnterSubmit(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && target.tagName === "INPUT") event.preventDefault();
}

function updateDraftField<K extends keyof GameDraft>(key: K, value: GameDraft[K]): void {
  emit("update:game-draft", { ...gameDraft.value, [key]: value });
}

function updateTextField(key: keyof GameDraft, event: Event): void {
  updateDraftField(key, (event.target as HTMLInputElement).value as never);
}

function updateNumberField(key: "sort_order", event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  updateDraftField(key, Number.isFinite(value) ? value : 0);
}

function updateEnabled(event: Event): void {
  updateDraftField("is_enabled", (event.target as HTMLInputElement).checked);
}

function updateSearchQuery(event: Event): void {
  emit("update:search-query", (event.target as HTMLInputElement).value);
}

function selectGame(id: string): void { emit("select-game", id); }
function startGame(): void { emit("start-game"); }
function saveGame(): void { emit("save-game"); }
function removeGame(): void { emit("remove-game"); }
function revertGame(): void { emit("revert-game"); }
function adjustSort(delta: number): void { emit("adjust-sort", delta); }
function setPlatform(platform: string): void { emit("set-platform", platform); }
function setIconPreset(preset: string): void { emit("set-icon-preset", preset); }
function openDomains(gameId: string): void { emit("open-domains", gameId); }
function copyText(value: string): void { emit("copy-text", value); }
</script>

<template>
        <section class="admin-master-detail game-workspace">
          <!-- 左侧索引栏 -->
          <aside class="admin-list-pane game-list-pane">
            <div class="pane-header">
              <div class="pane-title">
                <span class="pane-kicker">GAMES</span>
                <strong>{{ filteredGames.length }} 个游戏入口</strong>
              </div>
              <button v-if="catalogMutations" class="admin-btn primary small create-module-btn" type="button" @click="startGame">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>新增游戏</span>
              </button>
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
                  placeholder="搜索游戏名称、ID 或副标题…"
                  type="search"
                />
              </div>
            </div>

            <div class="pane-scroll-list">
              <button
                v-for="item in filteredGames"
                :key="item.id"
                class="admin-list-item game-item"
                :class="{ active: item.id === selectedGameId && !newGame }"
                type="button"
                @click="selectGame(item.id)"
              >
                <div class="item-domain-icon-box">
                  <img
                    v-if="resolveGameIcon(item.id, item.icon_source)"
                    :class="{ 'endfield-icon': item.id === 'endfield' }"
                    :src="resolveGameIcon(item.id, item.icon_source)"
                    :alt="item.name"
                    @error="useFallbackIcon($event, item.id)"
                    class="domain-game-avatar"
                  />
                  <div v-else class="domain-fallback-icon">{{ item.id.slice(0, 1).toUpperCase() }}</div>
                  <span class="status-indicator" :class="{ off: !item.is_enabled }" :title="item.is_enabled ? '正常展示中' : '已隐藏停用'"></span>
                </div>
                <div class="item-info">
                  <div class="item-primary-row">
                    <strong class="item-name">{{ item.name }}</strong>
                    <span class="version-count-pill">{{ item.version_count }} 版本</span>
                  </div>
                  <div class="item-secondary-row">
                    <code class="item-id-tag">{{ item.id }}</code>
                    <span v-if="item.sub_name" class="item-sub-name">{{ item.sub_name }}</span>
                  </div>
                </div>
                <div class="item-slot-right">
                  <span class="item-sort-badge" title="显示排序权重">#{{ item.sort_order }}</span>
                </div>
              </button>
              <div v-if="!filteredGames.length" class="admin-empty-state">
                <div class="empty-icon">🎮</div>
                <span>未找到匹配的游戏入口</span>
                <span>当前目录为只读</span>
              </div>
            </div>
          </aside>

          <!-- 右侧卡片化编辑器 -->
          <form v-if="catalogMutations" class="admin-form-pane game-form-pane" @keydown.enter="preventEnterSubmit" @submit.prevent="saveGame">
            <!-- 头部 Hero 横幅 -->
            <div class="domain-hero-banner game-hero-banner">
              <div class="hero-identity">
                <div class="hero-icon-container">
                  <img
                    v-if="gameIconPreview"
                    :class="{ 'endfield-icon': gameDraft.id === 'endfield' }"
                    :src="gameIconPreview"
                    :alt="gameDraft.name"
                    @error="useFallbackIcon($event, gameDraft.id)"
                    class="hero-game-avatar"
                  />
                  <b v-else class="hero-fallback-letter">{{ gameDraft.id.slice(0, 1).toUpperCase() || '?' }}</b>
                </div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row">
                    <span class="kicker-tag">{{ newGame ? 'NEW GAME ENTRY' : 'GAME IDENTITY' }}</span>
                    <span class="hero-state-pill" :class="{ off: !gameDraft.is_enabled }">
                      <span class="state-dot"></span>
                      <span>{{ gameDraft.is_enabled ? '前台公开展示中' : '前台已停用隐藏' }}</span>
                    </span>
                    <span v-if="!newGame" class="hero-version-pill">
                      {{ gameDomainsCount }} 个关联数据模块
                    </span>
                  </div>
                  <div class="hero-title-row">
                    <h2>{{ newGame ? '创建新游戏入口' : gameDraft.name }}</h2>
                    <span v-if="!newGame" class="hero-game-badge">
                      <code class="tag-code">{{ gameDraft.id }}</code> · {{ gameDraft.sub_name }}
                    </span>
                  </div>
                </div>
              </div>

              <div v-if="!newGame && gameDraft.id" class="hero-action-buttons">
                <button type="button" class="admin-btn secondary small hero-jump-btn" @click="openDomains(gameDraft.id)">
                  <span>管理关联数据模块 ({{ gameDomainsCount }})</span>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </button>
              </div>
            </div>

            <!-- 上半部 2 列网格：1. 基本身份 (左) + 2. 图标与外观资源 (右) -->
            <div class="domain-cards-grid">
              <!-- 块 1: 基本身份标识 -->
              <div class="form-section-card domain-card block-identity">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🏷️</span>
                    <div>
                      <div class="section-card-title">1. 基本身份标识</div>
                      <p class="section-card-subtitle">设置游戏唯一主键代号、中英文显示名称与默认平台</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">IDENTITY</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- 游戏唯一 ID -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">游戏唯一 ID <b class="text-rose">*</b></span>
                      <button
                        v-if="!newGame && gameDraft.id"
                        type="button"
                        class="field-action-link"
                        @click="copyText(gameDraft.id)"
                      >
                        复制 ID
                      </button>
                    </div>
                    <div class="id-input-container">
                      <span class="id-prefix-icon">{{ newGame ? '✏️' : '🔒' }}</span>
                      <input
                        :value="gameDraft.id"
                        @input="updateTextField('id', $event)"
                        class="admin-input text-mono id-input"
                        :disabled="!newGame"
                        required
                        placeholder="例如: hk4e、wuwa 或 arknights"
                      />
                    </div>
                    <small class="field-tip">
                      {{ newGame ? '全局唯一英文/数字小写代号，创建后不可更改' : '系统核心主键，用于资产目录索引与分发模块关联' }}
                    </small>
                  </div>

                  <!-- 默认展示平台 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">默认展示平台 <b class="text-rose">*</b></span>
                    </div>
                    <div class="platform-input-row">
                      <div class="platform-presets">
                        <button
                          v-for="p in ['PC', 'Android', 'iOS', 'Web']"
                          :key="p"
                          type="button"
                          class="preset-pill-btn"
                          :class="{ active: gameDraft.platform.toLowerCase() === p.toLowerCase() }"
                          @click="setPlatform(p)"
                        >
                          {{ p }}
                        </button>
                      </div>
                      <input
                        :value="gameDraft.platform"
                        @input="updateTextField('platform', $event)"
                        class="admin-input platform-input"
                        required
                        placeholder="PC / Android / iOS / Web"
                      />
                    </div>
                  </div>

                  <!-- 中文主名称 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">中文主名称 <b class="text-rose">*</b></span>
                    </div>
                    <input
                      :value="gameDraft.name"
                      @input="updateTextField('name', $event)"
                      class="admin-input"
                      required
                      placeholder="例如: 原神、鸣潮、崩坏：星穹铁道"
                    />
                    <small class="field-tip">前台导航栏、概览卡片及页面标题呈现的核心品牌名称。</small>
                  </div>

                  <!-- 英文 / 副标题 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">英文 / 副标题 <b class="text-rose">*</b></span>
                    </div>
                    <input
                      :value="gameDraft.sub_name"
                      @input="updateTextField('sub_name', $event)"
                      class="admin-input"
                      required
                      placeholder="例如: Genshin Impact 或 Wuthering Waves"
                    />
                    <small class="field-tip">前台英文副标题显示，同时参与搜索匹配索引。</small>
                  </div>
                </div>
              </div>

              <!-- 块 2: 图标与外观资源 -->
              <div class="form-section-card domain-card block-assets">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🎨</span>
                    <div>
                      <div class="section-card-title">2. 图标与外观资源</div>
                      <p class="section-card-subtitle">配置导航与卡片图标解析源，支持内置资源与外部图片</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">ASSETS & ICON</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- 图标实时预览卡片 -->
                  <div class="admin-field full-width">
                    <div class="icon-live-preview-box">
                      <div class="preview-avatar-wrap">
                        <img
                          v-if="gameIconPreview"
                          :class="{ 'endfield-icon': gameDraft.id === 'endfield' }"
                          :src="gameIconPreview"
                          :alt="gameDraft.name"
                          @error="useFallbackIcon($event, gameDraft.id)"
                          class="preview-avatar-img"
                        />
                        <div v-else class="preview-fallback-letter">
                          {{ (gameDraft.name || gameDraft.id).slice(0, 1).toUpperCase() || '?' }}
                        </div>
                      </div>
                      <div class="preview-avatar-meta">
                        <div class="preview-meta-title">图标实时渲染解析</div>
                        <div class="preview-meta-desc">
                          解析结果：<code class="tag-code">{{ gameIconPreview || '默认首字母' }}</code>
                        </div>
                        <div class="icon-quick-presets">
                          <button
                            type="button"
                            class="preset-pill-btn micro"
                            :class="{ active: !gameDraft.icon_source }"
                            @click="setIconPreset('')"
                          >
                            默认内置图标 (留空)
                          </button>
                          <button
                            v-if="gameDraft.id"
                            type="button"
                            class="preset-pill-btn micro"
                            :class="{ active: gameDraft.icon_source === `builtin:${gameDraft.id}` }"
                            @click="setIconPreset(`builtin:${gameDraft.id}`)"
                          >
                            显式指定 builtin:{{ gameDraft.id }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 图标数据源 (Icon Source) 输入框 -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">图标数据源 (Icon Source)</span>
                      <span class="field-badge-tip">留空自动匹配内置同名图标</span>
                    </div>
                    <input
                      :value="gameDraft.icon_source"
                      @input="updateTextField('icon_source', $event)"
                      class="admin-input text-mono"
                      placeholder="例如: builtin:hk4e、/assets/icon.png 或 https://…"
                    />
                    <small class="field-tip">
                      支持 <code>builtin:&lt;id&gt;</code> 内置标识、站内绝对路径（如 <code>/assets/custom.png</code>）或外链 HTTPS 图片地址。
                    </small>
                  </div>
                </div>
              </div>
            </div>

            <!-- 下半部卡片：3. 展示与发布控制台 -->
            <div class="form-section-card domain-card block-publish">
              <div class="section-card-header">
                <div class="section-header-left">
                  <span class="section-icon">🚀</span>
                  <div>
                    <div class="section-card-title">3. 展示与发布控制台</div>
                    <p class="section-card-subtitle">设置前台顶部导航排序优先级、对外可见性与模块维护</p>
                  </div>
                </div>
                <div class="section-header-badge">
                  <span class="block-tag-pill">PUBLISH & OPERATIONS</span>
                </div>
              </div>

              <!-- 展示与发布 Bento 网格 -->
              <div class="publish-bento-grid">
                <!-- 1. 显示排序权重 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台显示排序 (sort_order)</span>
                    <span class="sort-tag-val">权重: <b>#{{ gameDraft.sort_order ?? 0 }}</b></span>
                  </div>
                  <div class="sort-stepper-container">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="(gameDraft.sort_order ?? 0) <= 0"
                        @click="adjustSort(-5)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                        :value="gameDraft.sort_order"
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
                        :class="{ active: gameDraft.sort_order === s }"
                        @click="updateDraftField('sort_order', s)"
                      >
                        #{{ s }}{{ s === 0 ? ' (置顶)' : '' }}
                      </button>
                    </div>
                  </div>
                  <small class="field-tip">数字越小在前台导航栏与首页列表中展示越靠前。</small>
                </div>

                <!-- 2. 前台公开可见性 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台公开可见性</span>
                  </div>
                  <div class="visibility-toggle-card mini" :class="{ enabled: gameDraft.is_enabled }">
                    <div class="vis-info">
                      <span class="vis-icon">{{ gameDraft.is_enabled ? '🟢' : '⚪' }}</span>
                      <div>
                        <strong>{{ gameDraft.is_enabled ? '前台导航公开展示中' : '前台隐藏暂不对外展示' }}</strong>
                        <p>{{ gameDraft.is_enabled ? '普通访客可直接在导航和首页看到该游戏。' : '仅在管理控制台可见，对公众隐藏。' }}</p>
                      </div>
                    </div>
                    <label class="admin-toggle-label">
                      <input :checked="gameDraft.is_enabled" class="admin-toggle-checkbox" type="checkbox" @change="updateEnabled" />
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                </div>

                <!-- 3. 数据模块关联状态 -->
                <div class="publish-bento-cell version-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">关联数据分发模块</span>
                  </div>
                  <div class="version-portal-box">
                    <div class="version-stat-group">
                      <span class="version-stat-num">{{ gameDomainsCount }}</span>
                      <span class="version-stat-unit">个分发模块</span>
                    </div>
                    <button
                      v-if="!newGame && gameDraft.id"
                      type="button"
                      class="admin-btn primary small version-portal-btn"
                      @click="openDomains(gameDraft.id)"
                    >
                      <span>进入模块管理</span>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </button>
                    <span v-else class="version-portal-hint">创建保存后可添加分发模块</span>
                  </div>
                </div>
              </div>

              <!-- 4. 保存 / 还原与危险删除操作栏 -->
              <div class="publish-actions-row">
                <div class="actions-left">
                  <button
                    v-if="!newGame && gameDraft.id"
                    type="button"
                    class="admin-btn danger outline"
                    :title="gameDomainsCount > 0 ? '该游戏下存在数据模块，不可直接删除' : '彻底删除此空游戏入口'"
                    @click="removeGame"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    <span>删除空游戏</span>
                  </button>
                </div>

                <div class="actions-right">
                  <button
                    v-if="!newGame"
                    type="button"
                    class="admin-btn secondary"
                    :disabled="loading"
                    @click="revertGame"
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
                    :disabled="loading || !gameDraft.id"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                      <polyline points="17 21 17 13 7 13 7 21"/>
                      <polyline points="7 3 7 8 15 8"/>
                    </svg>
                    <span>{{ loading ? '保存中…' : (newGame ? '立即创建游戏入口' : '保存游戏设置') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
          <div v-else class="admin-form-pane game-form-pane">
            <div class="domain-hero-banner game-hero-banner">
              <div class="hero-identity">
                <div class="hero-icon-container">
                  <img
                    v-if="gameIconPreview"
                    :src="gameIconPreview"
                    :alt="gameDraft.name"
                    class="hero-game-avatar"
                  />
                  <b v-else class="hero-fallback-letter">{{ gameDraft.id.slice(0, 1).toUpperCase() || '?' }}</b>
                </div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row"><span class="kicker-tag">READ-ONLY CATALOG</span></div>
                  <div class="hero-title-row"><h2>{{ gameDraft.name || '未选择游戏' }}</h2></div>
                </div>
              </div>
            </div>
            <div class="admin-alert info">
              游戏目录由当前 V5 静态注册关系和数据投影生成；后端尚未提供创建、编辑或删除能力。
            </div>
            <div v-if="gameDraft.id" class="form-section-card">
              <div class="section-card-title">目录信息</div>
              <div class="admin-field-grid compact-3col">
                <div class="admin-field"><span class="field-label">游戏 ID</span><code>{{ gameDraft.id }}</code></div>
                <div class="admin-field"><span class="field-label">英文 / 副标题</span><strong>{{ gameDraft.sub_name || '—' }}</strong></div>
                <div class="admin-field"><span class="field-label">当前平台</span><strong>{{ gameDraft.platform || '—' }}</strong></div>
              </div>
              <div class="form-actions-bar">
                <div class="actions-left"><span>{{ gameDomainsCount }} 个关联数据模块</span></div>
                <div class="actions-right">
                  <button class="admin-btn primary" type="button" @click="openDomains(gameDraft.id)">查看关联模块</button>
                </div>
              </div>
            </div>
          </div>
        </section>
</template>
