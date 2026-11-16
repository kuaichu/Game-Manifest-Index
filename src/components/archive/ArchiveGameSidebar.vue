<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { iconForGame } from "../../archive-artifact-helpers";
import { gameIcons } from "../../game-icons";
import { publisherGroups } from "../../game-meta";
import type { Game } from "../../types";

const props = defineProps<{
  games: Game[];
  gameId: string;
}>();

const emit = defineEmits<{
  (e: "select-game", gameId: string): void;
}>();

const sidebarGameSearch = ref("");
const railGroups = computed(() => publisherGroups(props.games));

function filterGroups(search: string) {
  const query = search.trim().toLowerCase();
  if (!query) return railGroups.value;

  return railGroups.value
    .map((group) => ({
      publisher: group.publisher,
      games: group.games.filter(
        (g) =>
          g.name.toLowerCase().includes(query) ||
          g.sub_name.toLowerCase().includes(query) ||
          g.id.toLowerCase().includes(query),
      ),
    }))
    .filter((group) => group.games.length > 0);
}

const filteredRailGroups = computed(() => filterGroups(sidebarGameSearch.value));

// Small screens: the bar shows the current game; tapping it opens a drawer with
// search and the full grouped list instead of a row of unlabeled icons.
const drawerOpen = ref(false);
const drawerSearch = ref("");
const currentGame = computed(() => props.games.find((item) => item.id === props.gameId) || null);
const drawerGroups = computed(() => filterGroups(drawerSearch.value));

function selectFromDrawer(id: string): void {
  drawerOpen.value = false;
  emit("select-game", id);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") drawerOpen.value = false;
}

watch(drawerOpen, (open) => {
  if (open) {
    window.addEventListener("keydown", onKeydown);
  } else {
    window.removeEventListener("keydown", onKeydown);
    drawerSearch.value = "";
  }
});
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

function shortName(item: Game): string {
  return item.id.slice(0, 3).toUpperCase();
}

function iconFor(id: string): string | undefined {
  return iconForGame(props.games, id);
}

function useFallbackIcon(event: Event, id: string): void {
  const image = event.currentTarget as HTMLImageElement;
  const fallback = gameIcons[id];
  if (fallback && image.src !== fallback) image.src = fallback;
  else image.hidden = true;
}
</script>

<template>
  <aside class="game-sidebar" aria-label="游戏导航">
    <div class="sidebar-header">
      <div class="sidebar-brand">
        <img class="brand-badge" src="/project-icon.svg" alt="GMI" />
        <div class="brand-info">
          <strong>游戏资源索引</strong>
          <span>Game Manifest Index</span>
        </div>
      </div>
      <div class="sidebar-search-box">
        <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          v-model="sidebarGameSearch"
          class="sidebar-search-input"
          placeholder="搜索游戏名称 / 代号…"
        />
        <span v-if="sidebarGameSearch" class="clear-search-btn" @click="sidebarGameSearch = ''">✕</span>
      </div>
      <button
        type="button"
        class="mobile-game-trigger"
        :aria-expanded="drawerOpen"
        aria-haspopup="dialog"
        @click="drawerOpen = !drawerOpen"
      >
        <span class="mobile-game-icon">
          <img v-if="currentGame && iconFor(currentGame.id)" :src="iconFor(currentGame.id)" alt="" @error="useFallbackIcon($event, currentGame.id)" />
          <span v-else-if="currentGame">{{ shortName(currentGame) }}</span>
        </span>
        <span class="mobile-game-name">{{ currentGame?.name || "选择游戏" }}</span>
        <span class="mobile-game-switch">切换游戏<span class="mobile-game-caret" :class="{ open: drawerOpen }" aria-hidden="true">▾</span></span>
      </button>
    </div>

    <!-- Teleported: the mobile bar uses backdrop-filter, which would trap position: fixed. -->
    <Teleport to="body">
    <div v-if="drawerOpen" class="mobile-game-drawer" role="dialog" aria-label="选择游戏" @click.self="drawerOpen = false">
      <div class="mobile-drawer-panel">
        <div class="mobile-drawer-search">
          <input v-model="drawerSearch" type="search" placeholder="搜索游戏名称 / 代号…" aria-label="搜索游戏" />
          <button v-if="drawerSearch" type="button" aria-label="清除搜索" @click="drawerSearch = ''">✕</button>
        </div>
        <div class="mobile-drawer-list">
          <p v-if="!drawerGroups.length" class="mobile-drawer-empty">未找到匹配的游戏</p>
          <section v-for="group in drawerGroups" :key="group.publisher" class="mobile-drawer-group">
            <h3>{{ group.publisher }} <small>{{ group.games.length }}</small></h3>
            <button
              v-for="item in group.games"
              :key="item.id"
              type="button"
              class="mobile-drawer-game"
              :class="{ active: item.id === gameId }"
              @click="selectFromDrawer(item.id)"
            >
              <span class="mobile-game-icon">
                <img v-if="iconFor(item.id)" :src="iconFor(item.id)" alt="" @error="useFallbackIcon($event, item.id)" />
                <span v-else>{{ shortName(item) }}</span>
              </span>
              <span class="mobile-drawer-text">
                <strong>{{ item.name }}</strong>
                <small>{{ item.sub_name || item.id }}</small>
              </span>
            </button>
          </section>
        </div>
      </div>
    </div>

    <div class="sidebar-games-scroll">
      <div v-if="filteredRailGroups.length === 0" class="sidebar-empty">
        未找到匹配的游戏
      </div>
      <div v-for="group in filteredRailGroups" :key="group.publisher" class="publisher-group">
        <div class="publisher-header">
          <span>{{ group.publisher }}</span>
          <small class="publisher-count">{{ group.games.length }}</small>
        </div>
        <div class="publisher-game-list">
          <button
            v-for="item in group.games"
            :key="item.id"
            class="game-nav-item"
            :class="{ active: item.id === gameId }"
            type="button"
            @click="emit('select-game', item.id)"
          >
            <div class="game-item-icon-box">
              <img
                v-if="iconFor(item.id)"
                :class="{ 'endfield-icon': item.id === 'endfield' }"
                :src="iconFor(item.id)"
                :alt="item.name"
                @error="useFallbackIcon($event, item.id)"
              />
              <span v-else>{{ shortName(item) }}</span>
            </div>
            <div class="game-item-text">
              <strong class="game-item-name">{{ item.name }}</strong>
              <span class="game-item-sub">{{ item.sub_name || item.id }}</span>
            </div>
          </button>
        </div>
      </div>
    </div>
    </Teleport>
  </aside>
</template>

<style scoped>
.mobile-game-trigger,
.mobile-game-drawer {
  display: none;
}

@media (max-width: 860px) {
  /* The icon rail is replaced by the current-game button + drawer. */
  .sidebar-games-scroll {
    display: none;
  }

  .sidebar-header {
    flex: 1;
    min-width: 0;
  }

  .mobile-game-trigger {
    display: flex;
    flex: 1;
    min-width: 0;
    align-items: center;
    gap: 8px;
    height: 36px;
    padding: 0 10px 0 4px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 9px;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text);
    text-align: left;
  }

  .mobile-game-trigger[aria-expanded="true"] {
    border-color: rgba(56, 189, 248, 0.45);
    background: rgba(56, 189, 248, 0.1);
  }

  .mobile-game-icon {
    display: inline-grid;
    flex: 0 0 auto;
    place-items: center;
    width: 28px;
    height: 28px;
    overflow: hidden;
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.06);
    color: var(--muted);
    font-size: 10px;
    font-weight: 800;
  }

  .mobile-game-icon img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .mobile-game-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: 13.5px;
    font-weight: 800;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-game-switch {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 4px;
    color: var(--muted);
    font-size: 11.5px;
    font-weight: 700;
  }

  .mobile-game-caret {
    transition: transform 0.18s ease;
  }

  .mobile-game-caret.open {
    transform: rotate(180deg);
  }

  .mobile-game-drawer {
    position: fixed;
    inset: 50px 0 0;
    z-index: 1001;
    display: block;
    background: rgba(2, 6, 14, 0.55);
    animation: drawer-fade 0.16s ease-out;
  }

  .mobile-drawer-panel {
    display: flex;
    flex-direction: column;
    max-height: min(78vh, 640px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 0 0 14px 14px;
    background: rgba(11, 17, 30, 0.98);
    box-shadow: 0 16px 32px rgba(0, 0, 0, 0.5);
    animation: drawer-slide 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }

  .mobile-drawer-search {
    position: relative;
    padding: 10px 12px 8px;
  }

  .mobile-drawer-search input {
    width: 100%;
    height: 38px;
    padding: 0 34px 0 12px;
    border: 1px solid var(--line);
    border-radius: 9px;
    outline: 0;
    background: var(--panel-deep);
    color: var(--text);
    font-size: 14px;
  }

  .mobile-drawer-search input:focus {
    border-color: var(--blue);
  }

  .mobile-drawer-search button {
    position: absolute;
    top: 50%;
    right: 20px;
    transform: translateY(-40%);
    color: var(--muted);
    font-size: 12px;
  }

  .mobile-drawer-list {
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0 8px 12px;
  }

  .mobile-drawer-group h3 {
    margin: 10px 6px 4px;
    color: var(--muted);
    font-size: 11.5px;
    font-weight: 800;
  }

  .mobile-drawer-group h3 small {
    margin-left: 4px;
    opacity: 0.7;
  }

  .mobile-drawer-game {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 10px;
    min-height: 46px;
    padding: 6px;
    border: 1px solid transparent;
    border-radius: 9px;
    color: var(--text);
    text-align: left;
  }

  .mobile-drawer-game .mobile-game-icon {
    width: 32px;
    height: 32px;
  }

  .mobile-drawer-game.active {
    border-color: rgba(56, 189, 248, 0.35);
    background: rgba(56, 189, 248, 0.12);
  }

  .mobile-drawer-text {
    display: grid;
    min-width: 0;
  }

  .mobile-drawer-text strong,
  .mobile-drawer-text small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-drawer-text strong {
    font-size: 13.5px;
  }

  .mobile-drawer-text small {
    color: var(--muted);
    font-size: 11.5px;
  }

  .mobile-drawer-empty {
    margin: 12px 6px;
    color: var(--muted);
    font-size: 13px;
  }
}

@keyframes drawer-fade {
  from { opacity: 0; }
}

@keyframes drawer-slide {
  from { transform: translateY(-12px); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .mobile-game-drawer,
  .mobile-drawer-panel {
    animation: none;
  }
}
</style>
