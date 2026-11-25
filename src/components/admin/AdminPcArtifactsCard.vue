<script setup lang="ts">
import { toRef } from "vue";
import AdminPcArtifactFields from "./AdminPcArtifactFields.vue";
import { formatBytes } from "../../admin-format";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  pcArtifactSummaryTags,
  pcArtifactTitle,
} from "../../admin-version-editor";
import type { ProbeUrlResult } from "../../types";

const props = defineProps<{
  draft: VersionDraft;
  overview: {
    total: number;
    packageCount: number;
    patchCount: number;
    urlCount: number;
    totalSize: number;
  };
  urlProbeMap: Record<string, { loading: boolean; result?: ProbeUrlResult }>;
}>();

const emit = defineEmits<{
  (event: "switch-mode", mode: "visual" | "json"): void;
  (event: "format-json"): void;
  (event: "add-artifact"): void;
  (event: "remove-artifact", index: number): void;
  (event: "extract-name", artifact: EditableArtifactDraft): void;
  (event: "sync-json"): void;
  (event: "add-url", artifactIndex: number): void;
  (event: "remove-url", artifactIndex: number, urlIndex: number): void;
  (event: "url-change", artifact: EditableArtifactDraft, url: string): void;
  (event: "copy-url", url: string): void;
  (event: "probe-url", target: EditableArtifactDraft["urls"][number]): void;
}>();

const draft = toRef(props, "draft");
</script>

<template>
  <div class="form-section-card pc-artifacts-card">
    <div class="section-card-header pc-artifacts-head">
      <div class="card-title-group">
        <h3>PC 资源文件</h3>
        <p class="card-subtitle">编辑 package / patch 资源、分卷、路由、manifest/source 与下载 URL。</p>
      </div>
      <div class="section-header-tools artifact-mode-tabs">
        <button
          class="tool-pill-btn"
          :class="{ active: draft.artifactsMode === 'visual' }"
          type="button"
          @click="emit('switch-mode', 'visual')"
        >
          列表
        </button>
        <button
          class="tool-pill-btn"
          :class="{ active: draft.artifactsMode === 'json' }"
          type="button"
          @click="emit('switch-mode', 'json')"
        >
          JSON
        </button>
        <button
          v-if="draft.artifactsMode === 'json'"
          class="tool-pill-btn"
          type="button"
          @click="emit('format-json')"
        >
          格式化
        </button>
        <button
          v-if="draft.artifactsMode === 'visual'"
          class="tool-pill-btn highlight"
          type="button"
          @click="emit('add-artifact')"
        >
          添加资源
        </button>
      </div>
    </div>

    <div class="pc-artifacts-overview">
      <div class="pc-overview-item">
        <span>资源总数</span>
        <strong>{{ overview.total }}</strong>
      </div>
      <div class="pc-overview-item">
        <span>Package</span>
        <strong>{{ overview.packageCount }}</strong>
      </div>
      <div class="pc-overview-item">
        <span>Patch</span>
        <strong>{{ overview.patchCount }}</strong>
      </div>
      <div class="pc-overview-item">
        <span>总大小</span>
        <strong>{{ formatBytes(overview.totalSize) }}</strong>
      </div>
      <div class="pc-overview-item">
        <span>有效 URL</span>
        <strong>{{ overview.urlCount }}</strong>
      </div>
    </div>

    <div v-if="draft.artifactsMode === 'json'" class="admin-field full-width pc-json-editor">
      <span class="field-label">Artifacts JSON</span>
      <div class="code-editor-container">
        <textarea
          v-model="draft.artifactsJson"
          class="admin-code-textarea pc-json-textarea"
          spellcheck="false"
        ></textarea>
      </div>
      <small class="field-tip">保存时会交给后端按 PC schema 重新校验和生成 artifact_id。</small>
    </div>

    <div v-else class="pc-artifact-list">
      <div
        v-for="(artifact, artIndex) in draft.artifacts"
        :key="`pc-artifact-${artIndex}`"
        class="pc-artifact-item"
      >
        <div class="pc-artifact-title-row">
          <div class="pc-artifact-title-main">
            <strong>{{ pcArtifactTitle(artifact, artIndex) }}</strong>
            <div class="pc-artifact-tags">
              <span
                v-for="tag in pcArtifactSummaryTags(artifact)"
                :key="tag"
                class="accordion-summary-tag"
              >
                {{ tag }}
              </span>
            </div>
          </div>
          <button
            class="tool-pill-btn danger"
            type="button"
            :disabled="draft.artifacts.length <= 1"
            @click="emit('remove-artifact', artIndex)"
          >
            删除资源
          </button>
        </div>

        <AdminPcArtifactFields
          :artifact="artifact"
          :format-bytes="formatBytes"
          :force-extract-artifact-name="(value) => emit('extract-name', value as EditableArtifactDraft)"
          :sync-artifacts-to-json="() => emit('sync-json')"
        />

        <div class="pc-artifact-section pc-url-list">
          <div class="field-header-row">
            <span class="field-label">下载 URL</span>
            <button class="tool-pill-btn highlight" type="button" @click="emit('add-url', artIndex)">添加 URL</button>
          </div>
          <div
            v-for="(urlItem, urlIndex) in artifact.urls"
            :key="`pc-url-${artIndex}-${urlIndex}`"
            class="pc-url-row"
          >
            <input
              v-model="urlItem.url"
              class="admin-input text-mono url-long-input"
              placeholder="https://..."
              @input="emit('url-change', artifact, urlItem.url)"
            />
            <input
              v-model.number="urlItem.priority"
              class="admin-input pc-priority-input"
              type="number"
              min="0"
              title="priority"
              @input="emit('sync-json')"
            />
            <input
              v-model="urlItem.source_kind"
              class="admin-input pc-source-kind-input"
              placeholder="official"
              title="source_kind"
              @input="emit('sync-json')"
            />
            <button class="url-action-pill-btn" type="button" @click="emit('copy-url', urlItem.url)">复制</button>
            <button class="url-action-pill-btn" type="button" @click="emit('probe-url', urlItem)">
              {{ urlProbeMap[urlItem.url]?.loading ? '测试中' : '测试' }}
            </button>
            <button
              class="tool-pill-btn danger"
              type="button"
              :disabled="artifact.urls.length <= 1"
              @click="emit('remove-url', artIndex, urlIndex)"
            >
              删除
            </button>
          </div>
        </div>

        <div class="pc-artifact-section">
          <div class="pc-artifact-section-title">元数据</div>
          <div class="admin-field-grid compact-3col">
            <label class="admin-field">
              <span class="field-label">Manifest</span>
              <textarea v-model="artifact.manifestJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="emit('sync-json')"></textarea>
            </label>
            <label class="admin-field">
              <span class="field-label">Source</span>
              <textarea v-model="artifact.sourceJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="emit('sync-json')"></textarea>
            </label>
            <label class="admin-field">
              <span class="field-label">附加属性</span>
              <textarea v-model="artifact.attributesJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="emit('sync-json')"></textarea>
            </label>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
