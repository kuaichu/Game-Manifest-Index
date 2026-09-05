<script setup lang="ts">
import { toRef } from "vue";

interface ArtifactUrl {
  url: string;
  priority: number;
  source_kind: string;
}

interface PcArtifactDraft {
  kind: string;
  name: string;
  part: number;
  size: number;
  package_type: string;
  delivery_mode: string;
  component: string;
  language: string;
  route_from: string;
  route_to: string;
  decompressed_size: number | null;
  checksum_type: string;
  checksum_value: string;
  urls: ArtifactUrl[];
}

const props = defineProps<{
  artifact: PcArtifactDraft;
  formatBytes: (bytes: number | null | undefined) => string;
  forceExtractArtifactName: (artifact: PcArtifactDraft) => void;
  syncArtifactsToJson: () => void;
}>();

const artifact = toRef(props, "artifact");
</script>

<template>
  <div class="pc-artifact-section">
    <div class="pc-artifact-section-title">资源类型</div>
    <div class="admin-field-grid compact-4col">
      <label class="admin-field">
        <span class="field-label">类型 <small class="field-sublabel">kind</small></span>
        <select v-model="artifact.kind" class="admin-input" @change="syncArtifactsToJson">
          <option value="package">package</option>
          <option value="patch">patch</option>
        </select>
      </label>
      <label class="admin-field">
        <span class="field-label">包类型 <small class="field-sublabel">package_type</small></span>
        <input v-model="artifact.package_type" class="admin-input" placeholder="full / segment / differential" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">交付方式 <small class="field-sublabel">delivery_mode</small></span>
        <input v-model="artifact.delivery_mode" class="admin-input" placeholder="direct / archive / file_manifest" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">组件 <small class="field-sublabel">component</small></span>
        <input v-model="artifact.component" class="admin-input" placeholder="game / voice" @input="syncArtifactsToJson" />
      </label>
    </div>
  </div>

  <div class="pc-artifact-section">
    <div class="pc-artifact-section-title">文件信息</div>
    <div class="admin-field-grid compact-4col">
      <div class="admin-field span-2">
        <div class="field-header-row">
          <span class="field-label">文件名</span>
          <button v-if="artifact.urls[0]?.url" class="tool-pill-btn" type="button" @click="forceExtractArtifactName(artifact)">根据 URL 填写</button>
        </div>
        <input v-model="artifact.name" class="admin-input" placeholder="文件名或 manifest 名称" @input="syncArtifactsToJson" />
      </div>
      <label class="admin-field">
        <span class="field-label">分卷 <small class="field-sublabel">part</small></span>
        <input v-model.number="artifact.part" class="admin-input" type="number" min="1" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">大小 <small class="field-sublabel">size</small></span>
        <input v-model.number="artifact.size" class="admin-input" type="number" min="0" @input="syncArtifactsToJson" />
        <small class="field-tip">{{ formatBytes(artifact.size) }}</small>
      </label>
    </div>
  </div>

  <div class="pc-artifact-section">
    <div class="pc-artifact-section-title">补丁路由</div>
    <div class="admin-field-grid compact-4col">
      <label class="admin-field">
        <span class="field-label">语言 <small class="field-sublabel">language</small></span>
        <input v-model="artifact.language" class="admin-input" placeholder="zh-cn / en-us，可留空" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">来源版本 <small class="field-sublabel">route_from</small></span>
        <input v-model="artifact.route_from" class="admin-input" placeholder="patch 起始版本" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">目标版本 <small class="field-sublabel">route_to</small></span>
        <input v-model="artifact.route_to" class="admin-input" placeholder="patch 目标版本" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field">
        <span class="field-label">解包大小 <small class="field-sublabel">decompressed_size</small></span>
        <input v-model.number="artifact.decompressed_size" class="admin-input" type="number" min="0" placeholder="可留空" @input="syncArtifactsToJson" />
      </label>
    </div>
  </div>

  <div class="pc-artifact-section">
    <div class="pc-artifact-section-title">校验信息</div>
    <div class="admin-field-grid compact-3col">
      <label class="admin-field">
        <span class="field-label">校验类型 <small class="field-sublabel">checksum_type</small></span>
        <input v-model="artifact.checksum_type" class="admin-input" placeholder="md5 / sha256 / crc64" @input="syncArtifactsToJson" />
      </label>
      <label class="admin-field span-2">
        <span class="field-label">校验值 <small class="field-sublabel">checksum_value</small></span>
        <input v-model="artifact.checksum_value" class="admin-input text-mono" placeholder="可留空" @input="syncArtifactsToJson" />
      </label>
    </div>
  </div>

</template>
