<script setup lang="ts">
import { toRef } from "vue";
import { getFileTimeSourceDescription } from "../../admin-format";
import type { VersionDraft } from "../../admin-version-editor";

const props = defineProps<{
  draft: VersionDraft;
  isCreateMode: boolean;
  fileTimeRaw: string;
  fileTimeInputValue: string;
  fileTimeLabel: string;
  fileTimeUnparsable: boolean;
}>();

const emit = defineEmits<{
  (event: "clear-file-time"): void;
  (event: "file-time-input", payload: Event): void;
}>();

const draft = toRef(props, "draft");
</script>

<template>
  <!-- 基本信息 -->
  <div class="form-section-card">
    <div class="section-card-title">基本信息</div>
    <div
      class="admin-field-grid"
      :class="isCreateMode ? 'compact-4col' : 'compact-3col'"
    >
      <label v-if="isCreateMode" class="admin-field">
        <span class="field-label">版本号 <small class="field-sublabel">version</small> <b class="text-rose">*</b></span>
        <input
          v-model="draft.version"
          class="admin-input"
          placeholder="例如: 7.1.0"
          required
        />
      </label>

      <label class="admin-field">
        <span class="field-label">渠道</span>
        <input
          v-model="draft.channel"
          class="admin-input"
          placeholder="official / bilibili"
          required
        />
      </label>

      <label class="admin-field">
        <span class="field-label">版本代码</span>
        <input
          v-model.number="draft.version_code"
          class="admin-input"
          type="number"
          placeholder="例如: 12345"
        />
      </label>

      <div class="admin-field">
        <div class="field-header-row">
          <span class="field-label">
            文件时间
          </span>
          <button
            v-if="draft.file_created_at_override"
            class="field-mini-btn"
            type="button"
            title="清空后将由后端自动识别 URL 或 Last-Modified 时间"
            @click="emit('clear-file-time')"
          >
            清空
          </button>
        </div>
        <input
          class="admin-input"
          type="datetime-local"
          :value="fileTimeInputValue"
          @input="emit('file-time-input', $event)"
        />
        <small v-if="fileTimeUnparsable" class="field-tip field-tip-warning">
          无法识别当前值（{{ fileTimeRaw }}），请重新选择或清空。
        </small>
        <small v-else class="field-tip">
          {{ fileTimeLabel ? `当前 ${fileTimeLabel}，按 UTC 保存` : '留空时按 URL / Last-Modified 自动识别' }}
          · 来源：{{ getFileTimeSourceDescription(draft.file_created_at_override, draft.artifacts[0]?.urls[0]?.url) }}
        </small>
      </div>
    </div>
  </div>
</template>
