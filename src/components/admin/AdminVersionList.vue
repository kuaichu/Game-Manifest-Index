<script setup lang="ts">
import AdminIcon from "./AdminIcon.vue";
import { formatSyncTime } from "../../admin-format";
import {
  getDomainFriendlyName,
  isVersionAvailable,
  isVersionUnknown,
  versionHealthClass,
  versionHealthTitle,
} from "../../admin-version-editor";
import type { AdminVersionListState } from "../../composables/useAdminVersionList";
import type { AdminDomain } from "../../types";

const props = defineProps<{
  versionList: AdminVersionListState;
  selectedGameId: string;
  selectedDomainId: string;
  gameDomains: AdminDomain[];
  resolveGameIcon: (id: string, source?: string) => string | undefined;
}>();

const emit = defineEmits<{
  (event: "select-version", version: string): void;
}>();

const {
  selectedVersion,
  versionSearchQuery,
  selectedGame,
  selectedDomain,
  selectedDomainGameName,
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
  handleDropdownSelectGame,
  handleDropdownSelectDomain,
  toggleVersionFilter,
  resetVersionFilter,
  toggleMajorGroup,
  toggleMinorGroup,
} = props.versionList;
</script>

<template>
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
                @click="emit('select-version', entry.item.version)"
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
                    @click="emit('select-version', subItem.version)"
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

    <!-- 右侧插槽：版本工作台 -->
    <slot />
  </div>
</template>
