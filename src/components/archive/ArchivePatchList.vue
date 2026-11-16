<script setup lang="ts">
import ArtifactPagination from "../ArtifactPagination.vue";
import AvailabilityBadge from "../AvailabilityBadge.vue";
import {
  actionableCandidate,
  baseUrlFor,
  formatChecksum,
  hoyoPatchLabel,
  isFileManifestArtifact,
  manifestUrlFor,
  patchBasePath,
  patchRouteLabel,
  patchRouteText,
  preferredAvailableUrl,
  rawArtifactUrl,
} from "../../archive-artifact-helpers";
import {
  displayVersionLabel,
  domainFieldSupport,
  formatBytes,
  hoyoLanguageLabel,
  preferredArtifactAction,
} from "../../domain-presentation";
import type { ArchiveDomain, Artifact } from "../../types";

const props = defineProps<{
  displayedArtifacts: Artifact[];
  domain: ArchiveDomain | null;
  selectedVersion: string;
  usesPreferredUrlPresentation: boolean;
  artifactPage: number;
  artifactTotal: number;
  artifactPageSize: number;
  loadingMore: boolean;
}>();

const emit = defineEmits<{
  (e: "copy-url", url?: string): void;
  (e: "copy-artifact-url", artifact: Artifact): void;
  (e: "copy-manifest-url", artifact: Artifact): void;
  (e: "copy-base-url", artifact: Artifact): void;
  (e: "open-files"): void;
  (e: "update:page", page: number): void;
  (e: "update:page-size", pageSize: number): void;
}>();

function supportsArtifactField(field: string): boolean {
  return domainFieldSupport(props.domain, "artifact_fields", field) === "supported";
}
</script>

<template>
  <div v-if="usesPreferredUrlPresentation && domain?.adapter !== 'wuwa'" class="file-list patch-route-list endfield-list">
    <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card patch-route-card">
      <div class="file-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m21 8-9-5-9 5 9 5 9-5Z" />
          <path d="M3 8v8l9 5 9-5V8" />
          <path d="M12 13v8" />
        </svg>
      </div>
      <div class="file-main">
        <div class="file-title">
          <span class="pill">更新分卷</span>
          <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
          <strong>{{ artifact.name }}</strong>
        </div>
        <div class="file-meta">
          <span v-if="supportsArtifactField('size')">{{ formatBytes(artifact.size) }}</span>
          <span v-if="supportsArtifactField('checksum') && artifact.checksum_value"># {{ artifact.checksum_value }}</span>
          <span v-if="patchRouteText(artifact)">{{ patchRouteText(artifact) }}</span>
        </div>
      </div>
      <div class="file-actions endfield-actions">
        <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
        <button
          v-if="preferredAvailableUrl(domain, artifact, 'copy')"
          class="icon-button"
          @click="emit('copy-url', preferredAvailableUrl(domain, artifact, 'copy'))"
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
          v-if="actionableCandidate(domain, artifact, 'official')"
          class="icon-button"
          :href="actionableCandidate(domain, artifact, 'official')?.url"
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
          v-if="actionableCandidate(domain, artifact, 'mirror')"
          class="icon-button mirror-link"
          :href="actionableCandidate(domain, artifact, 'mirror')?.url"
          target="_blank"
          rel="noreferrer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M5 21h14" />
          </svg>
          <span>镜像</span>
        </a>
        <button
          v-if="!preferredAvailableUrl(domain, artifact) && !actionableCandidate(domain, artifact, 'official') && !actionableCandidate(domain, artifact, 'mirror')"
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
      </div>
    </article>
    <ArtifactPagination
      :page="artifactPage"
      :total="artifactTotal"
      :page-size="artifactPageSize"
      :loading="loadingMore"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:page-size', $event)"
    />
  </div>

  <div v-else-if="domain?.adapter === 'wuwa'" class="file-list patch-route-list">
    <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card patch-route-card">
      <div class="file-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m21 8-9-5-9 5 9 5 9-5Z" />
          <path d="M3 8v8l9 5 9-5V8" />
          <path d="M12 13v8" />
        </svg>
      </div>
      <div class="file-main">
        <div class="file-title">
          <span class="pill">更新路线</span>
          <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
          <strong>{{ patchRouteLabel(artifact.name) }}</strong>
        </div>
        <div class="file-meta">
          <span>{{ formatBytes(artifact.size) }}</span>
          <span># {{ artifact.checksum_value || '—' }}</span>
          <span v-if="patchBasePath(artifact)">{{ patchBasePath(artifact) }}</span>
        </div>
      </div>
      <div class="file-actions">
        <template v-if="isFileManifestArtifact(artifact)">
          <button class="icon-button" type="button" @click="emit('open-files')"><span>查看清单</span></button>
          <button v-if="manifestUrlFor(artifact)" class="icon-button" type="button" @click="emit('copy-manifest-url', artifact)"><span>复制清单链接</span></button>
          <button v-if="baseUrlFor(artifact)" class="icon-button" type="button" @click="emit('copy-base-url', artifact)"><span>复制资源文件根目录</span></button>
        </template>
        <template v-else>
          <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
          <button
            v-if="preferredAvailableUrl(domain, artifact, 'copy')"
            class="icon-button"
            @click="emit('copy-artifact-url', artifact)"
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
          <button
            v-else
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
        </template>
      </div>
    </article>
    <ArtifactPagination
      :page="artifactPage"
      :total="artifactTotal"
      :page-size="artifactPageSize"
      :loading="loadingMore"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:page-size', $event)"
    />
  </div>

  <div v-else-if="domain?.adapter === 'hoyo'" class="file-list patch-route-list">
    <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card package-card">
      <div class="file-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m21 8-9-5-9 5 9 5 9-5Z" />
          <path d="M3 8v8l9 5 9-5V8" />
          <path d="M12 13v8" />
        </svg>
      </div>
      <div class="file-main">
        <div class="file-title">
          <span class="pill">{{ hoyoPatchLabel(selectedVersion, artifact) }}</span>
          <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
          <strong>{{ artifact.name }}</strong>
        </div>
        <div class="file-meta">
          <span>{{ formatBytes(artifact.size) }}</span>
          <span v-if="artifact.checksum_value">{{ formatChecksum(artifact) }}</span>
          <span v-if="artifact.attributes.route_from && (artifact.attributes.route_to || selectedVersion)">{{ displayVersionLabel(String(artifact.attributes.route_from)) }} -> {{ displayVersionLabel(String(artifact.attributes.route_to || selectedVersion)) }}</span>
          <span v-if="artifact.attributes.language">{{ hoyoLanguageLabel(artifact.attributes.language) }}</span>
        </div>
      </div>
      <div class="file-actions">
        <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
        <button
          v-if="preferredAvailableUrl(domain, artifact, 'copy')"
          class="icon-button"
          @click="emit('copy-artifact-url', artifact)"
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
        <button
          v-else
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
      </div>
    </article>
    <ArtifactPagination
      :page="artifactPage"
      :total="artifactTotal"
      :page-size="artifactPageSize"
      :loading="loadingMore"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:page-size', $event)"
    />
  </div>
</template>
