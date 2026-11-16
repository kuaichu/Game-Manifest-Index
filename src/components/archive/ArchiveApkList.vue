<script setup lang="ts">
import AvailabilityBadge from "../AvailabilityBadge.vue";
import {
  actionableCandidate,
  apkSourceSize,
  artifactDownloadUrl,
  preferredAvailableUrl,
  rawArtifactUrl,
} from "../../archive-artifact-helpers";
import { formatBytes, preferredArtifactAction } from "../../domain-presentation";
import type { ArchiveDomain, Artifact } from "../../types";

defineProps<{
  artifacts: Artifact[];
  domain: ArchiveDomain | null;
  suppressAvailabilityPresentation: boolean;
}>();

const emit = defineEmits<{
  (e: "copy-url", url?: string): void;
  (e: "copy-artifact-url", artifact: Artifact): void;
}>();
</script>

<template>
  <div class="file-list">
    <article v-for="(artifact, index) in artifacts" :key="artifact.id" class="file-card">
      <div class="file-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m21 8-9-5-9 5 9 5 9-5Z" />
          <path d="M3 8v8l9 5 9-5V8" />
          <path d="M12 13v8" />
        </svg>
      </div>
      <div class="file-main">
        <div class="file-title">
          <span class="pill">官方安装包</span>
          <span class="count">{{ index + 1 }}/{{ artifacts.length }}</span>
          <strong>{{ artifact.name }}</strong>
        </div>
        <div class="file-meta">
          <span>{{ formatBytes(artifact.size || apkSourceSize(artifact) || 0) }}</span>
          <span v-if="artifact.checksum_value">{{ (artifact.checksum_type || 'CRC64').toUpperCase() }}: {{ artifact.checksum_value }}</span>
          <span v-if="artifact.attributes.artifact_variant">渠道 {{ artifact.attributes.artifact_variant }}</span>
        </div>
      </div>
      <div class="file-actions">
        <AvailabilityBadge
          v-if="!suppressAvailabilityPresentation"
          :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null"
        />
        <button
          v-if="preferredAvailableUrl(domain, artifact, 'copy') || (suppressAvailabilityPresentation && rawArtifactUrl(artifact))"
          class="icon-button"
          @click="suppressAvailabilityPresentation ? emit('copy-url', rawArtifactUrl(artifact)) : emit('copy-artifact-url', artifact)"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          <span>复制链接</span>
        </button>
        <button
          v-else-if="rawArtifactUrl(artifact)"
          class="icon-button"
          @click="emit('copy-url', rawArtifactUrl(artifact))"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          <span>复制链接</span>
        </button>
        <a
          v-if="preferredAvailableUrl(domain, artifact)"
          class="icon-button"
          :href="preferredAvailableUrl(domain, artifact)"
          target="_blank"
          rel="noreferrer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M5 21h14" />
          </svg>
          <span>下载</span>
        </a>
        <a
          v-else-if="artifactDownloadUrl(domain, artifact)"
          class="icon-button"
          :href="artifactDownloadUrl(domain, artifact)"
          target="_blank"
          rel="noreferrer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M5 21h14" />
          </svg>
          <span>下载</span>
        </a>
        <button
          v-else-if="!suppressAvailabilityPresentation"
          class="icon-button is-disabled is-locked"
          disabled
          type="button"
          title="链接已失效，不可直接下载"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <span>下载</span>
        </button>
        <a
          v-if="actionableCandidate(domain, artifact, 'archive')"
          class="icon-button mirror-link"
          :href="actionableCandidate(domain, artifact, 'archive')?.url"
          target="_blank"
          rel="noreferrer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M5 21h14" />
          </svg>
          <span>归档路径</span>
        </a>
      </div>
    </article>
  </div>
</template>
