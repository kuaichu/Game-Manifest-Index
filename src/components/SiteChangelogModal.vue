<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api, isAbortError } from "../api";
import { gameActivityTime, gameActivityTitle } from "../game-activity";
import { gameIcons } from "../game-icons";
import type { GameActivityEvent } from "../types";

const props = defineProps<{
  open: boolean;
  originPos?: { x: number; y: number } | null;
  initialTab: "system" | "data";
  gameNames: Record<string, string>;
}>();

const emit = defineEmits<{ (event: "close"): void }>();
const closeButton = ref<HTMLButtonElement | null>(null);
const selectedTab = ref<"system" | "data">("system");
const activity = ref<GameActivityEvent[]>([]);
const activityLoading = ref(false);
const activityError = ref(false);
const refreshKey = ref(0);
const refreshSpinning = ref(false);
const failedIcons = ref(new Set<string>());
const activityDays = computed(() => {
  const days = new Map<string, { date: string; label: string; events: GameActivityEvent[] }>();
  for (const event of activity.value) {
    const time = new Date(event.occurred_at);
    const valid = !Number.isNaN(time.getTime());
    const date = valid
      ? `${time.getFullYear()}-${String(time.getMonth() + 1).padStart(2, "0")}-${String(time.getDate()).padStart(2, "0")}`
      : "unknown";
    if (!days.has(date)) days.set(date, {
      date,
      label: valid ? time.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }) : "时间未知",
      events: [],
    });
    days.get(date)!.events.push(event);
  }
  return [...days.values()];
});
let refreshTimer: number | null = null;
let previousFocus: HTMLElement | null = null;
let previousOverflow = "";

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
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    void nextTick(() => closeButton.value?.focus());
  } else {
    document.body.style.overflow = previousOverflow;
    void nextTick(() => previousFocus?.focus());
  }
});

onMounted(() => window.addEventListener("keydown", handleKeydown));
onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  if (props.open) document.body.style.overflow = previousOverflow;
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

          <div class="provenance-modal-body changelog-body">
            <div class="changelog-tabs" role="tablist" aria-label="更新日志类别">
              <button id="changelog-system-tab" type="button" role="tab" :aria-selected="selectedTab === 'system'" aria-controls="changelog-system-panel" @click="selectedTab = 'system'">系统日志</button>
              <button id="changelog-data-tab" type="button" role="tab" :aria-selected="selectedTab === 'data'" aria-controls="changelog-data-panel" @click="selectedTab = 'data'">数据动态</button>
            </div>

            <section v-if="selectedTab === 'system'" id="changelog-system-panel" role="tabpanel" aria-labelledby="changelog-system-tab">
              <div class="changelog-timeline">
                <article class="changelog-entry">
                  <time datetime="2026-09-27">2026.09.27</time>
                  <div>
                    <h3>新增《崩坏：因缘精灵》PC 文件清单</h3>
                    <p>《崩坏：因缘精灵》国服 CBT2 0.60.2 版本的 PC 文件清单现已收录，共 566 个文件。支持按目录浏览和搜索，并可查看文件大小与 MD5 校验信息。</p>
                  </div>
                </article>
              </div>
            </section>

            <section v-else id="changelog-data-panel" role="tabpanel" aria-labelledby="changelog-data-tab">
              <div class="changelog-data-head">
                <p>全站最近动态 <span v-if="activity.length" class="changelog-count">{{ activity.length }} 条</span></p>
                <button type="button" :disabled="activityLoading" :class="{ 'is-refreshing': refreshSpinning || activityLoading }" @click="refreshActivity">
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M13.5 7a5.5 5.5 0 1 0 .2 2.2" />
                    <path d="M13.5 3.5V7h-3.5" />
                  </svg>
                  <span>{{ activityLoading ? '刷新中' : '刷新' }}</span>
                </button>
              </div>
              <p v-if="activityLoading && !activity.length" class="changelog-empty" role="status">正在读取数据动态…</p>
              <p v-else-if="activityError" class="changelog-empty" role="alert">数据动态暂时无法读取，请稍后刷新。</p>
              <div v-else-if="!activity.length" class="changelog-empty changelog-empty-idle">
                <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                  <circle cx="24" cy="24" r="17" />
                  <circle cx="24" cy="24" r="10" />
                  <circle cx="24" cy="24" r="2" fill="currentColor" stroke="none" />
                  <path d="M24 24 36 12" />
                </svg>
                <span class="changelog-empty-code">STATUS: AWAITING_NEW_EVENTS</span>
                <p>暂无数据动态。</p>
              </div>
              <div v-else class="changelog-activity-days" :aria-busy="activityLoading">
                <section v-for="day in activityDays" :key="day.date" class="changelog-day" :aria-label="day.label">
                  <h3 class="changelog-day-heading">
                    <time v-if="day.date !== 'unknown'" :datetime="day.date">{{ day.label }}</time>
                    <span v-else>{{ day.label }}</span>
                    <span class="changelog-day-count">{{ day.events.length }} 条动态</span>
                  </h3>
                  <ol class="changelog-activity-list">
                    <li v-for="event in day.events" :key="event.id" class="changelog-event" :aria-label="`${gameActivityTitle(event, gameNames[event.game_id] || event.game_id)} · ${event.platform === 'android' ? 'Android' : 'PC'} · ${gameActivityTime(event.occurred_at)}`">
                      <span class="changelog-game-icon" aria-hidden="true">
                        <img v-if="gameIcons[event.game_id] && !failedIcons.has(event.game_id)" :src="gameIcons[event.game_id]" alt="" @error="failedIcons.add(event.game_id)" />
                        <span v-else>{{ (gameNames[event.game_id] || event.game_id).slice(0, 1) }}</span>
                      </span>
                      <div class="changelog-event-content">
                        <div class="changelog-event-title">
                          <h4>{{ gameNames[event.game_id] || event.game_id }}</h4>
                          <span class="changelog-version">{{ event.version }}</span>
                        </div>
                        <div class="changelog-event-details">
                          <span class="changelog-platform">{{ event.platform === 'android' ? 'Android' : 'PC' }}</span>
                          <span class="changelog-event-status" :class="{ 'is-unavailable': event.type === 'version_unavailable' }">{{ event.type === 'version_update' ? '发现新版本' : '探活确认不可用' }}</span>
                        </div>
                      </div>
                      <time class="changelog-event-time" :datetime="event.occurred_at" :title="gameActivityTime(event.occurred_at)">{{ activityClock(event.occurred_at) }}</time>
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

.changelog-body {
  gap: 0;
}

.changelog-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
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
.changelog-data-head button:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.changelog-timeline {
  position: relative;
}

.changelog-timeline::before {
  content: "";
  position: absolute;
  top: 9px;
  bottom: 9px;
  left: 107px;
  border-left: 1px dashed rgba(148, 163, 184, 0.17);
  pointer-events: none;
}

.changelog-entry {
  display: grid;
  grid-template-columns: 98px minmax(0, 1fr);
  gap: 20px;
  position: relative;
  padding: 0 0 24px;
}

.changelog-entry::before {
  content: "";
  position: absolute;
  top: 5px;
  left: 103px;
  width: 7px;
  height: 7px;
  border: 1px solid rgba(56, 189, 248, 0.65);
  border-radius: 50%;
  background: #111827;
  box-shadow: 0 0 0 3px #0b111c;
}

.changelog-entry + .changelog-entry {
  padding-top: 8px;
}

.changelog-entry + .changelog-entry::before {
  top: 13px;
}

.changelog-entry:last-child {
  padding-bottom: 0;
}

.changelog-entry time {
  padding-top: 3px;
  color: #38bdf8;
  font: 700 12px var(--font-mono);
}

.changelog-entry h3 {
  margin: 0 0 8px;
  color: #f1f5f9;
  font-size: 15px;
}

.changelog-entry p {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.8;
}

.changelog-data-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
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

.changelog-empty-code {
  color: #64748b;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
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
  display: grid;
  gap: 24px;
}

.changelog-day-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  color: #cbd5e1;
  font: 600 12px var(--font-mono);
}

.changelog-day-heading::after {
  content: "";
  flex: 1;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.changelog-day-count {
  color: #94a3b8;
  font: 11px var(--font-sans);
}

.changelog-event {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}

.changelog-event:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.changelog-game-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  overflow: hidden;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.08);
  color: #7dd3fc;
  font-size: 16px;
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
  gap: 6px 10px;
}

.changelog-event-title h4 {
  margin: 0;
  color: #f1f5f9;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.changelog-version {
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.09);
  color: #7dd3fc;
  font: 12px var(--font-mono);
  overflow-wrap: anywhere;
}

.changelog-event-details {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
}

.changelog-platform {
  color: #cbd5e1;
  font: 11px var(--font-mono);
}

.changelog-event-status {
  color: #94a3b8;
}

.changelog-event-status.is-unavailable {
  color: #fda4af;
}

.changelog-event-time {
  padding-top: 3px;
  color: #94a3b8;
  font: 11px var(--font-mono);
}

@media (max-width: 600px) {
  .changelog-timeline::before {
    left: 4px;
  }

  .changelog-entry {
    grid-template-columns: 1fr;
    gap: 7px;
    padding-left: 20px;
  }

  .changelog-entry::before {
    left: 0;
  }

  .changelog-event {
    grid-template-columns: 32px minmax(0, 1fr) auto;
    gap: 9px;
  }

  .changelog-game-icon {
    width: 32px;
    height: 32px;
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
