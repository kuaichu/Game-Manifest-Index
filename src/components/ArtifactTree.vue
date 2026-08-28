<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Artifact } from "../types";
import FragmentFileRow from "./FragmentFileRow.vue";

const props = defineProps<{ artifacts: Artifact[] }>();
const path = ref<string[]>([]);

watch(() => props.artifacts, () => { path.value = []; });

const normalized = computed(() => props.artifacts.map((artifact) => ({
  artifact,
  parts: artifact.name.replaceAll("\\", "/").split("/").filter(Boolean),
})));

const entries = computed(() => {
  const depth = path.value.length;
  const matching = normalized.value.filter((item) => path.value.every((part, index) => item.parts[index] === part));
  const folderMap = new Map<string, { name: string; path: string[]; count: number; size: number }>();
  const files: Artifact[] = [];
  for (const item of matching) {
    if (item.parts.length <= depth + 1) {
      files.push(item.artifact);
      continue;
    }
    const name = item.parts[depth];
    const folder = folderMap.get(name) || { name, path: [...path.value, name], count: 0, size: 0 };
    folder.count += 1;
    folder.size += item.artifact.size;
    folderMap.set(name, folder);
  }
  return { folders: [...folderMap.values()].sort((a, b) => a.name.localeCompare(b.name)), files };
});

function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value, unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit ? 2 : 0)} ${units[unit]}`;
}
</script>

<template>
  <div class="tree-browser">
    <div class="tree-toolbar">
      <button class="crumb" :class="{ active: !path.length }" @click="path = []">根目录</button>
      <template v-for="(part, index) in path" :key="`${part}:${index}`">
        <span>/</span><button class="crumb" :class="{ active: index === path.length - 1 }" @click="path = path.slice(0, index + 1)">{{ part }}</button>
      </template>
      <div class="tree-count"><strong>{{ entries.folders.length }}</strong> 个文件夹 / <strong>{{ entries.files.length }}</strong> 个文件</div>
    </div>
    <div v-if="entries.folders.length" class="folder-grid">
      <button v-for="folder in entries.folders" :key="folder.name" class="folder-card" @click="path = folder.path"><span class="folder-icon">▰</span><span><strong>{{ folder.name }}</strong><small>{{ folder.count }} 个文件</small></span><em>{{ formatBytes(folder.size) }}</em></button>
    </div>
    <div v-if="entries.files.length" class="hoyo-browser fragment-tree-files">
      <FragmentFileRow v-for="artifact in entries.files" :key="artifact.id" :artifact="artifact" />
    </div>
    <div v-if="!entries.folders.length && !entries.files.length" class="empty">当前目录为空。</div>
  </div>
</template>
