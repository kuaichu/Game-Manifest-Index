<script setup lang="ts">
import CustomSelect from "../CustomSelect.vue";
import AdminOperationProgress from "./AdminOperationProgress.vue";
import { externalScheduleNotice, probeScheduleNotice } from "../../admin-ui-capabilities";
import { formatSyncTime } from "../../admin-format";
import {
  discoverItemState,
  discoverSkippedCount,
  isProbeUnknownItem,
  probeAvailableUrls,
  probeCheckedUrls,
  probeFailedUrls,
  probeItemKey,
  probeResultReason,
  probeUnavailableUrls,
  probeUnknownUrls,
} from "../../operation-scope";
import type { AdminOperations } from "../../composables/useAdminOperations";
import type { AdminProbe } from "../../composables/useAdminProbe";
import type { AdminCatalog } from "../../types";

const props = defineProps<{
  probe: AdminProbe;
  ops: AdminOperations;
  catalog: AdminCatalog;
  loading: boolean;
  resolveGameIcon: (id: string, source?: string) => string | undefined;
  useFallbackIcon: (event: Event, id: string) => void;
}>();

// Probe and operation state live in AdminView (via composables) so polling and results survive tab switches.
const {
  syncSchedule,
  probeSchedule,
  probeSchedulerStatus,
  saveSyncSchedule,
  saveProbeSchedule,
} = props.probe;

const {
  opAction,
  opScope,
  opPlatformScope,
  opSelectedGameIds,
  opTimeout,
  opWorkers,
  opRunning,
  opJob,
  opResult,
  opExecutionTime,
  opTerminalHidden,
  probeTableFilter,
  filteredProbeItems,
  operationControlsLocked,
  operationScopeText,
  opProgressPercent,
  opCurrentGameLabel,
  terminalLogEntries,
  terminalLogStats,
  terminalStatusText,
  terminalLogTone,
  gameDisplayName,
  selectAllGames,
  clearSelectedGames,
  isGameSelected,
  toggleGameSelection,
  refreshTerminalLogs,
  clearOpResult,
  executeAdminOperation,
  cancelAdminOperation,
  isOperationPollBusy,
} = props.ops;
</script>

<template>
  <section class="admin-probe-dashboard">
    <!-- 上方两列：操作控制台 + 自动化定时调度 -->
    <div class="probe-top-grid">
      <!-- 卡片 1: 运维操作控制台 (start / status / cancel) -->
      <div class="probe-card">
        <div class="card-title-group">
          <h3>数据采集与版本探活控制台</h3>
        </div>

        <!-- 动作模式选择 -->
        <div class="op-action-options">
          <label
            class="op-action-card"
            :class="{ active: opAction === 'both' }"
            @click="opAction = 'both'"
          >
            <input v-model="opAction" class="op-radio" type="radio" value="both" />
            <div class="op-action-text">
              <span class="op-action-title">查找新版本 + 探活全量（discover + probe）</span>
              <span class="op-action-desc">先扫描官方入口发现新版本并写入索引，再逐条探活所有历史版本链接（推荐）</span>
            </div>
          </label>

          <label
            class="op-action-card"
            :class="{ active: opAction === 'discover' }"
            @click="opAction = 'discover'"
          >
            <input v-model="opAction" class="op-radio" type="radio" value="discover" />
            <div class="op-action-text">
              <span class="op-action-title">仅查找新版本（discover）</span>
              <span class="op-action-desc">只扫描官方入口并写入新版本记录，不检查已有链接的可用性</span>
            </div>
          </label>
        </div>

        <!-- 数据类型选择 (全量 / APK / PC) -->
        <div class="op-scope-tabs" style="margin-top: 10px;">
          <button
            type="button"
            class="op-scope-btn"
            :class="{ active: opPlatformScope === 'all' }"
            :disabled="operationControlsLocked"
            :aria-pressed="opPlatformScope === 'all'"
            @click="opPlatformScope = 'all'"
          >
            全量数据 (APK + 已接入的 PC)
          </button>
          <button
            type="button"
            class="op-scope-btn"
            :class="{ active: opPlatformScope === 'android' }"
            :disabled="operationControlsLocked"
            :aria-pressed="opPlatformScope === 'android'"
            @click="opPlatformScope = 'android'"
          >
            仅 Android (APK)
          </button>
          <button
            type="button"
            class="op-scope-btn"
            :class="{ active: opPlatformScope === 'pc' }"
            :disabled="operationControlsLocked"
            :aria-pressed="opPlatformScope === 'pc'"
            @click="opPlatformScope = 'pc'"
          >
            仅 PC 客户端（已接入适配器）
          </button>
        </div>

        <!-- 游戏范围选择 -->
        <div class="op-scope-tabs" style="margin-top: 10px;">
          <button
            type="button"
            class="op-scope-btn"
            :class="{ active: opScope === 'all' }"
            @click="opScope = 'all'"
          >
            全部游戏 (all_games=true)
          </button>
          <button
            type="button"
            class="op-scope-btn"
            :class="{ active: opScope === 'custom' }"
            @click="opScope = 'custom'"
          >
            指定游戏 ({{ opSelectedGameIds.length }}/{{ catalog.games.length }})
          </button>
        </div>

        <!-- 指定游戏多选网格 -->
        <div v-if="opScope === 'custom'" class="op-games-selector">
          <div class="op-games-toolbar">
            <span class="text-muted">点击游戏勾选/取消：</span>
            <div class="op-games-actions">
              <button type="button" class="op-mini-btn" @click="selectAllGames">全选</button>
              <button type="button" class="op-mini-btn" @click="clearSelectedGames">清空</button>
            </div>
          </div>
          <div class="op-games-grid">
            <div
              v-for="game in catalog.games"
              :key="game.id"
              class="op-game-chip"
              :class="{ selected: isGameSelected(game.id) }"
              @click="toggleGameSelection(game.id)"
            >
              <img
                :src="resolveGameIcon(game.id, game.icon_source)"
                class="op-game-icon"
                alt=""
                @error="useFallbackIcon($event, game.id)"
              />
              <span class="op-game-name" :title="game.name">{{ game.name }}</span>
            </div>
          </div>
        </div>

        <!-- 高级参数配置 -->
        <div class="op-params-grid">
          <label class="admin-field">
            <span class="field-label">请求超时 (秒)</span>
            <input v-model.number="opTimeout" class="admin-input" type="number" min="1" max="60" />
          </label>
          <label class="admin-field">
            <span class="field-label">并发线程数 (Workers)</span>
            <input v-model.number="opWorkers" class="admin-input" type="number" min="1" max="16" />
          </label>
        </div>

        <!-- 执行操作按钮与实时进度 -->
        <AdminOperationProgress
          :loading="loading"
          :running="opRunning"
          :job="opJob"
          :scope-text="operationScopeText"
          :progress-percent="opProgressPercent"
          :current-game-label="opCurrentGameLabel"
          @start="executeAdminOperation"
          @cancel="cancelAdminOperation"
        />
      </div>

      <!-- 卡片 2: 定时调度与策略配置 -->
      <div class="probe-card">
        <div class="card-title-group">
          <h3>定时探活与采集计划</h3>
          <details class="inline-help">
            <summary>说明</summary>
            <p>{{ externalScheduleNotice }}</p>
          </details>
        </div>

        <!-- 每日采集计划 -->
        <div class="schedule-toggle-row">
          <label class="admin-toggle-label">
            <input v-model="syncSchedule.enabled" class="admin-toggle-checkbox" type="checkbox" />
            <span class="toggle-slider"></span>
            <span class="toggle-text">{{ syncSchedule.enabled ? '采集计划参数已启用' : '采集计划参数已停用' }}</span>
          </label>
        </div>
        <div class="schedule-inputs-row">
          <label class="admin-field">
            <span class="field-label">时间点 1（时区由外部任务定义）</span>
            <input v-model="syncSchedule.times[0]" class="admin-input" type="time" />
          </label>
          <label class="admin-field">
            <span class="field-label">时间点 2（时区由外部任务定义）</span>
            <input v-model="syncSchedule.times[1]" class="admin-input" type="time" />
          </label>
        </div>
        <button class="admin-btn secondary full-width" type="button" :disabled="loading" @click="saveSyncSchedule">
          <span>保存采集计划参数</span>
        </button>

        <hr style="border: 0; border-top: 1px solid var(--line-soft); margin: 6px 0;" />

        <!-- 定时探活计划 -->
        <div class="schedule-runtime-status" aria-live="polite">
          <div>
            内置探活计时器：<strong>{{ !probeSchedulerStatus ? '状态未知' : probeSchedulerStatus.running ? '运行中' : '已停止' }}</strong>
          </div>
          <div v-if="probeSchedulerStatus?.next_run_at">
            下次任务计划：{{ formatSyncTime(probeSchedulerStatus.next_run_at) || '时间无效' }}
          </div>
          <div v-if="probeSchedulerStatus?.last_started_at">
            最近任务启动：{{ formatSyncTime(probeSchedulerStatus.last_started_at) || '时间无效' }}
            <span v-if="probeSchedulerStatus.last_job_id"> · 任务 {{ probeSchedulerStatus.last_job_id }}</span>
          </div>
          <div v-if="probeSchedulerStatus?.error" class="text-danger">错误：{{ probeSchedulerStatus.error }}</div>
        </div>
        <details class="inline-help">
          <summary>说明</summary>
          <p>{{ probeScheduleNotice }}</p>
        </details>
        <div class="schedule-toggle-row">
          <label class="admin-toggle-label">
            <input v-model="probeSchedule.enabled" class="admin-toggle-checkbox" type="checkbox" />
            <span class="toggle-slider"></span>
            <span class="toggle-text">{{ probeSchedule.enabled ? '定时探活已启用' : '定时探活已停用' }}</span>
          </label>
        </div>
        <div class="schedule-inputs-row">
          <label class="admin-field">
            <span class="field-label">执行周期 (小时)</span>
            <input v-model.number="probeSchedule.interval_hours" class="admin-input" type="number" min="1" max="168" />
          </label>
          <div class="admin-field">
            <span class="field-label">默认模式</span>
            <CustomSelect
              v-model="probeSchedule.mode"
              :options="[
                { label: '普通轮（跳过 20h 内有效证据）', value: 'normal' },
                { label: '全量轮（新发现及上次可用 URL）', value: 'full' }
              ]"
            />
          </div>
        </div>
        <button class="admin-btn secondary full-width" type="button" :disabled="loading" @click="saveProbeSchedule">
          <span>保存定时探活计划</span>
        </button>
      </div>
    </div>

    <!-- 执行结果实时明细看板 (当有操作结果时展示) -->
    <div v-if="opResult" class="op-results-container">
      <div class="op-results-header">
        <div class="card-title-group">
          <h3>运维操作执行结果报告</h3>
          <p class="card-subtitle">
            执行动作：<span class="text-mono font-bold">{{ opResult.actions.join(' + ') }}</span>
            · 数据范围：<span class="text-mono font-bold">{{ operationScopeText }}</span>
            · 目标游戏：<span class="text-mono font-bold">{{ opResult.game_ids.length }} 款</span>
            · 总耗时：<span class="text-emerald text-mono font-bold">{{ opExecutionTime }} 秒</span>
          </p>
        </div>
        <button type="button" class="op-mini-btn" @click="clearOpResult">✕ 关闭结果卡片</button>
      </div>

      <!-- 汇总统计卡片 -->
      <div class="op-summary-cards">
        <div v-if="opResult.discover" class="op-stat-card">
          <span class="op-stat-label">查找成功任务</span>
          <div class="op-stat-value text-emerald">{{ opResult.discover.succeeded }} / {{ opResult.discover.selected }}</div>
        </div>
        <div v-if="opResult.discover" class="op-stat-card">
          <span class="op-stat-label">发现全新版本</span>
          <div class="op-stat-value text-cyan">{{ opResult.discover.new_versions }} 个</div>
        </div>
        <div v-if="opResult.discover && opResult.discover.failed > 0" class="op-stat-card">
          <span class="op-stat-label">查找失败任务</span>
          <div class="op-stat-value text-rose">{{ opResult.discover.failed }}</div>
        </div>
        <div v-if="opResult.discover && discoverSkippedCount(opResult.discover) > 0" class="op-stat-card">
          <span class="op-stat-label">不支持而跳过</span>
          <div class="op-stat-value text-amber">{{ discoverSkippedCount(opResult.discover) }}</div>
        </div>

        <div
          v-if="opResult.probe"
          class="op-stat-card clickable"
          :class="{ active: probeTableFilter === 'all' }"
          title="点击筛选：显示全部探活记录"
          @click="probeTableFilter = 'all'"
        >
          <span class="op-stat-label">探活 URL 总数</span>
          <div class="op-stat-value text-mono">{{ probeCheckedUrls(opResult.probe) }}</div>
        </div>
        <div
          v-if="opResult.probe"
          class="op-stat-card clickable tone-emerald"
          :class="{ active: probeTableFilter === 'available' }"
          title="点击筛选：仅显示可用 URL"
          @click="probeTableFilter = 'available'"
        >
          <span class="op-stat-label">可用 URL (Available)</span>
          <div class="op-stat-value text-emerald">{{ probeAvailableUrls(opResult.probe) }}</div>
        </div>
        <div
          v-if="opResult.probe"
          class="op-stat-card clickable tone-rose"
          :class="{ active: probeTableFilter === 'unavailable' }"
          title="点击筛选：仅显示失效 URL"
          @click="probeTableFilter = 'unavailable'"
        >
          <span class="op-stat-label">失效 URL (Unavailable)</span>
          <div class="op-stat-value text-rose">{{ probeUnavailableUrls(opResult.probe) }}</div>
        </div>
        <div
          v-if="opResult.probe && probeUnknownUrls(opResult.probe) > 0"
          class="op-stat-card clickable tone-amber"
          :class="{ active: probeTableFilter === 'unknown' }"
          title="点击筛选：仅显示未知/未判定 URL"
          @click="probeTableFilter = 'unknown'"
        >
          <span class="op-stat-label">未知 URL (Unknown)</span>
          <div class="op-stat-value text-amber">{{ probeUnknownUrls(opResult.probe) }}</div>
        </div>
        <div
          v-if="opResult.probe && probeFailedUrls(opResult.probe) > 0"
          class="op-stat-card clickable tone-amber"
          :class="{ active: probeTableFilter === 'failed' }"
          title="点击筛选：仅显示异常记录"
          @click="probeTableFilter = 'failed'"
        >
          <span class="op-stat-label">探活异常数</span>
          <div class="op-stat-value text-amber">{{ probeFailedUrls(opResult.probe) }}</div>
        </div>
      </div>

      <!-- 查找新版本明细表 -->
      <div v-if="opResult.discover" class="op-table-section">
        <p v-if="opResult.discover.items_truncated" class="text-muted">
          本次采集共 {{ opResult.discover.items_total }} 条结果，下方保留 {{ opResult.discover.items.length }} 条明细；上方统计包含全部结果。
        </p>
        <h4 style="margin: 0 0 10px; font-size: 13.5px; font-weight: 750; color: #7dd3fc;">查找新版本 (Discover) 执行明细</h4>
        <div class="op-table-wrapper">
          <table class="op-table">
            <thead>
              <tr>
                <th>游戏</th>
                <th>平台</th>
                <th>执行状态</th>
                <th>官方最新版本</th>
                <th>版本标记</th>
                <th>下载可用性</th>
                <th>存储路径 / 错误详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in opResult.discover.items" :key="`${item.game_id}-${item.platform || item.scope || 'unknown'}-${item.version || 'none'}`">
                <td>
                  <strong class="text-mono">{{ gameDisplayName(item.game_id) }}</strong>
                </td>
                <td><span class="text-mono">{{ item.platform || item.scope || '--' }}</span></td>
                <td>
                  <span v-if="discoverItemState(item) === 'skipped'" class="op-badge warning">↷ 跳过（不支持）</span>
                  <span v-else-if="discoverItemState(item) === 'success'" class="op-badge success">✓ 成功</span>
                  <span v-else class="op-badge danger">✕ 失败</span>
                </td>
                <td>
                  <span class="text-mono font-bold">{{ item.version || '--' }}</span>
                </td>
                <td>
                  <span v-if="item.new" class="op-badge info">全新版本</span>
                  <span v-else-if="discoverItemState(item) === 'success'" class="op-badge muted">现有最新</span>
                  <span v-else class="text-muted">--</span>
                </td>
                <td>
                  <span v-if="discoverItemState(item) === 'skipped'" class="op-badge warning">不适用</span>
                  <span v-else-if="item.available === true" class="op-badge success">可用 (200)</span>
                  <span v-else-if="item.available === false" class="op-badge danger">不可用</span>
                  <span v-else-if="discoverItemState(item) === 'success'" class="op-badge warning">未探活</span>
                  <span v-else class="text-muted">--</span>
                </td>
                <td>
                  <span v-if="item.error" class="text-rose text-mono" style="font-size: 11.5px;">{{ item.error }}</span>
                  <span v-else-if="item.path" class="text-muted text-mono" style="font-size: 11.5px;">{{ item.path }}</span>
                  <span v-else class="text-muted">--</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 探活历史版本明细表 -->
      <div v-if="opResult.probe" class="op-table-section">
        <p v-if="opResult.probe.items_truncated" class="text-muted">
          本次探活共 {{ opResult.probe.items_total }} 条结果，下方保留 {{ opResult.probe.items.length }} 条明细；筛选仅针对保留的明细，上方统计包含全部结果。
        </p>
        <div class="op-table-head-row">
          <h4 style="margin: 0; font-size: 13.5px; font-weight: 750; color: #34d399;">
            历史版本探活 (Probe) 执行明细
            <span v-if="probeTableFilter === 'all'" class="text-muted" style="font-weight: 400; margin-left: 6px;">(共 {{ filteredProbeItems.length }} 条)</span>
            <span v-else-if="probeTableFilter === 'available'" style="color: #34d399; font-weight: 700; margin-left: 6px;">(仅显示可用: {{ filteredProbeItems.length }} 条)</span>
            <span v-else-if="probeTableFilter === 'unavailable'" style="color: #f43f5e; font-weight: 700; margin-left: 6px;">(仅显示失效: {{ filteredProbeItems.length }} 条)</span>
            <span v-else-if="probeTableFilter === 'unknown'" style="color: #fbbf24; font-weight: 700; margin-left: 6px;">(仅显示未知: {{ filteredProbeItems.length }} 条)</span>
            <span v-else-if="probeTableFilter === 'failed'" style="color: #fbbf24; font-weight: 700; margin-left: 6px;">(仅显示异常: {{ filteredProbeItems.length }} 条)</span>
          </h4>
          <div class="op-filter-chips">
            <button
              type="button"
              class="op-filter-chip"
              :class="{ active: probeTableFilter === 'all' }"
              @click="probeTableFilter = 'all'"
            >全部 ({{ opResult.probe.items.length }})</button>
            <button
              type="button"
              class="op-filter-chip tone-emerald"
              :class="{ active: probeTableFilter === 'available' }"
              @click="probeTableFilter = 'available'"
            >✓ 可用 ({{ probeAvailableUrls(opResult.probe) }})</button>
            <button
              type="button"
              class="op-filter-chip tone-rose"
              :class="{ active: probeTableFilter === 'unavailable' }"
              @click="probeTableFilter = 'unavailable'"
            >✕ 失效 ({{ probeUnavailableUrls(opResult.probe) }})</button>
            <button
              v-if="probeUnknownUrls(opResult.probe) > 0"
              type="button"
              class="op-filter-chip tone-amber"
              :class="{ active: probeTableFilter === 'unknown' }"
              @click="probeTableFilter = 'unknown'"
            >? 未知 ({{ probeUnknownUrls(opResult.probe) }})</button>
            <button
              v-if="probeFailedUrls(opResult.probe) > 0"
              type="button"
              class="op-filter-chip tone-amber"
              :class="{ active: probeTableFilter === 'failed' }"
              @click="probeTableFilter = 'failed'"
            >⚠ 异常 ({{ probeFailedUrls(opResult.probe) }})</button>
          </div>
        </div>
        <div class="op-table-wrapper" style="max-height: 340px; overflow-y: auto;">
          <table class="op-table">
            <thead>
              <tr>
                <th>游戏</th>
                <th>平台</th>
                <th>版本</th>
                <th>Artifact / URL</th>
                <th>可用性状态</th>
                <th>探活适配器</th>
                <th>探活原因 / 异常信息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="pItem in filteredProbeItems" :key="probeItemKey(pItem)">
                <td><strong class="text-mono">{{ gameDisplayName(pItem.game_id) }}</strong></td>
                <td><span class="text-mono">{{ pItem.platform || '--' }}</span></td>
                <td><span class="text-mono font-bold">{{ pItem.version }}</span></td>
                <td>
                  <span v-if="pItem.kind" class="op-badge muted">{{ pItem.kind }}</span>
                  <span v-if="pItem.url" class="text-mono text-muted" style="display: block; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px;" :title="pItem.url">{{ pItem.url }}</span>
                  <span v-if="pItem.artifact_index !== undefined || pItem.url_index !== undefined" class="text-muted" style="font-size: 10.5px;">#{{ pItem.artifact_index ?? '-' }}/{{ pItem.url_index ?? '-' }}</span>
                </td>
                <td>
                  <span v-if="pItem.available === true" class="op-badge success">✓ 可用</span>
                  <span v-else-if="pItem.available === false" class="op-badge danger">✕ 失效</span>
                  <span v-else-if="pItem.ok" class="op-badge warning">? 未知</span>
                  <span v-else class="op-badge danger">✕ 探测失败</span>
                </td>
                <td><span class="text-mono text-muted" style="font-size: 11.5px;">{{ pItem.adapter || 'default' }}</span></td>
                <td>
                  <span
                    :class="!pItem.ok || pItem.available === false ? 'text-rose' : isProbeUnknownItem(pItem) ? 'text-amber' : 'text-emerald'"
                    style="font-size: 11.5px;"
                  >{{ probeResultReason(pItem) }}</span>
                </td>
              </tr>
              <tr v-if="filteredProbeItems.length === 0">
                <td colspan="7" style="text-align: center; padding: 24px; color: var(--muted);">
                  当前筛选条件下没有匹配的探活记录
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 底部全宽运维日志面板 -->
    <div class="admin-terminal-window">
      <div class="terminal-titlebar">
        <div class="terminal-heading">
          <h3>任务日志</h3>
          <p>实时记录探活与版本发现结果，原始行可展开查看。</p>
        </div>
        <div class="terminal-state" :class="`tone-${terminalLogTone(terminalStatusText)}`">
          <span class="terminal-state-dot"></span>
          <span>{{ terminalStatusText }}</span>
        </div>
        <div class="terminal-actions">
          <button class="terminal-refresh-btn" type="button" @click="opTerminalHidden = true" title="仅隐藏当前页面的日志">
            <span>清屏</span>
          </button>
          <button class="terminal-refresh-btn" type="button" :disabled="loading || isOperationPollBusy()" @click="refreshTerminalLogs" title="重新获取日志">
            <span>刷新</span>
          </button>
        </div>
      </div>
      <div class="terminal-summary" aria-label="日志摘要">
        <div class="terminal-summary-item">
          <span>范围</span>
          <strong>{{ operationScopeText }}</strong>
        </div>
        <div class="terminal-summary-item">
          <span>记录</span>
          <strong>{{ terminalLogStats.total }}</strong>
        </div>
        <div class="terminal-summary-item tone-success">
          <span>成功</span>
          <strong>{{ terminalLogStats.success }}</strong>
        </div>
        <div class="terminal-summary-item tone-danger">
          <span>异常</span>
          <strong>{{ terminalLogStats.danger }}</strong>
        </div>
        <div class="terminal-summary-item tone-warning">
          <span>待确认</span>
          <strong>{{ terminalLogStats.warning }}</strong>
        </div>
      </div>
      <div class="terminal-viewport" aria-live="polite">
        <div v-if="opTerminalHidden" class="terminal-empty terminal-empty-muted">
          <strong>日志已清屏</strong>
          <span>仅隐藏当前页面，新日志到达后会继续显示。</span>
        </div>
        <div v-else-if="terminalLogEntries.length" class="terminal-list">
          <article
            v-for="entry in terminalLogEntries"
            :key="entry.id"
            class="terminal-row"
            :class="`tone-${entry.tone}`"
          >
            <span class="terminal-row-index">{{ String(entry.id).padStart(3, '0') }}</span>
            <div class="terminal-row-content">
              <div class="terminal-row-meta">
                <span class="terminal-phase">{{ entry.phase }}</span>
                <strong>{{ entry.target }}</strong>
                <span class="terminal-outcome">{{ entry.outcome }}</span>
              </div>
              <p v-if="entry.detail" class="terminal-row-detail">{{ entry.detail }}</p>
              <details class="terminal-raw-details">
                <summary>查看原始记录</summary>
                <code>{{ entry.raw }}</code>
              </details>
            </div>
          </article>
        </div>
        <div v-else class="terminal-empty">
          <strong>暂无运维日志</strong>
          <span>点击上方执行按钮开始任务，或刷新以获取最新记录。</span>
        </div>
      </div>
    </div>
  </section>
</template>
