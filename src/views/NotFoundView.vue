<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <main class="not-found-view">
    <div class="file-icon" style="width: 64px; height: 64px; border-radius: 18px; margin-bottom: 8px;">
      <svg viewBox="0 0 24 24" style="width: 32px; height: 32px;" aria-hidden="true">
        <path d="M12 9v4M12 17h.01M5 19h14a2 2 0 0 0 1.84-2.75L13.74 4a2 2 0 0 0-3.5 0L3.16 16.25A2 2 0 0 0 5 19z" />
      </svg>
    </div>
    <p class="kicker">404 / Not Found</p>
    <h1>没有这个归档页面</h1>
    <p>链接可能已过期，或当前路径不属于公开查询产品。</p>
    <RouterLink class="tool-button" to="/" style="min-height: 42px; padding: 0 20px; font-size: 14px;">
      返回归档首页
    </RouterLink>
  </main>
</template>
