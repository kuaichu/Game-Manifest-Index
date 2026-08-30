<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { ArchiveDomain, VersionSummary } from "../types";
import { artifactCountForMode, artifactKindForMode, availabilityStatesForMode, buildVersionBadges, displayVersionLabel, versionSupportsMode } from "../domain-presentation";
import { versionFamily } from "../version-grouping";

const props = withDefaults(
  defineProps<{
    versions: VersionSummary[];
    modelValue: string;
    domain: ArchiveDomain | null;
    mode?: string;
    labelOverride?: string;
    showAvailability?: boolean;
  }>(),
  {
    showAvailability: true,
  },
);

const emit = defineEmits<{ select: [version: string] }>();
const root = ref<HTMLElement | null>(null);
const open = ref(false);
const filterQuery = ref("");
const collapsed = ref(new Set<string>());

const family = (version: string) => {
  return versionFamily(version, props.domain?.adapter, props.domain?.game_id);
};

const groups = computed(() => {
  const output = new Map<string, VersionSummary[]>();
  const scopesHoYoVersions = props.domain?.adapter === "hoyo"
    && ["packages", "patches", "chunks"].includes(props.mode || "");
  const visibleVersions = scopesHoYoVersions
    ? props.versions.filter((item) => versionSupportsMode(item, props.mode!, props.domain?.adapter))
    : props.versions;
  for (const item of visibleVersions) {
    const key = family(item.version);
    if (!output.has(key)) output.set(key, []);
    output.get(key)!.push(item);
  }
  return [...output.entries()];
});

const displayVersion = (item: VersionSummary) => displayVersionLabel(item.version, item.attributes);

// Legacy suffixed versions collapse into one plain-version picker row.
const pickerRows = computed(() => {
  const q = filterQuery.value.trim().toLowerCase();
  const output: Array<{
    name: string;
    rows: Array<{
      base: string;
      item: VersionSummary;
      states: Record<string, number>;
    }>;
  }> = [];

  for (const [name, items] of groups.value) {
    const seen = new Map<string, { item: VersionSummary; states: Record<string, number> }>();
    for (const item of items) {
      const base = displayVersion(item);
      const modeStates = props.mode
        ? availabilityStatesForMode(item, props.mode, props.domain?.adapter)
        : item.availability_states;
      const states = {
        available: Number(modeStates?.available || 0),
        unavailable: Number(modeStates?.unavailable || 0),
        unknown: Number(modeStates?.unknown || 0),
      };
      const entry = seen.get(base);
      if (!entry) {
        seen.set(base, { item, states });
      } else {
        entry.states.available += states.available;
        entry.states.unavailable += states.unavailable;
        entry.states.unknown += states.unknown;
      }
    }

    const filteredRows = [...seen.entries()]
      .map(([base, entry]) => ({
        base,
        item: entry.item,
        states: entry.states,
      }))
      .filter((row) => {
        if (!q) return true;
        return row.base.toLowerCase().includes(q) || row.item.version.toLowerCase().includes(q);
      });

    if (filteredRows.length > 0 || !q) {
      output.push({
        name,
        rows: filteredRows,
      });
    }
  }
  return output;
});

const selectedLabel = computed(() => {
  return (
    props.labelOverride ||
    displayVersion(
      props.versions.find((item) => item.version === props.modelValue) ||
        ({ version: props.modelValue, attributes: {} } as VersionSummary),
    )
  );
});

function formatFileDate(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return `${year}/${month}/${day}`;
  }
  const normalized = /(?:z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  if (isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function groupSuffix(): string {
  return "版本";
}

function caps(row: {
  base: string;
  item: VersionSummary;
  states: Record<string, number>;
}): Array<{ label: string; tone: string }> {
  if (props.mode || props.domain?.adapter === "android") {
    const total = row.states.available + row.states.unavailable + row.states.unknown;
    const modeCount = props.mode
      ? artifactCountForMode(row.item, props.mode, props.domain?.adapter)
      : row.item.artifact_count;
    const merged = {
      ...row.item,
      artifact_count: total || modeCount || row.item.artifact_count,
      availability_states: row.states,
    } as VersionSummary;
    return buildVersionBadges(props.domain, merged, formatFileDate, props.showAvailability, props.mode);
  }
  return buildVersionBadges(props.domain, row.item, formatFileDate, props.showAvailability);
}

function timeBadge(row: {
  base: string;
  item: VersionSummary;
  states: Record<string, number>;
}) {
  const all = caps(row);
  return all.find((item) => item.tone === "slate") || null;
}

function isLatestVersion(version: string): boolean {
  const scopesHoYoVersions = props.domain?.adapter === "hoyo"
    && ["packages", "patches", "chunks"].includes(props.mode || "");
  const latest = scopesHoYoVersions
    ? props.versions.find((item) => versionSupportsMode(item, props.mode!, props.domain?.adapter))
    : props.versions[0];
  return latest?.version === version;
}

function isPatchVersion(version: string): boolean {
  const clean = version.split("@")[0].trim();
  const parts = clean.split(".");
  if (parts.length >= 3) {
    const patch = Number.parseInt(parts[2], 10);
    return !Number.isNaN(patch) && patch > 0;
  }
  return false;
}

interface AtomicBadge {
  label: string;
  tone: string;
}

function isRowUnavailable(row: {
  base: string;
  item: VersionSummary;
  states: Record<string, number>;
}): boolean {
  const unavailable = Number(row.states.unavailable || 0);
  const available = Number(row.states.available || 0);
  const manifestFiles = (props.domain?.adapter === "wuwa" || props.domain?.adapter === "perfectworld_patcher") && props.mode === "files";
  const kind = props.mode ? artifactKindForMode(props.mode) : "";
  const count = manifestFiles
    ? artifactCountForMode(row.item, "files", props.domain?.adapter)
    : kind ? row.item.artifact_kinds?.[kind]?.count || 0 : (available + unavailable + Number(row.states.unknown || 0)) || Number(row.item.artifact_count || 0);

  if (props.mode && count === 0) {
    if (versionSupportsMode(row.item, props.mode, props.domain?.adapter)) return false;
    if (props.mode === "files" && props.domain?.adapter === "hoyo") {
      const pkg = row.item.artifact_kinds?.package;
      const chunk = row.item.artifact_kinds?.chunk;
      const pkgAvail = (pkg?.availability_states?.available || 0) > 0;
      const chunkAvail = (chunk?.availability_states?.available || 0) > 0 || (chunk?.count || 0) > 0;
      return !(pkgAvail || chunkAvail);
    }
    return true;
  }

  if (unavailable > 0 && available === 0) return true;
  if (unavailable > 0 && count > 0 && unavailable >= count) return true;
  return false;
}

function atomicBadges(row: {
  base: string;
  item: VersionSummary;
  states: Record<string, number>;
}): AtomicBadge[] {
  const all = caps(row);
  const result: AtomicBadge[] = [];

  for (const badge of all) {
    if (badge.tone === "slate" && badge.label !== "已归档") continue;
    if (badge.label === "文件清单") continue;
    if (badge.label === "含更新包" || badge.label === "含更新补丁") continue;

    // 拆解复合标签，如 "完整包 + 直链 + Chunk"
    if (badge.label.includes(" + ")) {
      const parts = badge.label.split(" + ").map((p) => p.trim()).filter(Boolean);
      for (const part of parts) {
        let tone = "blue";
        if (part === "Chunk") tone = "violet";
        else if (part === "直链" || part === "直链文件") tone = "cyan";
        else if (part === "完整包") tone = "blue";
        result.push({ label: part, tone });
      }
    } else if (badge.label === "直链文件") {
      result.push({ label: "直链", tone: "cyan" });
    } else {
      result.push(badge);
    }
  }

  // 若需要展示可用性，确保每一行均有明确且准确的可用性徽章
  if (props.showAvailability) {
    const hasStatus = result.some((b) => ["可用", "不可用", "链接失效", "无数据", "未判定", "已归档"].includes(b.label)
      || b.label.startsWith("含失效 ") || b.label.startsWith("含未判定 "));
    const manifestFiles = (props.domain?.adapter === "wuwa" || props.domain?.adapter === "perfectworld_patcher") && props.mode === "files";
    const available = Number(row.states.available || 0);
    const unknown = Number(row.states.unknown || 0);
    if (!hasStatus && manifestFiles && unknown > 0) {
      result.push({ label: available > 0 ? `含未判定 ${unknown}` : "未判定", tone: available > 0 ? "amber" : "slate" });
    } else if (!hasStatus) {
      const kind = props.mode ? artifactKindForMode(props.mode) : "";
      const count = manifestFiles ? artifactCountForMode(row.item, "files", props.domain?.adapter) : kind ? row.item.artifact_kinds?.[kind]?.count || 0 : 0;
      const modeHasKind = Boolean(kind || manifestFiles);
      if (modeHasKind && count === 0 && !versionSupportsMode(row.item, props.mode || "", props.domain?.adapter)) {
        result.push({ label: "无数据", tone: "slate" });
      } else if (isRowUnavailable(row)) {
        result.push({ label: props.domain?.adapter === "android" ? "不可用" : "链接失效", tone: "red" });
      } else if (available > 0 && unknown > 0) {
        result.push({ label: `含未判定 ${unknown}`, tone: "amber" });
      } else if (available > 0) {
        result.push({ label: "可用", tone: "green" });
      } else {
        result.push({ label: "未判定", tone: "slate" });
      }
    }
  }

  return result;
}

function groupMetaText(group: { name: string; rows: Array<{ base: string; item: VersionSummary; states: Record<string, number> }> }): string {
  if (!props.showAvailability) return `${group.rows.length} 个版本`;

  let availableCount = 0;
  let unavailableCount = 0;
  let unknownCount = 0;

  for (const row of group.rows) {
    const available = Number(row.states.available || 0);

    if (isRowUnavailable(row)) {
      unavailableCount++;
    } else if (available > 0) {
      availableCount++;
    } else {
      unknownCount++;
    }
  }

  const parts: string[] = [];
  if (availableCount > 0) {
    parts.push(`${availableCount} 可用`);
  }
  if (unavailableCount > 0) {
    parts.push(`${unavailableCount} 不可用`);
  }
  if (unknownCount > 0) {
    parts.push(`${unknownCount} 未判定`);
  }
  return parts.join(" · ") || `${group.rows.length} 个版本`;
}

function toggleFamily(value: string): void {
  const next = new Set(collapsed.value);
  next.has(value) ? next.delete(value) : next.add(value);
  collapsed.value = next;
}

function choose(value: string): void {
  open.value = false;
  filterQuery.value = "";
  emit("select", value);
}

function onDocumentClick(event: MouseEvent): void {
  if (!root.value?.contains(event.target as Node)) {
    open.value = false;
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    open.value = false;
  }
}

const isMobile = ref(false);
function updateMobileStatus() {
  isMobile.value = typeof window !== "undefined" && window.innerWidth <= 860;
}

watch(
  () => open.value && isMobile.value,
  (shouldLock) => {
    if (typeof document !== "undefined") {
      if (shouldLock) {
        document.body.style.overflow = "hidden";
        document.body.style.touchAction = "none";
      } else {
        document.body.style.overflow = "";
        document.body.style.touchAction = "";
      }
    }
  },
  { immediate: true },
);

onMounted(() => {
  updateMobileStatus();
  window.addEventListener("resize", updateMobileStatus);
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onKey);
});

onBeforeUnmount(() => {
  if (typeof document !== "undefined") {
    document.body.style.overflow = "";
    document.body.style.touchAction = "";
  }
  window.removeEventListener("resize", updateMobileStatus);
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div ref="root" class="version-picker">
    <span class="version-picker-label">版本选择</span>
    <button
      class="select-button"
      type="button"
      :aria-expanded="open"
      @click.stop="open = !open"
    >
      <span>{{ selectedLabel || '—' }}</span>
      <svg class="chevron-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <!-- 桌面端原位下拉菜单 -->
    <div v-if="open && !isMobile" class="version-menu" @wheel.stop>
      <div v-if="versions.length > 8" class="version-search-wrap" @click.stop>
        <input
          v-model="filterQuery"
          class="version-search-input"
          placeholder="🔍 搜索版本"
          type="search"
          autofocus
        />
      </div>
      <div class="version-menu-scroll" @wheel.stop>
        <div
          v-for="group in pickerRows"
          :key="group.name"
          class="version-group"
          :class="{ collapsed: collapsed.has(group.name) }"
        >
          <button
            class="version-group-head"
            type="button"
            :aria-expanded="!collapsed.has(group.name)"
            @click.stop="toggleFamily(group.name)"
          >
            <span class="group-title">
              <span class="group-chevron"></span>
              <strong>{{ group.name }} {{ groupSuffix() }}</strong>
            </span>
            <span class="group-meta">{{ groupMetaText(group) }}</span>
          </button>
          <div v-if="!collapsed.has(group.name)" class="version-group-body">
            <button
              v-for="row in group.rows"
              :key="row.item.version"
              class="version-row"
              :class="{ selected: row.item.version === modelValue }"
              type="button"
              @click="choose(row.item.version)"
            >
              <!-- 列 1: 版本号与最新/补丁标识 -->
              <div class="version-number-col">
                <span class="version-number" :class="{ 'is-patch': isPatchVersion(row.base) }">{{ row.base }}</span>
                <span v-if="isLatestVersion(row.item.version)" class="latest-badge">最新</span>
                <span v-else-if="isPatchVersion(row.base)" class="patch-badge">补丁</span>
              </div>

              <!-- 列 2: 更新时间 -->
              <span class="version-date-col">
                <span v-if="timeBadge(row)" class="cap slate">{{ timeBadge(row)!.label }}</span>
              </span>

              <!-- 列 3: 原子微标组 -->
              <span class="caps">
                <span
                  v-for="cap in atomicBadges(row)"
                  :key="`${row.item.version}:${cap.label}`"
                  class="cap micro-cap"
                  :class="cap.tone"
                >
                  {{ cap.label }}
                </span>
              </span>

              <!-- 列 4: 独立勾选占位 -->
              <span class="version-row-check-slot">
                <span v-if="row.item.version === modelValue" class="version-check-icon" aria-hidden="true">✓</span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 移动端全屏遮罩原生底部抽屉 (Bottom Sheet) -->
    <Teleport to="body">
      <div
        v-if="open && isMobile"
        class="mobile-version-sheet-backdrop"
        @click="open = false"
        @touchmove.prevent
      >
        <div class="mobile-version-sheet" @click.stop>
          <div class="sheet-header" @touchmove.prevent>
            <div class="sheet-handle"></div>
            <div class="sheet-title-row">
              <span class="sheet-title">选择游戏版本</span>
              <button class="sheet-close-btn" type="button" @click="open = false">✕</button>
            </div>
            <div v-if="versions.length > 5" class="sheet-search-wrap">
              <svg class="sheet-search-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="7" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                v-model="filterQuery"
                class="sheet-search-input"
                placeholder="🔍 搜索版本"
                type="search"
              />
            </div>
          </div>
          <div class="sheet-body-scroll" @touchmove.stop>
            <div
              v-for="group in pickerRows"
              :key="group.name"
              class="sheet-group"
              :class="{ collapsed: collapsed.has(group.name) }"
            >
              <button
                class="sheet-group-head"
                type="button"
                @click.stop="toggleFamily(group.name)"
              >
                <span class="group-title">
                  <span class="group-arrow">{{ collapsed.has(group.name) ? '▶' : '▼' }}</span>
                  <strong>{{ group.name }} {{ groupSuffix() }}</strong>
                </span>
                <span class="group-meta">{{ groupMetaText(group) }}</span>
              </button>
              <div v-if="!collapsed.has(group.name)" class="sheet-group-body">
                <button
                  v-for="row in group.rows"
                  :key="row.item.version"
                  class="sheet-row"
                  :class="{ selected: row.item.version === modelValue }"
                  type="button"
                  @click="choose(row.item.version)"
                >
                  <div class="sheet-row-top">
                    <div class="sheet-ver-box">
                      <span class="sheet-version-num" :class="{ 'is-patch': isPatchVersion(row.base) }">{{ row.base }}</span>
                      <span v-if="isLatestVersion(row.item.version)" class="latest-badge">最新</span>
                      <span v-else-if="isPatchVersion(row.base)" class="patch-badge">补丁</span>
                    </div>
                    <span v-if="timeBadge(row)" class="sheet-date">{{ timeBadge(row)!.label }}</span>
                  </div>
                  <div class="sheet-row-bottom">
                    <span class="caps">
                      <span
                        v-for="cap in atomicBadges(row)"
                        :key="`${row.item.version}:${cap.label}`"
                        class="cap micro-cap"
                        :class="cap.tone"
                      >
                        {{ cap.label }}
                      </span>
                    </span>
                    <span v-if="row.item.version === modelValue" class="sheet-check-icon">✓</span>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
