<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import VersionPicker from "../VersionPicker.vue";
import { domainModeLabel } from "../../domain-presentation";
import type { ArchiveDomain, VersionSummary } from "../../types";

export interface VisibleArchiveMode {
  domain: ArchiveDomain;
  capability: string;
}

const props = defineProps<{
  versions: VersionSummary[];
  selectedVersion: string;
  domain: ArchiveDomain | null;
  domainId: string;
  mode: string;
  visibleModes: VisibleArchiveMode[];
  controlStripDensity: string;
  searchableMode: boolean;
  query: string;
  suppressAvailabilityPresentation: boolean;
}>();

const emit = defineEmits<{
  (e: "select-version", version: string): void;
  (e: "select-mode", domain: ArchiveDomain, capability: string): void;
  (e: "update:query", value: string): void;
}>();

function isActive(item: VisibleArchiveMode): boolean {
  return item.capability === "compare"
    ? props.mode === "compare"
    : item.domain.id === props.domainId && item.capability === props.mode;
}

// Sliding indicator: one highlight that moves between tabs instead of each tab
// lighting up on its own. It is also what you grab when dragging to another tab.
const tabsEl = ref<HTMLElement | null>(null);
// Plain array: filled by the template ref callback, read only from event handlers.
const tabEls: HTMLElement[] = [];
const indicator = ref<{ x: number; y: number; width: number; height: number } | null>(null);
const indicatorAnimated = ref(false);
const activeIndex = computed(() => props.visibleModes.findIndex(isActive));

function measure(): void {
  const tab = tabEls[activeIndex.value];
  if (!tab || drag.value?.moved) {
    if (!tab) indicator.value = null;
    return;
  }
  indicator.value = { x: tab.offsetLeft, y: tab.offsetTop, width: tab.offsetWidth, height: tab.offsetHeight };
}

let resizeObserver: ResizeObserver | null = null;
onMounted(() => {
  measure();
  // Turn transitions on only after the first placement, so the indicator does not slide in from 0,0.
  requestAnimationFrame(() => { indicatorAnimated.value = true; });
  if (typeof ResizeObserver !== "undefined" && tabsEl.value) {
    resizeObserver = new ResizeObserver(() => measure());
    resizeObserver.observe(tabsEl.value);
  }
});
onBeforeUnmount(() => resizeObserver?.disconnect());
watch(() => [activeIndex.value, props.visibleModes.length], () => nextTick(measure));

// Press and hold the active tab, drag it onto another tab, release to switch.
const DRAG_THRESHOLD = 6;
const drag = ref<{ pointerId: number; startX: number; startY: number; grabX: number; grabY: number; moved: boolean; target: number } | null>(null);
let suppressClick = false;

function onPointerDown(event: PointerEvent, index: number): void {
  if (index !== activeIndex.value || event.button !== 0 || !indicator.value || !tabsEl.value) return;
  const box = tabsEl.value.getBoundingClientRect();
  drag.value = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    grabX: event.clientX - box.left - indicator.value.x,
    grabY: event.clientY - box.top - indicator.value.y,
    moved: false,
    target: index,
  };
}

function tabIndexAt(clientX: number, clientY: number): number {
  let best = -1;
  let bestDistance = Infinity;
  tabEls.slice(0, props.visibleModes.length).forEach((tab, index) => {
    const rect = tab.getBoundingClientRect();
    const dx = Math.max(rect.left - clientX, 0, clientX - rect.right);
    const dy = Math.max(rect.top - clientY, 0, clientY - rect.bottom);
    const distance = Math.hypot(dx, dy);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return bestDistance <= 40 ? best : -1;
}

function onPointerMove(event: PointerEvent): void {
  const state = drag.value;
  const container = tabsEl.value;
  if (!state || event.pointerId !== state.pointerId || !container || !indicator.value) return;
  if (!state.moved) {
    if (Math.hypot(event.clientX - state.startX, event.clientY - state.startY) < DRAG_THRESHOLD) return;
    state.moved = true;
    container.setPointerCapture?.(event.pointerId);
  }
  const box = container.getBoundingClientRect();
  const { width, height } = indicator.value;
  indicator.value = {
    x: Math.min(Math.max(event.clientX - box.left - state.grabX, 0), container.clientWidth - width),
    y: Math.min(Math.max(event.clientY - box.top - state.grabY, 0), container.clientHeight - height),
    width,
    height,
  };
  state.target = tabIndexAt(event.clientX, event.clientY);
}

function endDrag(event: PointerEvent, commit: boolean): void {
  const state = drag.value;
  if (!state || event.pointerId !== state.pointerId) return;
  drag.value = null;
  if (!state.moved) return;
  suppressClick = true;
  setTimeout(() => { suppressClick = false; }, 0);
  const target = commit ? state.target : -1;
  const item = props.visibleModes[target];
  if (item && target !== activeIndex.value) emit("select-mode", item.domain, item.capability);
  else measure();
}

function onTabClick(item: VisibleArchiveMode): void {
  if (suppressClick) return;
  emit("select-mode", item.domain, item.capability);
}
</script>

<template>
  <section class="control-strip" :class="controlStripDensity">
    <VersionPicker
      :versions="versions"
      :model-value="selectedVersion"
      :domain="domain"
      :mode="mode"
      :label-override="mode === 'legacy' ? '候选线索' : undefined"
      :show-availability="mode !== 'files' && !suppressAvailabilityPresentation"
      @select="emit('select-version', $event)"
    />
    <div class="mode-field">
      <div
        ref="tabsEl"
        class="mode-tabs"
        :class="{ 'mode-tabs-grid': visibleModes.length === 6, 'has-indicator': indicator, dragging: drag?.moved }"
        role="tablist"
        aria-label="数据视图"
        @pointermove="onPointerMove"
        @pointerup="endDrag($event, true)"
        @pointercancel="endDrag($event, false)"
        @lostpointercapture="endDrag($event, false)"
      >
        <span
          v-if="indicator"
          class="mode-tab-indicator"
          :class="{ animated: indicatorAnimated && !drag?.moved }"
          :style="{ width: `${indicator.width}px`, height: `${indicator.height}px`, transform: `translate(${indicator.x}px, ${indicator.y}px)` }"
          aria-hidden="true"
        ></span>
        <button
          v-for="(item, index) in visibleModes"
          :key="`${item.domain.id}:${item.capability}`"
          :ref="(el) => { if (el) tabEls[index] = el as HTMLElement; }"
          type="button"
          role="tab"
          class="mode-tab"
          :class="{ active: isActive(item), 'drop-target': drag?.moved && drag.target === index && index !== activeIndex }"
          :aria-selected="isActive(item)"
          :title="isActive(item) ? '可按住拖到其他选项切换' : undefined"
          @pointerdown="onPointerDown($event, index)"
          @click="onTabClick(item)"
        >
          {{ domainModeLabel(item.domain, item.capability) }}
        </button>
      </div>
    </div>
    <label v-if="searchableMode" class="search-box">
      <span>搜索</span>
      <div class="search-input-wrap">
        <input
          :value="query"
          placeholder="文件名 / MD5 / URL"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        />
        <button
          v-if="query"
          type="button"
          class="search-clear-btn"
          aria-label="清除搜索"
          title="清除搜索"
          @click.prevent="emit('update:query', '')"
        >
          ✕
        </button>
      </div>
    </label>
    <!-- Keeps the tabs where they are on modes without search (e.g. 版本对比). -->
    <div v-else class="search-box-spacer" aria-hidden="true"></div>
  </section>
</template>
