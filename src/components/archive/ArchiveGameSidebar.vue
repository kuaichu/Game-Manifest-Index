<script setup lang="ts">
import { computed, ref } from "vue";
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

const filteredRailGroups = computed(() => {
  const query = sidebarGameSearch.value.trim().toLowerCase();
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
});

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
  </aside>
</template>
