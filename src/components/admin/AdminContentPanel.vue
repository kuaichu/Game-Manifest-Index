<script setup lang="ts">
import AdminIcon from "./AdminIcon.vue";
import AdminPcArtifactFields from "./AdminPcArtifactFields.vue";
import { formatBytes, formatSyncTime, getFileTimeSourceDescription } from "../../admin-format";
import {
  type EditableArtifactDraft,
  getChecksumSummaryText,
  getDomainFriendlyName,
  isVersionAvailable,
  isVersionUnknown,
  pcArtifactSummaryTags,
  pcArtifactTitle,
  versionHealthClass,
  versionHealthTitle,
} from "../../admin-version-editor";
import type { AdminContent } from "../../composables/useAdminContent";
import type { AdminDomain } from "../../types";

const props = defineProps<{
  content: AdminContent;
  loading: boolean;
  selectedGameId: string;
  selectedDomainId: string;
  gameDomains: AdminDomain[];
  resolveGameIcon: (id: string, source?: string) => string | undefined;
}>();

// The content state lives in AdminView (via useAdminContent) so it survives tab switches.
const {
  selectedVersion,
  versionSearchQuery,
  contentSubTab,
  editableLoaded,
  editableLoading,
  checksumsOpen,
  moreActionsOpen,
  editableDraft,
  createDraft,
  versionDraft,
  isCreateMode,
  selectedDomainSupportsCreateVersion,
  selectedDomainUsesPcEditor,
  selectedDomainSupportsManualVersion,
  selectedDomainGameName,
  selectedGame,
  selectedDomain,
  currentVersionHealth,
  pcArtifactsOverview,
  isUrlChanged,
  dirtyChangesCount,
  isEditableDirty,
  showApkFileCard,
  fileTimeRaw,
  fileTimeInputValue,
  fileTimeLabel,
  fileTimeUnparsable,
  gameDropdownOpen,
  domainDropdownOpen,
  gameDropdownSearch,
  filteredDropdownGames,
  versionFilterState,
  archiveHealthStats,
  filteredVersions,
  groupedVersionList,
  expandedMajorKeys,
  expandedMinorKeys,
  urlProbeMap,
  clearActiveFileTime,
  copyUrl,
  openUrl,
  onFileTimeInput,
  submitVersionForm,
  handleDropdownSelectGame,
  handleDropdownSelectDomain,
  toggleVersionFilter,
  resetVersionFilter,
  toggleMajorGroup,
  toggleMinorGroup,
  preventEnterSubmit,
  addArtifactItem,
  removeArtifactItem,
  addArtifactUrlItem,
  removeArtifactUrlItem,
  handleArtifactUrlChange,
  forceExtractArtifactName,
  switchArtifactsMode,
  formatArtifactsJson,
  probeUrlItem,
  handleActiveArtifactUrlChange,
  forceExtractActiveArtifactName,
  syncArtifactsToJson,
  syncArtifactsJsonForActiveDraft,
  onContentVersionSelect,
  discardChanges,
  toggleVersionVisibility,
  deleteCurrentVersion,
  copyCurrentVersionToCreateDraft,
  resetCreateDraft,
  probeCurrentVersion,
} = props.content;
</script>

<template>
  <section class="admin-content-grid">
    <!-- 顶部数据范围选择条 (宽敞舒适双列选择框) -->
    <div class="content-cascade-bar two-cols">
      <!-- 游戏选择器 -->
      <div class="cascade-item">
        <div class="custom-dropdown-container game-dropdown">
          <button
            class="custom-dropdown-trigger"
            :class="{ active: gameDropdownOpen }"
            type="button"
            @click="gameDropdownOpen = !gameDropdownOpen; domainDropdownOpen = false"
          >
            <div class="trigger-content">
              <img
                v-if="selectedGame && resolveGameIcon(selectedGame.id, selectedGame.icon_source)"
                :src="resolveGameIcon(selectedGame.id, selectedGame.icon_source)"
                class="game-dropdown-icon"
                :class="{ 'endfield-icon': selectedGame.id === 'endfield' }"
                alt=""
              />
              <div v-else class="game-dropdown-icon fallback-icon"><AdminIcon name="game" /></div>
              <div class="trigger-texts">
                <strong class="trigger-title">{{ selectedGame?.name || '选择游戏…' }}</strong>
                <span v-if="selectedGame?.sub_name" class="trigger-subtitle">{{ selectedGame.sub_name }}</span>
              </div>
            </div>
            <span class="dropdown-chevron" :class="{ open: gameDropdownOpen }">▼</span>
          </button>

          <!-- 游戏下拉浮层 -->
          <transition name="dropdown-fade">
            <div v-if="gameDropdownOpen" class="custom-dropdown-menu">
              <div class="dropdown-search-box" @click.stop>
                <input
                  v-model="gameDropdownSearch"
                  class="dropdown-search-input"
                  placeholder="搜索游戏名称 / 代号…"
                  autofocus
                />
                <span v-if="gameDropdownSearch" class="clear-search-btn" @click="gameDropdownSearch = ''">✕</span>
              </div>
              <div class="dropdown-options-scroll">
                <div v-if="filteredDropdownGames.length === 0" class="dropdown-empty-item">
                  无匹配游戏
                </div>
                <button
                  v-for="game in filteredDropdownGames"
                  :key="game.id"
                  class="dropdown-option-item"
                  :class="{ selected: game.id === selectedGameId }"
                  type="button"
                  @click="handleDropdownSelectGame(game.id)"
                >
                  <img
                    v-if="resolveGameIcon(game.id, game.icon_source)"
                    :src="resolveGameIcon(game.id, game.icon_source)"
                    class="option-game-icon"
                    :class="{ 'endfield-icon': game.id === 'endfield' }"
                    alt=""
                  />
                  <div v-else class="option-game-icon fallback-icon"><AdminIcon name="game" /></div>
                  <div class="option-info">
                    <strong class="option-name">{{ game.name }}</strong>
                    <span class="option-sub">{{ game.sub_name || game.id }}</span>
                  </div>
                  <span v-if="game.id === selectedGameId" class="selected-check">✔</span>
                </button>
              </div>
            </div>
          </transition>
        </div>
      </div>

      <!-- 数据模块选择器 (宽敞下拉) -->
      <div class="cascade-item">
        <div class="custom-dropdown-container domain-dropdown">
          <button
            class="custom-dropdown-trigger"
            :class="{ active: domainDropdownOpen }"
            type="button"
            @click="domainDropdownOpen = !domainDropdownOpen; gameDropdownOpen = false"
          >
            <div class="trigger-content">
              <span
                v-if="selectedDomain"
                class="domain-kind-badge"
                :class="selectedDomain.kind"
              >
                {{ selectedDomain.kind.toUpperCase() }}
              </span>
              <div class="trigger-texts">
                <strong class="trigger-title">{{ getDomainFriendlyName(selectedDomain) }}</strong>
                <span v-if="selectedDomain" class="trigger-subtitle">
                  {{ selectedDomain.id }}
                </span>
              </div>
            </div>
            <span class="dropdown-chevron" :class="{ open: domainDropdownOpen }">▼</span>
          </button>

          <!-- 模块下拉浮层 -->
          <transition name="dropdown-fade">
            <div v-if="domainDropdownOpen" class="custom-dropdown-menu">
              <div class="dropdown-options-scroll">
                <div v-if="gameDomains.length === 0" class="dropdown-empty-item">
                  该游戏下暂无数据模块
                </div>
                <button
                  v-for="d in gameDomains"
                  :key="d.id"
                  class="dropdown-option-item domain-option"
                  :class="{ selected: d.id === selectedDomainId }"
                  type="button"
                  @click="handleDropdownSelectDomain(d.id)"
                >
                  <span class="domain-kind-badge" :class="d.kind">{{ d.kind.toUpperCase() }}</span>
                  <div class="option-info">
                    <strong class="option-name">{{ getDomainFriendlyName(d) }}</strong>
                    <span class="option-sub">{{ d.id }} · {{ d.platform }}</span>
                  </div>
                  <span v-if="d.id === selectedDomainId" class="selected-check">✔</span>
                </button>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </div>

    <!-- 顶部全局归档健康条 (可交互一键筛选) -->
    <div class="archive-health-overview-bar">
      <div class="overview-title-group">
        <strong class="overview-game-name">{{ selectedDomainGameName }}</strong>
        <span class="overview-slash">/</span>
        <span class="overview-domain-name">{{ getDomainFriendlyName(selectedDomain) }}</span>
      </div>

      <div class="overview-metrics-group">
        <span class="metric-item">{{ archiveHealthStats.total }} 个版本</span>
        <span class="metric-divider">·</span>
        <span class="metric-item">最新 {{ archiveHealthStats.latest }}</span>
        <span class="metric-divider">·</span>
        <span class="metric-item">{{ archiveHealthStats.available }} 个可用</span>

        <!-- 链接失效状态药丸（可交互筛选） -->
        <button
          v-if="archiveHealthStats.unavailable > 0"
          class="filter-pill-btn danger"
          :class="{ active: versionFilterState === 'unavailable' }"
          type="button"
          :title="versionFilterState === 'unavailable' ? '点击取消筛选' : '点击筛选链接失效版本'"
          @click="toggleVersionFilter('unavailable')"
        >
          ● 链接失效 {{ archiveHealthStats.unavailable }}
        </button>

        <!-- 尚未探活状态药丸（可交互筛选） -->
        <button
          v-if="archiveHealthStats.unknown > 0"
          class="filter-pill-btn warning"
          :class="{ active: versionFilterState === 'unknown' }"
          type="button"
          :title="versionFilterState === 'unknown' ? '点击取消筛选' : '点击筛选尚未探活版本'"
          @click="toggleVersionFilter('unknown')"
        >
          ○ 尚未探活 {{ archiveHealthStats.unknown }}
        </button>

        <!-- 重置筛选提示 -->
        <button
          v-if="versionFilterState !== 'all'"
          class="filter-pill-btn reset"
          type="button"
          title="清除状态筛选并恢复最新可用版本"
          @click="resetVersionFilter"
        >
          ✕ 清除筛选
        </button>
      </div>
    </div>

    <!-- 下方 Master-Detail 双栏布局 -->
    <div class="content-panels-layout">
      <!-- 左侧：精简版 Master 垂直版本列表 -->
      <div class="content-version-master-pane">
        <div class="pane-header">
          <div class="pane-title">
            <span>VERSION LIST</span>
            <strong>版本列表 ({{ filteredVersions.length }})</strong>
          </div>
        </div>

        <!-- 快速检索输入框 -->
        <div class="pane-search">
          <input
            v-model="versionSearchQuery"
            class="admin-input small"
            placeholder="搜索版本号…"
          />
        </div>

        <!-- 独立滚动的版本项列表（分层智能折叠） -->
        <div class="version-master-scroll-list">
          <div v-if="groupedVersionList.length === 0" class="admin-empty-state">
            未找到匹配的版本
          </div>

          <!-- 大版本分组 (Major Group) -->
          <div
            v-for="majorGroup in groupedVersionList"
            :key="majorGroup.majorKey"
            class="version-major-group"
          >
            <!-- 大版本折叠标题栏 -->
            <button
              class="major-group-header"
              :class="{ expanded: expandedMajorKeys.has(majorGroup.majorKey) }"
              type="button"
              @click="toggleMajorGroup(majorGroup.majorKey)"
            >
              <div class="major-title-left">
                <span class="group-chevron" :class="{ open: expandedMajorKeys.has(majorGroup.majorKey) }">▶</span>
                <strong class="major-key-text">{{ majorGroup.majorKey }}</strong>
              </div>
              <div class="major-meta-right">
                <span class="major-count-text">
                  {{ majorGroup.totalCount }} 个版本
                  <template v-if="majorGroup.unavailableCount > 0">
                    <span class="meta-dot">·</span>
                    <span class="text-danger-highlight">{{ majorGroup.unavailableCount }} 个失效</span>
                  </template>
                </span>
              </div>
            </button>

            <!-- 大版本展开容器 -->
            <div
              v-if="expandedMajorKeys.has(majorGroup.majorKey)"
              class="major-group-body"
            >
              <template v-for="entry in majorGroup.entries" :key="entry.type === 'single' ? (entry.item?.version || '') : (entry.group?.minorKey || '')">
                <!-- 情况 A：单版本直接平铺 (避免无意义多层折叠) -->
                <button
                  v-if="entry.type === 'single' && entry.item"
                  class="version-master-item"
                  :class="{ active: entry.item.version === selectedVersion }"
                  type="button"
                  @click="onContentVersionSelect(entry.item.version)"
                >
                  <div class="version-item-top">
                    <div class="version-item-title-row">
                      <span
                        class="version-status-dot"
                        :class="versionHealthClass(entry.item)"
                        :title="versionHealthTitle(entry.item)"
                      ></span>
                      <strong class="version-item-title">{{ entry.item.version }}</strong>
                    </div>
                    <span v-if="!entry.item.is_visible" class="status-pill hidden">已隐藏</span>
                    <span v-else-if="isVersionUnknown(entry.item)" class="status-pill unknown">尚未探活</span>
                    <span v-else-if="!isVersionAvailable(entry.item)" class="status-pill danger">链接不可用</span>
                    <span v-else class="version-time-muted">{{ formatSyncTime(entry.item.source_released_at || entry.item.observed_at) || '未记录时间' }}</span>
                  </div>
                </button>

                <!-- 情况 B：存在多个补丁版本的二级小版本折叠组 -->
                <div
                  v-else-if="entry.type === 'minorGroup' && entry.group"
                  class="version-minor-group"
                >
                  <button
                    class="minor-group-header"
                    :class="{ expanded: expandedMinorKeys.has(entry.group.minorKey) }"
                    type="button"
                    @click="toggleMinorGroup(entry.group.minorKey)"
                  >
                    <div class="minor-title-left">
                      <span class="group-chevron small" :class="{ open: expandedMinorKeys.has(entry.group.minorKey) }">▶</span>
                      <strong class="minor-key-text">{{ entry.group.minorKey }}</strong>
                    </div>
                    <span class="minor-count">{{ entry.group.items.length }} 个补丁</span>
                  </button>

                  <div
                    v-if="expandedMinorKeys.has(entry.group.minorKey)"
                    class="minor-group-body"
                  >
                    <button
                      v-for="subItem in entry.group.items"
                      :key="subItem.version"
                      class="version-master-item sub-item"
                      :class="{ active: subItem.version === selectedVersion }"
                      type="button"
                      @click="onContentVersionSelect(subItem.version)"
                    >
                      <div class="version-item-top">
                        <div class="version-item-title-row">
                          <span
                            class="version-status-dot"
                            :class="versionHealthClass(subItem)"
                            :title="versionHealthTitle(subItem)"
                          ></span>
                          <strong class="version-item-title">{{ subItem.version }}</strong>
                        </div>
                        <span v-if="!subItem.is_visible" class="status-pill hidden">已隐藏</span>
                        <span v-else-if="isVersionUnknown(subItem)" class="status-pill unknown">尚未探活</span>
                        <span v-else-if="!isVersionAvailable(subItem)" class="status-pill danger">链接不可用</span>
                        <span v-else class="version-time-muted">{{ formatSyncTime(subItem.source_released_at || subItem.observed_at) || '未记录时间' }}</span>
                      </div>
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：版本工作台（编辑版本 / 新建版本） -->
      <div v-if="selectedDomainSupportsManualVersion" class="content-work-card">
        <!-- 子功能切换 Tab -->
        <div class="content-sub-tabs">
          <button
            class="sub-tab-btn"
            :class="{ active: contentSubTab === 'edit' }"
            type="button"
            @click="contentSubTab = 'edit'"
          >
            <span>编辑版本</span>
          </button>
          <button
            v-if="selectedDomainSupportsCreateVersion"
            class="sub-tab-btn"
            :class="{ active: contentSubTab === 'create' }"
            type="button"
            @click="contentSubTab = 'create'"
          >
            <span>新建版本</span>
          </button>
        </div>

        <!-- 版本工作台：编辑与新建共用同一套字段与资源编辑器 -->
        <form
          class="version-edit-form"
          :class="{ 'version-create-form': isCreateMode }"
          novalidate
          @keydown.enter="preventEnterSubmit"
          @submit.prevent="submitVersionForm"
        >
          <!-- 顶部版本状态栏 -->
          <div class="version-status-topbar">
            <div class="version-header-meta">
              <div class="version-title-row">
                <template v-if="isCreateMode">
                  <h2>新建版本 · {{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }}</h2>
                  <span class="status-pill success">新建模式</span>
                </template>
                <template v-else>
                  <h2>{{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }} <span class="divider">/</span> {{ selectedVersion || '未选择版本' }}</h2>
                  <span v-if="!editableDraft.is_visible" class="status-pill hidden">已隐藏</span>
                </template>
              </div>
            </div>

            <div class="version-header-actions">
              <template v-if="isCreateMode">
                <button
                  v-if="selectedVersion && editableLoaded"
                  class="admin-btn secondary"
                  type="button"
                  @click="copyCurrentVersionToCreateDraft"
                >
                  <span>复制当前 ({{ selectedVersion }}) 为模板</span>
                </button>
                <button
                  class="admin-btn secondary"
                  type="button"
                  @click="resetCreateDraft"
                >
                  <span>重置</span>
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="admin-btn secondary"
                  :disabled="editableLoading || loading || !selectedVersion"
                  title="向官方源发起实时探活并持久化探活结果，不会保存当前表单草稿"
                  @click="probeCurrentVersion()"
                >
                  <span>实时探活</span>
                </button>

                <!-- 更多操作下拉菜单 -->
                <div class="custom-dropdown-container more-actions-dropdown">
                  <button
                    type="button"
                    class="admin-btn secondary"
                    title="更多操作"
                    @click.stop="moreActionsOpen = !moreActionsOpen"
                  >
                    <span>更多 ▾</span>
                  </button>
                  <transition name="dropdown-fade">
                    <div v-if="moreActionsOpen" class="more-dropdown-menu" @click.stop>
                      <button
                        type="button"
                        class="more-dropdown-item"
                        @click="toggleVersionVisibility(); moreActionsOpen = false"
                      >
                        <span>{{ editableDraft.is_visible ? '隐藏此版本' : '恢复公开' }}</span>
                      </button>
                      <button
                        v-if="selectedDomainSupportsCreateVersion"
                        type="button"
                        class="more-dropdown-item"
                        @click="copyCurrentVersionToCreateDraft(); moreActionsOpen = false"
                      >
                        <span>复制为新版本模板</span>
                      </button>
                      <hr class="more-divider" />
                      <button
                        type="button"
                        class="more-dropdown-item danger"
                        @click="deleteCurrentVersion(); moreActionsOpen = false"
                      >
                        <span>删除此版本</span>
                      </button>
                    </div>
                  </transition>
                </div>
              </template>
            </div>
          </div>

          <div v-if="!isCreateMode && !selectedVersion" class="admin-empty-state">
            请先在左侧列表中选择一个目标版本。
          </div>

          <template v-else>
            <!-- 链接健康条 (Health Banner - 紧凑低饱和)：仅编辑已有版本时展示 -->
            <div
              v-if="!isCreateMode"
              class="health-banner-card"
              :class="currentVersionHealth.isOk ? 'success' : (currentVersionHealth.isChecked ? 'danger' : 'neutral')"
            >
              <div class="banner-left">
                <span class="banner-dot">●</span>
                <strong class="banner-status">
                  {{ currentVersionHealth.isOk ? '链接可用' : (currentVersionHealth.isChecked ? '链接不可用' : '待探活') }}
                </strong>
                <span v-if="currentVersionHealth.httpCode" class="banner-badge">HTTP {{ currentVersionHealth.httpCode }}</span>
                <span v-if="currentVersionHealth.size" class="banner-badge">{{ formatBytes(currentVersionHealth.size) }}</span>
                <span v-if="currentVersionHealth.lastCheckedAt" class="banner-time">
                  最后检查：{{ formatSyncTime(currentVersionHealth.lastCheckedAt) }}
                </span>
              </div>
              <div class="banner-right">
                <button
                  v-if="!currentVersionHealth.isOk && currentVersionHealth.isChecked"
                  class="banner-action-btn"
                  type="button"
                  @click="probeCurrentVersion()"
                >
                  重新探活
                </button>
              </div>
            </div>
            <!-- 基本信息 -->
            <div class="form-section-card">
              <div class="section-card-title">基本信息</div>
              <div
                class="admin-field-grid"
                :class="isCreateMode ? 'compact-4col' : 'compact-3col'"
              >
                <label v-if="isCreateMode" class="admin-field">
                  <span class="field-label">版本号 <small class="field-sublabel">version</small> <b class="text-rose">*</b></span>
                  <input
                    v-model="versionDraft.version"
                    class="admin-input"
                    placeholder="例如: 7.1.0"
                    required
                  />
                </label>

                <label class="admin-field">
                  <span class="field-label">渠道</span>
                  <input
                    v-model="versionDraft.channel"
                    class="admin-input"
                    placeholder="official / bilibili"
                    required
                  />
                </label>

                <label class="admin-field">
                  <span class="field-label">版本代码</span>
                  <input
                    v-model.number="versionDraft.version_code"
                    class="admin-input"
                    type="number"
                    placeholder="例如: 12345"
                  />
                </label>

                <div class="admin-field">
                  <div class="field-header-row">
                    <span class="field-label">
                      文件时间
                    </span>
                    <button
                      v-if="versionDraft.file_created_at_override"
                      class="field-mini-btn"
                      type="button"
                      title="清空后将由后端自动识别 URL 或 Last-Modified 时间"
                      @click="clearActiveFileTime"
                    >
                      清空
                    </button>
                  </div>
                  <input
                    class="admin-input"
                    type="datetime-local"
                    :value="fileTimeInputValue"
                    @input="onFileTimeInput"
                  />
                  <small v-if="fileTimeUnparsable" class="field-tip field-tip-warning">
                    无法识别当前值（{{ fileTimeRaw }}），请重新选择或清空。
                  </small>
                  <small v-else class="field-tip">
                    {{ fileTimeLabel ? `当前 ${fileTimeLabel}，按 UTC 保存` : '留空时按 URL / Last-Modified 自动识别' }}
                    · 来源：{{ getFileTimeSourceDescription(versionDraft.file_created_at_override, versionDraft.artifacts[0]?.urls[0]?.url) }}
                  </small>
                </div>
              </div>
            </div>

            <!-- APK 文件平铺卡片 -->
            <div v-if="showApkFileCard" class="form-section-card apk-file-card">
              <div class="section-card-title">APK 文件</div>

              <div class="admin-field-grid">
                <div class="admin-field">
                  <div class="field-header-row">
                    <span class="field-label">文件名</span>
                    <button
                      v-if="versionDraft.artifacts[0].urls[0]?.url"
                      class="field-mini-btn"
                      type="button"
                      title="根据当前 URL 自动解析并填入文件名"
                      @click="forceExtractActiveArtifactName(versionDraft.artifacts[0])"
                    >
                      根据 URL 填写文件名
                    </button>
                  </div>
                  <input
                    v-model="versionDraft.artifacts[0].name"
                    class="admin-input"
                    placeholder="例如: yuanshen_7.1.0.apk"
                    required
                    @input="syncArtifactsJsonForActiveDraft"
                  />
                </div>

                <label class="admin-field">
                  <span class="field-label">文件大小</span>
                  <input
                    v-model.number="versionDraft.artifacts[0].size"
                    class="admin-input"
                    type="number"
                    min="0"
                    placeholder="字节数"
                    @input="syncArtifactsJsonForActiveDraft"
                  />
                  <small class="field-tip">
                    当前换算：<strong>{{ formatBytes(versionDraft.artifacts[0].size) }}</strong>
                  </small>
                </label>
              </div>

              <!-- URL 独占一行 -->
              <div class="admin-field full-width url-line-field">
                <span class="field-label">下载 URL</span>
                <div class="url-input-action-row">
                  <input
                    v-model="versionDraft.artifacts[0].urls[0].url"
                    class="admin-input text-mono url-long-input"
                    placeholder="https://..."
                    required
                    @input="handleActiveArtifactUrlChange(versionDraft.artifacts[0], versionDraft.artifacts[0].urls[0].url)"
                  />
                  <button
                    class="url-action-pill-btn"
                    type="button"
                    title="复制下载链接"
                    @click="copyUrl(versionDraft.artifacts[0].urls[0].url)"
                  >
                    复制
                  </button>
                  <button
                    class="url-action-pill-btn"
                    type="button"
                    title="在新窗口打开"
                    @click="openUrl(versionDraft.artifacts[0].urls[0].url)"
                  >
                    ↗ 打开
                  </button>
                  <button
                    class="url-action-pill-btn"
                    type="button"
                    title="仅检查网络连通性，不修改或保存任何数据"
                    :disabled="urlProbeMap[versionDraft.artifacts[0].urls[0].url]?.loading"
                    @click="probeUrlItem(versionDraft.artifacts[0].urls[0].url)"
                  >
                    {{ urlProbeMap[versionDraft.artifacts[0].urls[0].url]?.loading ? '测试中…' : '测试 URL' }}
                  </button>
                </div>
              </div>

              <!-- 校验值折叠面板 -->
              <div class="checksums-collapse-section">
                <button
                  class="collapse-toggle-btn"
                  type="button"
                  @click="checksumsOpen = !checksumsOpen"
                >
                  <span class="chevron" :class="{ open: checksumsOpen }">▶</span>
                  <span class="collapse-title">文件校验值</span>
                  <span v-if="getChecksumSummaryText(versionDraft.checksum_etag, versionDraft.checksum_crc64, versionDraft.checksum_md5)" class="checksum-tag">
                    {{ getChecksumSummaryText(versionDraft.checksum_etag, versionDraft.checksum_crc64, versionDraft.checksum_md5) }}
                  </span>
                  <span v-else class="checksum-tag-empty">未配置</span>
                </button>

                <div v-if="checksumsOpen" class="collapse-fields-grid">
                  <label class="admin-field">
                    <span class="field-label">ETag</span>
                    <input
                      v-model="versionDraft.checksum_etag"
                      class="admin-input text-mono"
                      placeholder="例如: &quot;abcd1234...&quot;"
                    />
                  </label>
                  <label class="admin-field">
                    <span class="field-label">CRC64</span>
                    <input
                      v-model="versionDraft.checksum_crc64"
                      class="admin-input text-mono"
                      placeholder="例如: 15852710230531907"
                    />
                  </label>
                  <label class="admin-field">
                    <span class="field-label">MD5</span>
                    <input
                      v-model="versionDraft.checksum_md5"
                      class="admin-input text-mono"
                      placeholder="32位 MD5 字符串"
                    />
                  </label>
                </div>
              </div>
            </div>

            <div v-if="selectedDomainUsesPcEditor" class="form-section-card pc-artifacts-card">
              <div class="section-card-header pc-artifacts-head">
                <div class="card-title-group">
                  <h3>PC 资源文件</h3>
                  <p class="card-subtitle">编辑 package / patch 资源、分卷、路由、manifest/source 与下载 URL。</p>
                </div>
                <div class="section-header-tools artifact-mode-tabs">
                  <button
                    class="tool-pill-btn"
                    :class="{ active: editableDraft.artifactsMode === 'visual' }"
                    type="button"
                    @click="switchArtifactsMode('visual')"
                  >
                    列表
                  </button>
                  <button
                    class="tool-pill-btn"
                    :class="{ active: editableDraft.artifactsMode === 'json' }"
                    type="button"
                    @click="switchArtifactsMode('json')"
                  >
                    JSON
                  </button>
                  <button
                    v-if="editableDraft.artifactsMode === 'json'"
                    class="tool-pill-btn"
                    type="button"
                    @click="formatArtifactsJson"
                  >
                    格式化
                  </button>
                  <button
                    v-if="editableDraft.artifactsMode === 'visual'"
                    class="tool-pill-btn highlight"
                    type="button"
                    @click="addArtifactItem"
                  >
                    添加资源
                  </button>
                </div>
              </div>

              <div class="pc-artifacts-overview">
                <div class="pc-overview-item">
                  <span>资源总数</span>
                  <strong>{{ pcArtifactsOverview.total }}</strong>
                </div>
                <div class="pc-overview-item">
                  <span>Package</span>
                  <strong>{{ pcArtifactsOverview.packageCount }}</strong>
                </div>
                <div class="pc-overview-item">
                  <span>Patch</span>
                  <strong>{{ pcArtifactsOverview.patchCount }}</strong>
                </div>
                <div class="pc-overview-item">
                  <span>总大小</span>
                  <strong>{{ formatBytes(pcArtifactsOverview.totalSize) }}</strong>
                </div>
                <div class="pc-overview-item">
                  <span>有效 URL</span>
                  <strong>{{ pcArtifactsOverview.urlCount }}</strong>
                </div>
              </div>

              <div v-if="editableDraft.artifactsMode === 'json'" class="admin-field full-width pc-json-editor">
                <span class="field-label">Artifacts JSON</span>
                <div class="code-editor-container">
                  <textarea
                    v-model="editableDraft.artifactsJson"
                    class="admin-code-textarea pc-json-textarea"
                    spellcheck="false"
                  ></textarea>
                </div>
                <small class="field-tip">保存时会交给后端按 PC schema 重新校验和生成 artifact_id。</small>
              </div>

              <div v-else class="pc-artifact-list">
                <div
                  v-for="(artifact, artIndex) in editableDraft.artifacts"
                  :key="`pc-artifact-${artIndex}`"
                  class="pc-artifact-item"
                >
                  <div class="pc-artifact-title-row">
                    <div class="pc-artifact-title-main">
                      <strong>{{ pcArtifactTitle(artifact, artIndex) }}</strong>
                      <div class="pc-artifact-tags">
                        <span
                          v-for="tag in pcArtifactSummaryTags(artifact)"
                          :key="tag"
                          class="accordion-summary-tag"
                        >
                          {{ tag }}
                        </span>
                      </div>
                    </div>
                    <button
                      class="tool-pill-btn danger"
                      type="button"
                      :disabled="editableDraft.artifacts.length <= 1"
                      @click="removeArtifactItem(artIndex)"
                    >
                      删除资源
                    </button>
                  </div>

                  <AdminPcArtifactFields
                    :artifact="artifact"
                    :format-bytes="formatBytes"
                    :force-extract-artifact-name="(value) => forceExtractArtifactName(value as EditableArtifactDraft)"
                    :sync-artifacts-to-json="syncArtifactsToJson"
                  />

                  <div class="pc-artifact-section pc-url-list">
                    <div class="field-header-row">
                      <span class="field-label">下载 URL</span>
                      <button class="tool-pill-btn highlight" type="button" @click="addArtifactUrlItem(artIndex)">添加 URL</button>
                    </div>
                    <div
                      v-for="(urlItem, urlIndex) in artifact.urls"
                      :key="`pc-url-${artIndex}-${urlIndex}`"
                      class="pc-url-row"
                    >
                      <input
                        v-model="urlItem.url"
                        class="admin-input text-mono url-long-input"
                        placeholder="https://..."
                        @input="handleArtifactUrlChange(artifact, urlItem.url)"
                      />
                      <input
                        v-model.number="urlItem.priority"
                        class="admin-input pc-priority-input"
                        type="number"
                        min="0"
                        title="priority"
                        @input="syncArtifactsToJson"
                      />
                      <input
                        v-model="urlItem.source_kind"
                        class="admin-input pc-source-kind-input"
                        placeholder="official"
                        title="source_kind"
                        @input="syncArtifactsToJson"
                      />
                      <button class="url-action-pill-btn" type="button" @click="copyUrl(urlItem.url)">复制</button>
                      <button class="url-action-pill-btn" type="button" @click="probeUrlItem(urlItem)">
                        {{ urlProbeMap[urlItem.url]?.loading ? '测试中' : '测试' }}
                      </button>
                      <button
                        class="tool-pill-btn danger"
                        type="button"
                        :disabled="artifact.urls.length <= 1"
                        @click="removeArtifactUrlItem(artIndex, urlIndex)"
                      >
                        删除
                      </button>
                    </div>
                  </div>

                  <div class="pc-artifact-section">
                    <div class="pc-artifact-section-title">元数据</div>
                    <div class="admin-field-grid compact-3col">
                    <label class="admin-field">
                      <span class="field-label">Manifest <small class="field-sublabel">JSON object</small></span>
                      <textarea v-model="artifact.manifestJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                    </label>
                    <label class="admin-field">
                      <span class="field-label">Source <small class="field-sublabel">compact provenance JSON</small></span>
                      <textarea v-model="artifact.sourceJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                    </label>
                    <label class="admin-field">
                      <span class="field-label">附加属性 <small class="field-sublabel">attributes</small></span>
                      <textarea v-model="artifact.attributesJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                    </label>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- 底部操作条：新建走提交，编辑走吸附保存 -->
            <div v-if="isCreateMode" class="form-actions-bar">
            <div class="actions-left">
              <button
                type="button"
                class="admin-btn secondary"
                @click="resetCreateDraft"
              >
                <span>重置表单</span>
              </button>
              <span v-if="!createDraft.version.trim()" class="create-submit-hint">
                填写版本号后即可提交
              </span>
            </div>

            <div class="actions-right">
              <button
                class="admin-btn primary"
                type="submit"
                :disabled="loading || !selectedDomainId || !createDraft.version.trim()"
              >
                <span>{{ loading ? '录入中…' : '保存并录入新版本' }}</span>
              </button>
            </div>
          </div>
            <!-- 底部吸附保存交互条（唯一保存入口） -->
            <div v-else class="sticky-save-bar" :class="{ dirty: isEditableDirty }">
              <div class="bar-left">
                <span v-if="isEditableDirty" class="save-status-badge dirty">⚠ 有 {{ dirtyChangesCount }} 项未保存修改</span>
                <span v-else class="save-status-badge clean">● 没有未保存修改</span>
              </div>
              <div class="bar-right">
                <button
                  v-if="isEditableDirty"
                  class="admin-btn secondary small"
                  type="button"
                  @click="discardChanges"
                >
                  放弃修改
                </button>
                <button
                  class="admin-btn primary small"
                  type="submit"
                  :disabled="loading || !selectedVersion || !isEditableDirty"
                >
                  <span>{{ selectedDomainSupportsCreateVersion && isUrlChanged ? '保存并探活' : '保存更改' }}</span>
                </button>
              </div>
            </div>
          </template>
        </form>
      </div>
      <div v-else class="content-work-card">
        <div class="version-status-topbar">
          <div class="version-header-meta">
            <div class="version-title-row"><h2>PC 版本只读</h2></div>
          </div>
        </div>
        <div class="admin-empty-state">
          <strong>当前单 APK 表单不适用于 PC 资源</strong>
          <span>PC package、patch、voice、file manifest 与 chunk manifest 具有不同身份结构，当前不提供手工新增或编辑。</span>
          <span>请使用已接入的官方采集与探活流程维护记录；左侧版本列表仍可用于只读浏览。</span>
        </div>
      </div>
    </div>
  </section>
</template>
