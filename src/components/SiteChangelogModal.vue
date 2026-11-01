<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api, isAbortError } from "../api";
import { useModalScrollLock } from "../composables/useModalScrollLock";
import { activityDateKey, gameActivityTime, groupActivityReleases, type ActivityReleaseRow } from "../game-activity";
import { gameIcons } from "../game-icons";
import { groupSiteChangelogByDate, searchSiteChangelog, siteChangelog } from "../site-changelog";
import type { GameActivityEvent } from "../types";

const props = defineProps<{
  open: boolean;
  originPos?: { x: number; y: number } | null;
  initialTab: "system" | "data";
  gameNames: Record<string, string>;
}>();

const emit = defineEmits<{ (event: "close"): void }>();
useModalScrollLock(() => props.open);
const closeButton = ref<HTMLButtonElement | null>(null);
const selectedTab = ref<"system" | "data">("system");
const changelogQuery = ref("");
const visibleDayCount = ref(3);
const filteredChangelog = computed(() => searchSiteChangelog(siteChangelog, changelogQuery.value));
const changelogDays = computed(() => groupSiteChangelogByDate(filteredChangelog.value));
const visibleChangelogDays = computed(() => changelogDays.value.slice(0, visibleDayCount.value));
const remainingChangelogDays = computed(() => Math.max(0, changelogDays.value.length - visibleChangelogDays.value.length));
const remainingChangelogEntries = computed(() => changelogDays.value
  .slice(visibleChangelogDays.value.length)
  .reduce((count, day) => count + day.entries.length, 0));
const activity = ref<GameActivityEvent[]>([]);
const activityLoading = ref(false);
const activityError = ref(false);
const activityQuery = ref("");
const lastRefreshedAt = ref<string | null>(null);
const refreshKey = ref(0);
const refreshSpinning = ref(false);
const failedIcons = ref(new Set<string>());
const activityReleases = computed<ActivityReleaseRow[]>(() => groupActivityReleases(activity.value));
const filteredActivity = computed(() => {
  const query = activityQuery.value.trim().toLowerCase();
  if (!query) return activityReleases.value;
  return activityReleases.value.filter((row) => {
    if ((props.gameNames[row.gameId] ?? row.gameId).toLowerCase().includes(query)) return true;
    return row.platforms.some((item) => item.version.toLowerCase().includes(query)
      || item.platform.toLowerCase().includes(query));
  });
});
const activityDays = computed(() => {
  const days = new Map<string, { date: string; label: string; rows: ActivityReleaseRow[] }>();
  for (const row of filteredActivity.value) {
    const date = activityDateKey(row.occurredAt);
    if (!days.has(date)) {
      days.set(date, {
        date,
        label: date === "unknown" ? "时间未知" : date.replaceAll("-", "."),
        rows: [],
      });
    }
    days.get(date)!.rows.push(row);
  }
  return [...days.values()];
});
const activityMatchCount = computed(() => filteredActivity.value.length);
let refreshTimer: number | null = null;
let previousFocus: HTMLElement | null = null;

const originStyle = computed(() => {
  if (!props.originPos || typeof window === "undefined") return { "--origin-x": "38vw", "--origin-y": "-38vh" };
  return {
    "--origin-x": `${Math.round(props.originPos.x - window.innerWidth / 2)}px`,
    "--origin-y": `${Math.round(props.originPos.y - window.innerHeight / 2)}px`,
  };
});

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && props.open) emit("close");
}

function activityClock(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" });
}

function activityRowLabel(row: ActivityReleaseRow): string {
  const name = props.gameNames[row.gameId] || row.gameId;
  const versions = row.platforms.map((item) => `${item.platform} ${item.version}`).join(" · ");
  const status = row.type === "version_unavailable" ? "不可用" : "发现新版本";
  return `${name} · ${versions} · ${status} · ${gameActivityTime(row.occurredAt)}`;
}

function refreshActivity(): void {
  refreshKey.value += 1;
  refreshSpinning.value = false;
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  void nextTick(() => {
    refreshSpinning.value = true;
    refreshTimer = window.setTimeout(() => { refreshSpinning.value = false; }, 450);
  });
}

watch(
  () => [props.open, selectedTab.value, refreshKey.value] as const,
  async ([open, tab], _previous, onCleanup) => {
    if (!open || tab !== "data") return;
    const controller = new AbortController();
    onCleanup(() => controller.abort());
    activityLoading.value = true;
    activityError.value = false;
    try {
      activity.value = (await api.activity(controller.signal)).items;
      lastRefreshedAt.value = new Date().toISOString();
    } catch (error) {
      if (!controller.signal.aborted && !isAbortError(error)) activityError.value = true;
    } finally {
      if (!controller.signal.aborted) activityLoading.value = false;
    }
  },
);

watch(() => props.open, (open) => {
  if (open) {
    selectedTab.value = props.initialTab;
    changelogQuery.value = "";
    activityQuery.value = "";
    visibleDayCount.value = 3;
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void nextTick(() => closeButton.value?.focus());
  } else {
    void nextTick(() => previousFocus?.focus());
  }
});

watch(changelogQuery, () => { visibleDayCount.value = 3; });

function showEarlierChangelog(): void {
  visibleDayCount.value += 3;
}

onMounted(() => window.addEventListener("keydown", handleKeydown));
onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
});
</script>

<template>
  <teleport to="body">
    <transition name="modal-zoom">
      <div
        v-if="open"
        class="provenance-modal-backdrop"
        :style="originStyle"
        @click.self="emit('close')"
      >
        <section class="provenance-modal-dialog changelog-dialog" role="dialog" aria-modal="true" aria-labelledby="site-changelog-title">
          <header class="provenance-modal-header">
            <div class="header-left">
              <div class="header-icon-box" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="5" width="18" height="16" rx="2" />
                  <path d="M7 3v4M17 3v4M3 10h18M7 14h5M7 17h9" />
                </svg>
              </div>
              <div>
                <div class="header-kicker">PROJECT & GAME UPDATES</div>
                <h2 id="site-changelog-title" class="header-title">更新日志</h2>
              </div>
            </div>
            <button ref="closeButton" class="modal-close-btn" type="button" aria-label="关闭更新日志" @click="emit('close')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </header>

          <div class="changelog-toolbar">
            <div class="changelog-tabs" role="tablist" aria-label="更新日志类别">
              <button id="changelog-system-tab" type="button" role="tab" :aria-selected="selectedTab === 'system'" aria-controls="changelog-system-panel" @click="selectedTab = 'system'">系统日志</button>
              <button id="changelog-data-tab" type="button" role="tab" :aria-selected="selectedTab === 'data'" aria-controls="changelog-data-panel" @click="selectedTab = 'data'">数据动态</button>
            </div>
            <label v-if="selectedTab === 'system'" class="changelog-search">
              <span>搜索系统日志</span>
              <input v-model="changelogQuery" type="search" placeholder="搜索标题或正文" autocomplete="off" />
              <button v-if="changelogQuery" type="button" aria-label="清除搜索" @click="changelogQuery = ''">清除</button>
            </label>
          </div>

          <div class="provenance-modal-body changelog-body">

            <section v-if="selectedTab === 'system'" id="changelog-system-panel" role="tabpanel" aria-labelledby="changelog-system-tab">
              <p class="changelog-result-count" role="status">{{ filteredChangelog.length }} 条记录</p>
              <p v-if="!filteredChangelog.length" class="changelog-empty" role="status">没有找到匹配的更新日志。<button type="button" @click="changelogQuery = ''">清除搜索</button></p>
              <div v-else class="changelog-timeline">
                <section v-for="(day, dayIndex) in visibleChangelogDays" :key="day.date" class="changelog-entry-day">
                  <h3 class="changelog-date"><time :datetime="day.date">{{ day.date.replaceAll('-', '.') }}</time><span>{{ day.entries.length }} 条记录</span></h3>
                  <details v-for="(entry, entryIndex) in day.entries" :key="entry.id" class="changelog-entry" :open="dayIndex === 0 && entryIndex === 0 && !changelogQuery.trim()">
                    <summary><span>{{ entry.title }}</span></summary>
                    <p>{{ entry.body }}</p>
                  </details>
                </section>
                <button v-if="remainingChangelogDays" class="changelog-more" type="button" @click="showEarlierChangelog">
                  显示更早记录（还有 {{ remainingChangelogDays }} 天，{{ remainingChangelogEntries }} 条）
                </button>
              </div>
            </section>

            <section v-else id="changelog-data-panel" role="tabpanel" aria-labelledby="changelog-data-tab">
              <div class="changelog-data-head">
                <p>全站最近动态 <span v-if="activity.length" class="changelog-count">{{ activityMatchCount }} 条</span></p>
                <div class="changelog-data-actions">
                  <span v-if="lastRefreshedAt" class="changelog-refreshed">最近刷新 {{ activityClock(lastRefreshedAt) }}</span>
                  <button type="button" :disabled="activityLoading" :class="{ 'is-refreshing': refreshSpinning || activityLoading }" @click="refreshActivity">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M13.5 7a5.5 5.5 0 1 0 .2 2.2" />
                      <path d="M13.5 3.5V7h-3.5" />
                    </svg>
                    <span>{{ activityLoading ? '刷新中' : '刷新' }}</span>
                  </button>
                </div>
              </div>
              <label class="changelog-search changelog-search-data">
                <span>搜索数据动态</span>
                <input v-model="activityQuery" type="search" placeholder="游戏名、版本号或平台" autocomplete="off" />
                <button v-if="activityQuery" type="button" aria-label="清除搜索" @click="activityQuery = ''">清除</button>
              </label>
              <p v-if="activityLoading && !activity.length" class="changelog-empty" role="status">正在读取数据动态…</p>
              <p v-else-if="activityError" class="changelog-empty" role="alert">数据动态暂时无法读取。<button type="button" @click="refreshActivity">重试</button></p>
              <div v-else-if="!activity.length" class="changelog-empty changelog-empty-idle">
                <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                  <circle cx="24" cy="24" r="17" />
                  <circle cx="24" cy="24" r="10" />
                  <circle cx="24" cy="24" r="2" fill="currentColor" stroke="none" />
                  <path d="M24 24 36 12" />
                </svg>
                <p>最近还没有采集到新动态，稍后再来看看。</p>
              </div>
              <p v-else-if="!activityMatchCount" class="changelog-empty" role="status">没有匹配的动态。<button type="button" @click="activityQuery = ''">清除搜索</button></p>
              <div v-else class="changelog-activity-days" :aria-busy="activityLoading">
                <section v-for="day in activityDays" :key="day.date" class="changelog-day" :aria-label="day.label">
                  <h3 class="changelog-day-heading">
                    <time v-if="day.date !== 'unknown'" :datetime="day.date">{{ day.label }}</time>
                    <span v-else>{{ day.label }}</span>
                  </h3>
                  <ol class="changelog-activity-list">
                    <li v-for="row in day.rows" :key="row.key" class="changelog-event" :aria-label="activityRowLabel(row)">
                      <span class="changelog-game-icon" aria-hidden="true">
                        <img v-if="gameIcons[row.gameId] && !failedIcons.has(row.gameId)" :src="gameIcons[row.gameId]" :class="{ 'endfield-icon': row.gameId === 'endfield' }" alt="" @error="failedIcons.add(row.gameId)" />
                        <span v-else>{{ (gameNames[row.gameId] || row.gameId).slice(0, 1) }}</span>
                      </span>
                      <div class="changelog-event-content">
                        <div class="changelog-event-title">
                          <h4>{{ gameNames[row.gameId] || row.gameId }}</h4>
                          <span v-for="item in row.platforms" :key="item.platform" class="changelog-platform-chip">
                            <span class="changelog-platform">{{ item.platform }}</span>
                            <span class="changelog-version">{{ item.version }}</span>
                          </span>
                          <span v-if="row.type === 'version_unavailable'" class="changelog-event-status is-unavailable">不可用</span>
                          <span v-else class="changelog-event-dot" role="img" title="发现新版本" aria-label="发现新版本"></span>
                        </div>
                      </div>
                      <time class="changelog-event-time" :datetime="row.occurredAt" :title="gameActivityTime(row.occurredAt)">{{ activityClock(row.occurredAt) }}</time>
                    </li>
                  </ol>
                </section>
              </div>
            </section>
          </div>
        </section>
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.changelog-dialog {
  max-width: 680px;
}

.changelog-toolbar {
  flex: 0 0 auto;
  padding: 16px 24px;
}

.changelog-body {
  gap: 0;
  min-height: 0;
  padding-top: 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.3) transparent;
}

.changelog-toolbar > :last-child {
  margin-bottom: 0;
}

.changelog-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  padding: 4px;
  border: 1px solid rgba(148, 201, 255, 0.12);
  border-radius: 10px;
  background: rgba(8, 13, 22, 0.7);
}

.changelog-tabs button {
  flex: 1;
  min-height: 36px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #94a3b8;
  font-family: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.changelog-tabs button[aria-selected="true"] {
  background: rgba(56, 189, 248, 0.15);
  color: #e0f2fe;
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.35);
}

.changelog-tabs button:focus-visible,
.changelog-data-head button:focus-visible,
.changelog-search input:focus-visible,
.changelog-search button:focus-visible,
.changelog-entry summary:focus-visible,
.changelog-more:focus-visible,
.changelog-empty button:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.changelog-search {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 14px;
  color: #94a3b8;
  font-size: 12px;
}

.changelog-search span {
  flex: 0 0 auto;
}

.changelog-search input {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 36px;
  padding: 7px 10px;
  border: 1px solid rgba(148, 201, 255, 0.18);
  border-radius: 7px;
  background: rgba(8, 13, 22, 0.7);
  color: #e2e8f0;
  font: inherit;
}

.changelog-search input::placeholder {
  color: #64748b;
}

.changelog-search button,
.changelog-empty button {
  padding: 4px 6px;
  border: 0;
  background: transparent;
  color: #38bdf8;
  font: inherit;
  cursor: pointer;
}

.changelog-result-count {
  margin: 0 0 14px;
  color: #94a3b8;
  font-size: 12px;
}

.changelog-timeline {
  position: relative;
}

.changelog-timeline::before {
  content: "";
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 4px;
  border-left: 1px dashed rgba(148, 163, 184, 0.17);
  pointer-events: none;
}

.changelog-entry-day {
  position: relative;
  margin-bottom: 22px;
  padding-left: 20px;
}

.changelog-entry-day::before {
  content: "";
  position: absolute;
  top: 5px;
  left: 0;
  width: 7px;
  height: 7px;
  border: 1px solid rgba(56, 189, 248, 0.65);
  border-radius: 50%;
  background: #111827;
  box-shadow: 0 0 0 3px #0b111c;
}

.changelog-date {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 9px;
  color: #38bdf8;
  font: 700 12px var(--font-mono);
}

.changelog-date span {
  color: #64748b;
  font: 11px var(--font-sans);
}

.changelog-date span::after {
  content: "";
  display: inline-block;
  width: 25px;
  margin-left: 9px;
  vertical-align: middle;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.changelog-entry {
  margin: 0 0 8px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 8px;
  background: rgba(8, 13, 22, 0.35);
}

.changelog-entry summary {
  padding: 10px 12px;
  color: #f1f5f9;
  font-size: 15px;
  font-weight: 650;
  line-height: 1.5;
  overflow-wrap: anywhere;
  cursor: pointer;
}

.changelog-entry p {
  margin: 0;
  padding: 0 12px 12px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.changelog-more {
  width: 100%;
  min-height: 38px;
  margin-top: 2px;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.06);
  color: #7dd3fc;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.changelog-data-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.changelog-data-head p {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}

.changelog-count {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(148, 163, 184, 0.08);
  color: #94a3b8;
  font: 11px var(--font-mono);
}

.changelog-data-head button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.changelog-data-head button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 4px 8px;
  border: 0;
  background: none;
  color: #38bdf8;
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.changelog-data-head button svg {
  width: 12px;
  height: 12px;
}

.changelog-data-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.changelog-refreshed {
  color: #64748b;
  font: 11px var(--font-mono);
}

.changelog-search-data {
  margin-bottom: 10px;
}

.changelog-data-head button.is-refreshing svg {
  animation: changelog-refresh-turn 0.45s ease-in-out both;
}

@keyframes changelog-refresh-turn {
  to { transform: rotate(360deg); }
}

.changelog-empty {
  margin: 0;
  padding: 24px 12px;
  border: 1px dashed rgba(148, 163, 184, 0.2);
  border-radius: 10px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.8;
  text-align: center;
}

.changelog-empty-idle {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 18px 16px;
}

.changelog-empty-idle svg {
  width: 30px;
  height: 30px;
  color: #4b6477;
}


.changelog-empty-idle p {
  margin: 0;
}

.changelog-activity-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.changelog-activity-days {
  display: block;
}

.changelog-day {
  min-width: 0;
}

.changelog-day + .changelog-day {
  margin-top: 6px;
}

.changelog-day-heading {
  position: sticky;
  top: 0;
  z-index: 1;
  margin: 0;
  padding: 10px 0 7px;
  background: rgba(8, 13, 22, 0.98);
  backdrop-filter: blur(6px);
  color: #7c8ea4;
  font: 600 11.5px/1.4 var(--font-mono);
  letter-spacing: 0.05em;
}

.changelog-event {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 6px 2px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.06);
}

.changelog-event:last-child {
  border-bottom: 0;
}

.changelog-event-content {
  min-width: 0;
}

.changelog-game-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  overflow: hidden;
  border-radius: 7px;
  background: rgba(56, 189, 248, 0.08);
  color: #7dd3fc;
  font-size: 13px;
  font-weight: 700;
}

.changelog-game-icon img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.changelog-event-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 7px;
}

.changelog-event-title h4 {
  margin: 0;
  color: #f1f5f9;
  font-size: 13.5px;
  font-weight: 620;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.changelog-platform-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(148, 163, 184, 0.08);
}

.changelog-platform {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: none;
  color: #8598ad;
  font: 10px/1.4 var(--font-mono);
}

.changelog-version {
  color: #7dd3fc;
  font: 600 11.5px/1.4 var(--font-mono);
  overflow-wrap: anywhere;
}

.changelog-event-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.16);
}

.changelog-event-status.is-unavailable {
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(244, 63, 94, 0.12);
  color: #fda4af;
  font-size: 11px;
}

.changelog-event-time {
  color: #64748b;
  font: 11px var(--font-mono);
}
@media (max-width: 600px) {
  .changelog-toolbar {
    padding: 12px 16px 0;
  }

  .changelog-body {
    padding: 14px 16px;
  }

  .changelog-day-heading {
    padding: 8px 0 6px;
  }

  .changelog-search {
    flex-wrap: wrap;
    gap: 6px 9px;
  }

  .changelog-search input {
    flex-basis: 100%;
    order: 1;
  }

  .changelog-search button {
    margin-left: auto;
  }

  .changelog-event {
    grid-template-columns: 26px minmax(0, 1fr) auto;
    gap: 9px;
  }

  .changelog-game-icon {
    width: 26px;
    height: 26px;
  }

  .changelog-event-title h4 {
    font-size: 13px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .changelog-data-head button.is-refreshing svg {
    animation: none;
  }
}
</style>
