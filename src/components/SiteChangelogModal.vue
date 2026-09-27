<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api, isAbortError } from "../api";
import { gameActivityTime, gameActivityTitle } from "../game-activity";
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
                <p>全站最近动态</p>
                <button type="button" :class="{ 'is-refreshing': refreshSpinning }" @click="refreshActivity">
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M13.5 7a5.5 5.5 0 1 0 .2 2.2" />
                    <path d="M13.5 3.5V7h-3.5" />
                  </svg>
                  <span>刷新</span>
                </button>
              </div>
              <p v-if="activityLoading" class="changelog-empty" role="status">正在读取数据动态…</p>
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
              <ol v-else class="changelog-activity-list changelog-timeline">
                <li v-for="event in activity" :key="event.id" class="changelog-entry">
                  <time :datetime="event.occurred_at">{{ gameActivityTime(event.occurred_at) }}</time>
                  <div>
                    <h3>{{ gameActivityTitle(event, gameNames[event.game_id] || event.game_id) }}</h3>
                    <p>{{ event.platform === 'android' ? 'Android' : 'PC' }} · {{ event.type === 'version_update' ? '发现新版本' : '探活确认不可用' }}</p>
                  </div>
                </li>
              </ol>
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
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
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
}

@media (prefers-reduced-motion: reduce) {
  .changelog-data-head button.is-refreshing svg {
    animation: none;
  }
}
</style>
