<script setup lang="ts">
import { toRef } from "vue";
import { formatBytes } from "../../admin-format";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  getChecksumSummaryText,
} from "../../admin-version-editor";
import type { ProbeUrlResult } from "../../types";

const props = defineProps<{
  draft: VersionDraft;
  checksumsOpen: boolean;
  urlProbeMap: Record<string, { loading: boolean; result?: ProbeUrlResult }>;
}>();

const emit = defineEmits<{
  (event: "toggle-checksums"): void;
  (event: "extract-name", artifact: EditableArtifactDraft): void;
  (event: "sync-json"): void;
  (event: "url-change", artifact: EditableArtifactDraft, url: string): void;
  (event: "copy-url", url: string): void;
  (event: "open-url", url: string): void;
  (event: "probe-url", url: string): void;
}>();

const draft = toRef(props, "draft");
</script>

<template>
  <!-- APK 文件平铺卡片 -->
  <div class="form-section-card apk-file-card">
    <div class="section-card-title">APK 文件</div>

    <div class="admin-field-grid">
      <div class="admin-field">
        <div class="field-header-row">
          <span class="field-label">文件名</span>
          <button
            v-if="draft.artifacts[0].urls[0]?.url"
            class="field-mini-btn"
            type="button"
            title="根据当前 URL 自动解析并填入文件名"
            @click="emit('extract-name', draft.artifacts[0])"
          >
            根据 URL 填写文件名
          </button>
        </div>
        <input
          v-model="draft.artifacts[0].name"
          class="admin-input"
          placeholder="例如: yuanshen_7.1.0.apk"
          required
          @input="emit('sync-json')"
        />
      </div>

      <label class="admin-field">
        <span class="field-label">文件大小</span>
        <input
          v-model.number="draft.artifacts[0].size"
          class="admin-input"
          type="number"
          min="0"
          placeholder="字节数"
          @input="emit('sync-json')"
        />
        <small class="field-tip">
          当前换算：<strong>{{ formatBytes(draft.artifacts[0].size) }}</strong>
        </small>
      </label>
    </div>

    <!-- URL 独占一行 -->
    <div class="admin-field full-width url-line-field">
      <span class="field-label">下载 URL</span>
      <div class="url-input-action-row">
        <input
          v-model="draft.artifacts[0].urls[0].url"
          class="admin-input text-mono url-long-input"
          placeholder="https://..."
          required
          @input="emit('url-change', draft.artifacts[0], draft.artifacts[0].urls[0].url)"
        />
        <button
          class="url-action-pill-btn"
          type="button"
          title="复制下载链接"
          @click="emit('copy-url', draft.artifacts[0].urls[0].url)"
        >
          复制
        </button>
        <button
          class="url-action-pill-btn"
          type="button"
          title="在新窗口打开"
          @click="emit('open-url', draft.artifacts[0].urls[0].url)"
        >
          ↗ 打开
        </button>
        <button
          class="url-action-pill-btn"
          type="button"
          title="仅检查网络连通性，不修改或保存任何数据"
          :disabled="urlProbeMap[draft.artifacts[0].urls[0].url]?.loading"
          @click="emit('probe-url', draft.artifacts[0].urls[0].url)"
        >
          {{ urlProbeMap[draft.artifacts[0].urls[0].url]?.loading ? '测试中…' : '测试 URL' }}
        </button>
      </div>
    </div>

    <!-- 校验值折叠面板 -->
    <div class="checksums-collapse-section">
      <button
        class="collapse-toggle-btn"
        type="button"
        @click="emit('toggle-checksums')"
      >
        <span class="chevron" :class="{ open: checksumsOpen }">▶</span>
        <span class="collapse-title">文件校验值</span>
        <span v-if="getChecksumSummaryText(draft.checksum_etag, draft.checksum_crc64, draft.checksum_md5)" class="checksum-tag">
          {{ getChecksumSummaryText(draft.checksum_etag, draft.checksum_crc64, draft.checksum_md5) }}
        </span>
        <span v-else class="checksum-tag-empty">未配置</span>
      </button>

      <div v-if="checksumsOpen" class="collapse-fields-grid">
        <label class="admin-field">
          <span class="field-label">ETag</span>
          <input
            v-model="draft.checksum_etag"
            class="admin-input text-mono"
            placeholder="例如: &quot;abcd1234...&quot;"
          />
        </label>
        <label class="admin-field">
          <span class="field-label">CRC64</span>
          <input
            v-model="draft.checksum_crc64"
            class="admin-input text-mono"
            placeholder="例如: 15852710230531907"
          />
        </label>
        <label class="admin-field">
          <span class="field-label">MD5</span>
          <input
            v-model="draft.checksum_md5"
            class="admin-input text-mono"
            placeholder="32位 MD5 字符串"
          />
        </label>
      </div>
    </div>
  </div>
</template>
