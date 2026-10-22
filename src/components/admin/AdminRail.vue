<script setup lang="ts">
import AdminIcon from "./AdminIcon.vue";

export type AdminRailTab = "games" | "domains" | "content" | "probe";

defineProps<{ activeTab: AdminRailTab }>();

const emit = defineEmits<{
  (event: "select", tab: AdminRailTab): void;
  (event: "logout"): void;
}>();
</script>

<template>
  <aside class="admin-rail">
    <div class="rail-brand" title="Game Manifest Index 控制台">
      <div class="rail-logo-box">
        <span>GMI</span>
      </div>
    </div>

    <div class="rail-nav-list">
      <button
        class="rail-item"
        :class="{ active: activeTab === 'games' }"
        type="button"
        title="游戏入口管理"
        @click="emit('select', 'games')"
      >
        <AdminIcon name="game" />
        <span class="rail-label">游戏</span>
      </button>

      <button
        class="rail-item"
        :class="{ active: activeTab === 'domains' }"
        type="button"
        title="数据模块管理"
        @click="emit('select', 'domains')"
      >
        <AdminIcon name="box" />
        <span class="rail-label">模块</span>
      </button>

      <button
        class="rail-item"
        :class="{ active: activeTab === 'content' }"
        type="button"
        title="版本内容控制"
        @click="emit('select', 'content')"
      >
        <AdminIcon name="contents" />
        <span class="rail-label">版本</span>
      </button>

      <button
        class="rail-item"
        :class="{ active: activeTab === 'probe' }"
        type="button"
        title="采集与探活监控"
        @click="emit('select', 'probe')"
      >
        <AdminIcon name="pulse" />
        <span class="rail-label">监控</span>
      </button>
    </div>

    <div class="rail-foot">
      <button class="rail-action-btn" type="button" title="退出登录" @click="emit('logout')">
        <AdminIcon name="logout" />
        <span class="rail-label">退出</span>
      </button>
    </div>
  </aside>
</template>
