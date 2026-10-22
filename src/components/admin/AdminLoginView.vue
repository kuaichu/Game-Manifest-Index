<script setup lang="ts">
const token = defineModel<string>({ required: true });

defineProps<{
  error: string;
  loading: boolean;
}>();

const emit = defineEmits<{
  (event: "submit"): void;
  (event: "back"): void;
}>();
</script>

<template>
  <div class="admin-login-layout">
    <header class="login-topbar">
      <button class="login-back" type="button" @click="emit('back')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <line x1="19" y1="12" x2="5" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
        <span>返回前台</span>
      </button>
      <div class="login-topbar-meta">
        <img src="/project-icon.svg" alt="" />
        <span>GMI / ADMIN CONSOLE</span>
      </div>
    </header>

    <div class="login-shell">
      <section class="login-intro" aria-label="控制台说明">
        <div class="login-brand-lockup">
          <img class="login-brand-icon" src="/project-icon.svg" alt="GMI" />
          <div>
            <p class="login-eyebrow">GAME MANIFEST INDEX</p>
            <h1>归档管理控制台</h1>
          </div>
        </div>
        <p class="login-intro-text">管理游戏入口、归档模块、版本内容与链接探活。</p>
        <ul class="login-feature-list">
          <li>
            <span>01</span>
            <div>
              <strong>版本与文件索引</strong>
              <small>游戏入口、归档模块、版本内容</small>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>链接可用性</strong>
              <small>探活证据、下载状态与失效记录</small>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>采集与探活任务</strong>
              <small>新版本发现、批量探活与计划</small>
            </div>
          </li>
        </ul>
        <p class="login-intro-foot">内部系统 · 仅限授权管理员访问</p>
      </section>

      <form class="admin-login-card" @submit.prevent="emit('submit')">
        <div class="login-card-head">
          <span class="login-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </span>
          <div>
            <p class="login-card-eyebrow">SECURE SIGN-IN</p>
            <h2>管理员登录</h2>
            <p>输入管理 Token 以进入控制台</p>
          </div>
        </div>

        <div v-if="error" class="admin-alert error">{{ error }}</div>

        <label class="login-field" for="admin-token-input">
          <span>管理凭证</span>
          <div class="login-input-shell">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <circle cx="7.5" cy="15.5" r="4.5" />
              <path d="m10.5 12.5 8-8m-2.5 0 2.5 2.5" />
            </svg>
            <input
              id="admin-token-input"
              v-model="token"
              type="password"
              placeholder="输入管理 Token"
              autocomplete="current-password"
              required
              autofocus
            />
          </div>
        </label>

        <button class="login-submit" type="submit" :disabled="loading">
          <span>{{ loading ? '验证中…' : '进入控制台' }}</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <line x1="5" y1="12" x2="19" y2="12" />
            <polyline points="12 5 19 12 12 19" />
          </svg>
        </button>

        <p class="login-security-note">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          凭证仅用于本次管理会话，不会发送到第三方。
        </p>
      </form>
    </div>

    <footer class="login-footbar">
      <span>GMI · Game Manifest Index</span>
      <span>Admin Console</span>
    </footer>
  </div>
</template>
