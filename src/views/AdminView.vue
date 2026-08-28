<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError, adminApi, isAbortError } from "../api";
import { gameIcons } from "../game-icons";
import CustomSelect from "../components/CustomSelect.vue";
import {
  discoverItemState,
  discoverSkippedCount,
  operationControlsDisabled,
  operationScopeLabel,
  probeAvailableUrls,
  probeCheckedUrls,
  probeFailedUrls,
  probeItemKey,
  probeUnavailableUrls,
  probeUnknownUrls,
  restoredOperationScope,
} from "../operation-scope";
import type {
  AdminCatalog,
  AdminDomain,
  AdminEditableVersionPayload,
  AdminOperationJob,
  AdminOperationPayload,
  AdminOperationResult,
  AdminSyncStatus,
  ManualArtifactPayload,
  ProbeSchedule,
  ProbeStatus,
  ProbeUrlResult,
  RetentionConfig,
  RetentionStatus,
  SyncRunStatus,
  SyncSchedule,
  VersionSummary,
} from "../types";

type Tab = "games" | "domains" | "content" | "probe" | "retention";

const TOKEN_STORAGE_KEY = "game-manifest-index-web-admin-token-v1";
const OPERATION_JOB_KEY = "game-manifest-index-web-operation-job-v1";

const router = useRouter();
const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY) || "");
const authenticated = ref(false);
const catalog = ref<AdminCatalog>({ games: [], domains: [] });
const tab = ref<Tab>("games");
const loading = ref(false);
const error = ref("");
const success = ref("");

const currentTabMeta = computed(() => {
  switch (tab.value) {
    case "games":
      return {
        title: "游戏入口管理",
        subtitle: "配置支持的游戏元数据、展示名称与图标资源",
      };
    case "domains":
      return {
        title: "数据模块管理",
        subtitle: "配置各游戏的数据分发模块、适配器契约与能力规范",
      };
    case "content":
      return {
        title: "版本内容控制",
        subtitle: "管理各模块的版本发布、文件分卷、下载直链与元数据",
      };
    case "probe":
      return {
        title: "采集与探活监控",
        subtitle: "监控各模块自动同步任务状态、定时探活与链接可用性",
      };
    case "retention":
      return {
        title: "数据保留与自动清理",
        subtitle: "配置本地缓存生命周期、旧运维记录与探活历史轮转，支持安全手动立即清理",
      };
    default:
      return {
        title: "归档控制台",
        subtitle: "统一游戏文件索引与分发后台管理",
      };
  }
});

const gameSearchQuery = ref("");
const domainSearchQuery = ref("");
const versionSearchQuery = ref("");

const selectedGameId = ref("");
const selectedDomainId = ref("");
const versions = ref<VersionSummary[]>([]);
const selectedVersion = ref("");
const syncStatus = ref<AdminSyncStatus | null>(null);
const probeStatus = ref<ProbeStatus | null>(null);
const probeSchedule = ref<ProbeSchedule>({ enabled: false, interval_hours: 24, mode: "normal" });
let probePollTimer: number | null = null;
const newGame = ref(false);
const newDomain = ref(false);
interface EditableArtifactDraft {
  kind: string;
  name: string;
  part: number;
  size: number;
  checksum_type: string;
  checksum_value: string;
  attributesJson: string;
  urls: Array<{
    id?: number;
    persisted_url?: string;
    url: string;
    priority: number;
    source_kind: string;
  }>;
}

const contentSubTab = ref<"edit" | "create">("edit");
const editableLoaded = ref(false);
const editableLoading = ref(false);
const originalEditableJson = ref("");
const checksumsOpen = ref(false);
const createChecksumsOpen = ref(false);
const moreActionsOpen = ref(false);

const editableDraft = ref({
  channel: "official",
  version_code: null as number | null,
  is_visible: true,
  file_created_at_override: "",
  checksum_etag: "",
  checksum_crc64: "",
  checksum_md5: "",
  artifacts: [] as EditableArtifactDraft[],
  artifactsJson: "[]",
  artifactsMode: "visual" as "visual" | "json",
});

const selectedDomainObj = computed(() =>
  catalog.value.domains.find((d) => d.id === selectedDomainId.value) || null,
);

const selectedDomainGameName = computed(() => {
  if (!selectedDomainObj.value) return "";
  const game = catalog.value.games.find((g) => g.id === selectedDomainObj.value?.game_id);
  return game?.name || selectedDomainObj.value.game_id;
});

const selectedDomainPlatform = computed(() => {
  return selectedDomainObj.value?.platform || "Android";
});

const currentVersionItem = computed(() =>
  versions.value.find((v) => v.version === selectedVersion.value) || null,
);

const currentVersionHealth = computed(() => {
  const art = editableDraft.value.artifacts[0];
  let attr: Record<string, any> = {};
  if (art?.attributesJson) {
    try {
      attr = JSON.parse(art.attributesJson || "{}");
    } catch {
      // ignore
    }
  }
  const httpCode = attr.http_code !== undefined && attr.http_code !== null ? Number(attr.http_code) : null;
  const available = attr.available === true;
  const lastCheckedAt = attr.last_checked_at || null;
  const size = art?.size || 0;

  const isChecked = httpCode !== null || lastCheckedAt !== null;
  const isOk = available || (httpCode !== null && httpCode >= 200 && httpCode < 400);

  return {
    isChecked,
    isOk,
    httpCode,
    available,
    lastCheckedAt,
    size,
  };
});

const isUrlChanged = computed(() => {
  if (!editableLoaded.value || !editableDraft.value.artifacts.length) return false;
  const currentUrl = editableDraft.value.artifacts[0]?.urls[0]?.url?.trim() || "";
  const initialUrl = editableDraft.value.artifacts[0]?.urls[0]?.persisted_url?.trim() || "";
  return initialUrl !== "" && currentUrl !== initialUrl;
});

function isVersionAvailable(item: VersionSummary): boolean {
  const apkInfo = item.artifact_kinds?.apk;
  if (!apkInfo) return true;
  const availableCount = apkInfo.availability_states?.available ?? 0;
  const canonicalCount = apkInfo.availability_states?.canonical ?? 0;
  const unavailableCount = apkInfo.availability_states?.unavailable ?? 0;
  if (unavailableCount > 0 && availableCount === 0 && canonicalCount === 0) {
    return false;
  }
  return true;
}

function getFileTimeSourceDescription(timeStr: string, rawUrl: string): string {
  if (!timeStr?.trim()) return "留空（保存后由后端自动识别）";
  const cleanTime = timeStr.trim();
  const cleanUrl = rawUrl || "";

  // 1. 检查 URL 中是否有完整时间戳形如 20260803155301
  const tsMatch = cleanUrl.match(/(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/);
  if (tsMatch) {
    const compactTs = tsMatch[0];
    const cleanTimeCompact = cleanTime.replace(/[-:T Z+]/g, "");
    if (cleanTimeCompact.startsWith(compactTs.slice(0, 8))) {
      return "URL 时间";
    }
  }

  // 2. 检查 URL 中是否有日期戳形如 20260803 或 2026-08-03
  const dateMatch = cleanUrl.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/);
  if (dateMatch) {
    const datePrefix = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
    if (cleanTime.startsWith(datePrefix)) {
      return "URL 时间";
    }
  }

  return "人工填写";
}

function getChecksumSummaryText(etag: string, crc64: string, md5: string): string {
  const parts: string[] = [];
  if (etag?.trim()) parts.push("ETag");
  if (crc64?.trim()) parts.push("CRC64");
  if (md5?.trim()) parts.push("MD5");
  if (!parts.length) return "";
  return parts.join(" · ");
}

const dirtyChangesCount = computed(() => {
  if (!editableLoaded.value) return 0;
  let count = 0;
  let original: any = {};
  try {
    original = JSON.parse(originalEditableJson.value || "{}");
  } catch {
    return 0;
  }

  if (editableDraft.value.channel.trim() !== (original.channel || "").trim()) count++;
  if (Number(editableDraft.value.version_code || 0) !== Number(original.version_code || 0)) count++;
  if (editableDraft.value.is_visible !== original.is_visible) count++;
  if (editableDraft.value.file_created_at_override.trim() !== (original.file_created_at_override || "").trim()) count++;
  if (editableDraft.value.checksum_etag.trim() !== (original.checksum_etag || "").trim()) count++;
  if (editableDraft.value.checksum_crc64.trim() !== (original.checksum_crc64 || "").trim()) count++;
  if (editableDraft.value.checksum_md5.trim() !== (original.checksum_md5 || "").trim()) count++;

  const currentArt = editableDraft.value.artifacts[0];
  let origArt: any = null;
  try {
    const origArts = JSON.parse(original.artifacts || "[]");
    origArt = origArts[0];
  } catch {
    // ignore
  }

  if (origArt) {
    if ((currentArt?.name || "").trim() !== (origArt.name || "").trim()) count++;
    if (Number(currentArt?.size || 0) !== Number(origArt.size || 0)) count++;
    if ((currentArt?.urls[0]?.url || "").trim() !== (origArt.urls?.[0]?.url || "").trim()) count++;
  } else if (currentArt) {
    count++;
  }

  return count;
});

function clearFileTime(): void {
  editableDraft.value.file_created_at_override = "";
}

function clearCreateFileTime(): void {
  createDraft.value.file_created_at = "";
}

async function copyUrl(url: string): Promise<void> {
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    success.value = "下载链接已成功复制到剪贴板！";
  } catch {
    error.value = "复制链接失败，请手动选择复制。";
  }
}

async function copyText(text: string): Promise<void> {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    success.value = `已复制到剪贴板：${text}`;
  } catch {
    error.value = "复制失败，请手动选择复制。";
  }
}

function openUrl(url: string): void {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function normalizeJsonStr(jsonStr: string): string {
  try {
    const sortKeys = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(sortKeys);
      if (typeof value !== "object" || value === null) return value;
      return Object.fromEntries(
        Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, sortKeys(item)]),
      );
    };
    const obj = JSON.parse(jsonStr || "{}");
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
      return jsonStr.trim();
    }
    return JSON.stringify(sortKeys(obj));
  } catch {
    return jsonStr.trim();
  }
}

function getNormalizedUnpackedSize(size: number | null | undefined): number | null {
  if (size === null || size === undefined) return null;
  const s = String(size).trim();
  if (s === "" || Number.isNaN(Number(s))) return null;
  return Number(s);
}

function buildArtifactsPayload(): ManualArtifactPayload[] {
  if (editableDraft.value.artifactsMode === "json") {
    try {
      const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
      if (Array.isArray(parsed)) {
        return parsed.map((item: any, idx: number) => ({
          kind: String(item.kind || "file").trim(),
          name: String(item.name || `part_${idx + 1}`).trim(),
          part: Number(item.part) || idx + 1,
          size: Number(item.size) || 0,
          checksum_type: item.checksum_type ? String(item.checksum_type).trim() : null,
          checksum_value: item.checksum_value ? String(item.checksum_value).trim().toLowerCase() : null,
          attributes: typeof item.attributes === "object" && item.attributes !== null && !Array.isArray(item.attributes) ? item.attributes : {},
          urls: Array.isArray(item.urls)
            ? item.urls.map((u: any, uIdx: number) => ({
                url: String(u.url || "").trim(),
                priority: Number(u.priority) ?? uIdx,
                source_kind: String(u.source_kind || "official").trim(),
              })).filter((u: any) => Boolean(u.url))
            : [],
        }));
      }
    } catch {
      // json parse failed
    }
  }

  return editableDraft.value.artifacts.map((art, idx) => {
    let attr: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(art.attributesJson || "{}");
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) attr = parsed;
    } catch {
      // ignore
    }
    return {
      kind: art.kind.trim() || "file",
      name: art.name.trim() || `part_${idx + 1}`,
      part: Number(art.part) || idx + 1,
      size: Number(art.size) || 0,
      checksum_type: art.checksum_type.trim() || null,
      checksum_value: art.checksum_value.trim().toLowerCase() || null,
      attributes: attr,
      urls: (art.urls || []).map((u, uIdx) => ({
        url: u.url.trim(),
        priority: Number(u.priority) ?? uIdx,
        source_kind: u.source_kind.trim() || "official",
      })).filter((u) => Boolean(u.url)),
    };
  });
}

function normalizeArtifactsForComparison(artifacts: ManualArtifactPayload[]): string {
  const normalized = artifacts.map((art) => ({
    kind: art.kind,
    name: art.name,
    part: art.part,
    size: art.size,
    checksum_type: art.checksum_type || null,
    checksum_value: art.checksum_value ? art.checksum_value.toLowerCase() : null,
    attributes: art.attributes || {},
    urls: (art.urls || [])
      .map((u) => ({ url: u.url.trim(), priority: Number(u.priority) || 0, source_kind: u.source_kind || "official" }))
      .filter((u) => Boolean(u.url))
      .sort((a, b) => a.priority - b.priority || a.url.localeCompare(b.url) || a.source_kind.localeCompare(b.source_kind)),
  })).sort((a, b) => a.part - b.part);

  return normalizeJsonStr(JSON.stringify(normalized));
}

function addArtifactItem(): void {
  const nextPart = editableDraft.value.artifacts.reduce((max, a) => Math.max(max, a.part), 0) + 1;
  editableDraft.value.artifacts.push({
    kind: "file",
    name: "",
    part: nextPart,
    size: 0,
    checksum_type: "",
    checksum_value: "",
    attributesJson: "{}",
    urls: [{ url: "", priority: 0, source_kind: "official" }],
  });
  syncArtifactsToJson();
}

function removeArtifactItem(index: number): void {
  if (editableDraft.value.artifacts.length <= 1) {
    alert("版本必须包含至少一个资源文件 (Artifact)。");
    return;
  }
  editableDraft.value.artifacts.splice(index, 1);
  syncArtifactsToJson();
}

function addArtifactUrlItem(artifactIndex: number): void {
  const art = editableDraft.value.artifacts[artifactIndex];
  if (!art) return;
  const nextPriority = art.urls.length;
  art.urls.push({ url: "", priority: nextPriority, source_kind: "official" });
  syncArtifactsToJson();
}

function removeArtifactUrlItem(artifactIndex: number, urlIndex: number): void {
  const art = editableDraft.value.artifacts[artifactIndex];
  if (!art) return;
  art.urls.splice(urlIndex, 1);
  syncArtifactsToJson();
}

function extractFilenameFromUrl(rawUrl: string): string {
  if (!rawUrl || typeof rawUrl !== "string") return "";
  try {
    const clean = rawUrl.split("?")[0].split("#")[0].trim();
    const lastSegment = clean.substring(clean.lastIndexOf("/") + 1).trim();
    return decodeURIComponent(lastSegment);
  } catch {
    const clean = rawUrl.split("?")[0].split("#")[0].trim();
    return clean.substring(clean.lastIndexOf("/") + 1).trim();
  }
}

function handleArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
  const extracted = extractFilenameFromUrl(newUrl);
  if (extracted && extracted.includes(".")) {
    const currentName = (art.name || "").trim();
    const isDefaultOrEmpty =
      !currentName ||
      /^package(\.part\d+)?\.(zip|bin|apk|dat)$/i.test(currentName) ||
      currentName === "未命名文件";

    if (isDefaultOrEmpty) {
      art.name = extracted;
    }
    if (extracted.toLowerCase().endsWith(".apk") && (art.kind === "file" || !art.kind)) {
      art.kind = "apk";
    }
  }
  syncArtifactsToJson();
}

function forceExtractArtifactName(art: EditableArtifactDraft): void {
  const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
  const extracted = extractFilenameFromUrl(firstUrl);
  if (extracted && extracted.includes(".")) {
    art.name = extracted;
    if (extracted.toLowerCase().endsWith(".apk") && (art.kind === "file" || !art.kind)) {
      art.kind = "apk";
    }
    syncArtifactsToJson();
  }
}

function switchArtifactsMode(mode: "visual" | "json"): void {
  if (mode === "json") {
    syncArtifactsToJson();
    editableDraft.value.artifactsMode = "json";
  } else {
    try {
      const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
      if (!Array.isArray(parsed)) throw new Error("Artifacts JSON 必须是数组");
      editableDraft.value.artifacts = parsed.map((item: any, idx: number) => ({
        kind: String(item.kind || "file").trim(),
        name: String(item.name || "").trim(),
        part: Number(item.part) || idx + 1,
        size: Number(item.size) || 0,
        checksum_type: item.checksum_type ? String(item.checksum_type).trim() : "",
        checksum_value: item.checksum_value ? String(item.checksum_value).trim() : "",
        attributesJson: JSON.stringify(item.attributes || {}, null, 2),
        urls: Array.isArray(item.urls)
          ? item.urls.map((u: any, uIdx: number) => ({
              url: String(u.url || "").trim(),
              priority: Number(u.priority) ?? uIdx,
              source_kind: String(u.source_kind || "official").trim(),
            }))
          : [],
      }));
      editableDraft.value.artifactsMode = "visual";
    } catch (err) {
      error.value = err instanceof Error ? `切换失败: ${err.message}` : "JSON 解析失败";
    }
  }
}

function syncArtifactsToJson(): void {
  const payload = buildArtifactsPayload();
  editableDraft.value.artifactsJson = JSON.stringify(payload, null, 2);
}

function formatArtifactsJson(): void {
  try {
    const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
    editableDraft.value.artifactsJson = JSON.stringify(parsed, null, 2);
  } catch (err) {
    error.value = err instanceof Error ? `JSON 格式错误: ${err.message}` : "JSON 格式无效";
  }
}

const isEditableDirty = computed(() => {
  if (!editableLoaded.value) return false;
  const currentArtifactsStr = normalizeArtifactsForComparison(buildArtifactsPayload());
  const current = JSON.stringify({
    channel: editableDraft.value.channel.trim(),
    version_code: editableDraft.value.version_code,
    is_visible: editableDraft.value.is_visible,
    file_created_at_override: editableDraft.value.file_created_at_override.trim(),
    checksum_etag: editableDraft.value.checksum_etag.trim(),
    checksum_crc64: editableDraft.value.checksum_crc64.trim(),
    checksum_md5: editableDraft.value.checksum_md5.trim(),
    artifacts: currentArtifactsStr,
  });
  return current !== originalEditableJson.value;
});

const urlProbeMap = ref<Record<string, { loading: boolean; result?: ProbeUrlResult }>>({});
const batchProbing = ref(false);

async function probeUrlItem(target: EditableArtifactDraft["urls"][number] | string): Promise<void> {
  const urlItem = typeof target === "string" ? { url: target, priority: 0, source_kind: "official" } : target;
  const cleanUrl = urlItem.url.trim();
  if (!cleanUrl) {
    error.value = "请先输入有效的 URL 地址";
    return;
  }
  if (!cleanUrl.startsWith("http://") && !cleanUrl.startsWith("https://")) {
    error.value = "URL 必须以 http:// 或 https:// 开头";
    return;
  }
  urlProbeMap.value[cleanUrl] = { loading: true };
  try {
    const artifactUrlId = "id" in urlItem && urlItem.id && cleanUrl === urlItem.persisted_url ? urlItem.id : undefined;
    const res = await adminApi.probeUrl(cleanUrl, token.value, 10, artifactUrlId);
    urlProbeMap.value[cleanUrl] = { loading: false, result: res };
    if (res.ok) {
      const persistence = res.persisted ? "，结果已同步到下载区" : "；当前链接尚未保存，本次仅临时检测";
      success.value = `URL 验活成功：HTTP ${res.status || 200}${res.size ? ` (${formatBytes(res.size)})` : ""}${persistence}`;
    } else {
      error.value = `URL 验活异常：${res.error || res.reason || `HTTP ${res.status || "失败"}`}`;
    }
  } catch (err) {
    urlProbeMap.value[cleanUrl] = {
      loading: false,
      result: { url: cleanUrl, ok: false, error: err instanceof Error ? err.message : "请求失败" },
    };
    error.value = `URL 验活请求出错: ${err instanceof Error ? err.message : "未知错误"}`;
  }
}

async function probeAllDraftUrls(artifacts: EditableArtifactDraft[]): Promise<void> {
  const candidates = artifacts.flatMap((art) => art.urls).filter((item) => {
    const url = item.url.trim();
    return url.startsWith("http://") || url.startsWith("https://");
  });
  const urls = Array.from(
    new Set(candidates.map((item) => item.url.trim())),
  );
  const artifactUrlIds = Array.from(new Set(
    candidates
      .filter((item) => item.id && item.url.trim() === item.persisted_url)
      .map((item) => item.id as number),
  ));
  if (!urls.length) {
    error.value = "当前没有可用于验活的有效 http/https 下载链接";
    return;
  }
  batchProbing.value = true;
  for (const u of urls) {
    urlProbeMap.value[u] = { loading: true };
  }
  try {
    const res = await adminApi.probeUrls(urls, token.value, 10, artifactUrlIds);
    for (const item of res.items) {
      urlProbeMap.value[item.url] = { loading: false, result: item };
    }
    const okCount = res.items.filter((i) => i.ok).length;
    const failCount = res.items.length - okCount;
    const transientCount = res.items.filter((i) => !i.persisted).length;
    if (failCount === 0) {
      const persistence = transientCount
        ? `其中 ${transientCount} 条尚未保存，仅完成临时检测。`
        : "结果已全部同步到下载区。";
      success.value = `全部 ${okCount} 条下载链接已验活通过！${persistence}`;
    } else {
      error.value = `验活完成：${okCount} 条链接正常，${failCount} 条链接异常，请检查红色标记。`;
    }
  } catch (err) {
    for (const u of urls) {
      if (urlProbeMap.value[u]?.loading) {
        urlProbeMap.value[u] = { loading: false };
      }
    }
    error.value = `批量验活请求失败: ${err instanceof Error ? err.message : "未知错误"}`;
  } finally {
    batchProbing.value = false;
  }
}

interface CreateVersionDraft {
  version: string;
  channel: string;
  version_code: number | null;
  file_created_at: string;
  is_visible: boolean;
  checksum_etag: string;
  checksum_crc64: string;
  checksum_md5: string;
  artifacts: EditableArtifactDraft[];
  artifactsJson: string;
  artifactsMode: "visual" | "json";
}

function defaultCreateDraft(): CreateVersionDraft {
  const initialArtifacts: EditableArtifactDraft[] = [
    {
      kind: "apk",
      name: "",
      part: 1,
      size: 0,
      checksum_type: "",
      checksum_value: "",
      attributesJson: "{}",
      urls: [{ url: "", priority: 0, source_kind: "official" }],
    },
  ];
  return {
    version: "",
    channel: "official",
    version_code: null,
    file_created_at: "",
    is_visible: true,
    checksum_etag: "",
    checksum_crc64: "",
    checksum_md5: "",
    artifacts: initialArtifacts,
    artifactsJson: JSON.stringify(
      initialArtifacts.map((art) => ({
        kind: art.kind,
        name: art.name,
        part: art.part,
        size: art.size,
        checksum_type: art.checksum_type || null,
        checksum_value: art.checksum_value || null,
        attributes: {},
        urls: art.urls,
      })),
      null,
      2,
    ),
    artifactsMode: "visual",
  };
}

const createDraft = ref<CreateVersionDraft>(defaultCreateDraft());

let controller: AbortController | null = null;

const gameDraft = ref({
  id: "",
  name: "",
  sub_name: "",
  platform: "PC",
  icon_source: "",
  is_enabled: true,
  sort_order: 0,
});
const domainDraft = ref({
  id: "",
  game_id: "",
  kind: "packages",
  platform: "Windows",
  capabilities: "packages",
  adapter: "generic",
  is_enabled: true,
  sort_order: 0,
});

const selectedGame = computed(() => catalog.value.games.find((item) => item.id === selectedGameId.value) || null);
const gameDomains = computed(() => catalog.value.domains.filter((item) => item.game_id === selectedGameId.value));
const selectedDomain = computed(() => catalog.value.domains.find((item) => item.id === selectedDomainId.value) || null);
const selectedVersionSummary = computed(() => versions.value.find((item) => item.version === selectedVersion.value) || null);
const gameIconPreview = computed(() => resolveGameIcon(gameDraft.value.id, gameDraft.value.icon_source));

const gameDropdownOpen = ref(false);
const domainDropdownOpen = ref(false);
const gameDropdownSearch = ref("");

const filteredDropdownGames = computed(() => {
  const q = gameDropdownSearch.value.trim().toLowerCase();
  if (!q) return catalog.value.games;
  return catalog.value.games.filter(
    (g) => g.name.toLowerCase().includes(q) || g.id.toLowerCase().includes(q) || (g.sub_name && g.sub_name.toLowerCase().includes(q)),
  );
});

function handleDropdownSelectGame(gameId: string): void {
  selectedGameId.value = gameId;
  selectGame(gameId);
  openContent(selectedDomainId.value);
  gameDropdownOpen.value = false;
  gameDropdownSearch.value = "";
}

function handleDropdownSelectDomain(domainId: string): void {
  selectedDomainId.value = domainId;
  openContent(domainId);
  domainDropdownOpen.value = false;
}

function handleGlobalDropdownClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  if (!target) return;
  if (!target.closest(".custom-dropdown-container.game-dropdown")) {
    gameDropdownOpen.value = false;
  }
  if (!target.closest(".custom-dropdown-container.domain-dropdown")) {
    domainDropdownOpen.value = false;
  }
}

const filteredGames = computed(() => {
  const q = gameSearchQuery.value.trim().toLowerCase();
  if (!q) return catalog.value.games;
  return catalog.value.games.filter(
    (g) => g.name.toLowerCase().includes(q) || g.id.toLowerCase().includes(q) || g.sub_name.toLowerCase().includes(q),
  );
});

const domainGameFilter = ref<string>("all");

function getDomainGame(gameId: string) {
  return catalog.value.games.find((g) => g.id === gameId) || null;
}

const domainGameOptions = computed(() => {
  const allOption = { label: `🌟 全部游戏 (${catalog.value.domains.length} 个模块)`, value: "all" };
  const gameOptions = catalog.value.games.map((g) => {
    const count = catalog.value.domains.filter((d) => d.game_id === g.id).length;
    return {
      label: `${g.name} (${count})`,
      value: g.id,
    };
  });
  return [allOption, ...gameOptions];
});

const filteredDomains = computed(() => {
  const q = domainSearchQuery.value.trim().toLowerCase();
  let list = catalog.value.domains;
  if (domainGameFilter.value && domainGameFilter.value !== "all") {
    list = list.filter((d) => d.game_id === domainGameFilter.value);
  }
  if (!q) return list;
  return list.filter((d) => {
    const game = getDomainGame(d.game_id);
    const gameName = game ? game.name.toLowerCase() : "";
    return (
      d.id.toLowerCase().includes(q) ||
      d.kind.toLowerCase().includes(q) ||
      d.platform.toLowerCase().includes(q) ||
      d.adapter.toLowerCase().includes(q) ||
      gameName.includes(q)
    );
  });
});

const versionFilterState = ref<"all" | "unavailable" | "unknown">("all");

async function toggleVersionFilter(target: "unavailable" | "unknown"): Promise<void> {
  if (isEditableDirty.value) {
    const confirmed = window.confirm(
      `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n切换筛选将丢弃未保存的修改，是否确定继续？`,
    );
    if (!confirmed) return;
  }

  if (versionFilterState.value === target) {
    // 取消筛选，恢复最新可用版本
    versionFilterState.value = "all";
    const latestAvailable = versions.value.find((v) => isVersionAvailable(v)) || versions.value[0];
    if (latestAvailable && latestAvailable.version !== selectedVersion.value) {
      selectedVersion.value = latestAvailable.version;
      await loadEditableVersion(selectedDomainId.value, latestAvailable.version);
    }
  } else {
    // 激活目标筛选，自动选中第一个匹配的版本
    versionFilterState.value = target;
    let targetVersion: VersionSummary | undefined;
    if (target === "unavailable") {
      targetVersion = versions.value.find((v) => isVersionUnavailable(v));
    } else if (target === "unknown") {
      targetVersion = versions.value.find((v) => isVersionUnknown(v));
    }

    if (targetVersion && targetVersion.version !== selectedVersion.value) {
      selectedVersion.value = targetVersion.version;
      await loadEditableVersion(selectedDomainId.value, targetVersion.version);
    }
  }
}

async function resetVersionFilter(): Promise<void> {
  if (isEditableDirty.value) {
    const confirmed = window.confirm(
      `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n清除筛选将丢弃未保存的修改，是否确定继续？`,
    );
    if (!confirmed) return;
  }

  versionFilterState.value = "all";
  const latestAvailable = versions.value.find((v) => isVersionAvailable(v)) || versions.value[0];
  if (latestAvailable && latestAvailable.version !== selectedVersion.value) {
    selectedVersion.value = latestAvailable.version;
    await loadEditableVersion(selectedDomainId.value, latestAvailable.version);
  }
}

function getDomainFriendlyName(d: AdminDomain | null): string {
  if (!d) return "Android 安装包";
  if (d.kind === "apk" || d.platform?.toLowerCase().includes("android")) {
    return "Android 安装包";
  }
  if (d.platform?.toLowerCase().includes("pc") || d.platform?.toLowerCase().includes("windows")) {
    if (d.kind === "archive" || d.kind === "packages") return "PC 安装包";
    if (d.kind === "resources" || d.kind === "chunks") return "PC 资源文件";
    return "PC 资源";
  }
  return d.id;
}

function isVersionUnavailable(item: VersionSummary): boolean {
  const apkInfo = item.artifact_kinds?.apk;
  if (!apkInfo) return false;
  const availableCount = apkInfo.availability_states?.available ?? 0;
  const canonicalCount = apkInfo.availability_states?.canonical ?? 0;
  const unavailableCount = apkInfo.availability_states?.unavailable ?? 0;
  return unavailableCount > 0 && availableCount === 0 && canonicalCount === 0;
}

function isVersionUnknown(item: VersionSummary): boolean {
  const apkInfo = item.artifact_kinds?.apk;
  if (!apkInfo) return true;
  const availableCount = apkInfo.availability_states?.available ?? 0;
  const canonicalCount = apkInfo.availability_states?.canonical ?? 0;
  const unavailableCount = apkInfo.availability_states?.unavailable ?? 0;
  const unknownCount = apkInfo.availability_states?.unknown ?? 0;
  return unknownCount > 0 && availableCount === 0 && canonicalCount === 0 && unavailableCount === 0;
}

const archiveHealthStats = computed(() => {
  const total = versions.value.length;
  const latest = versions.value[0]?.version || "—";
  let available = 0;
  let unavailable = 0;
  let unknown = 0;

  for (const v of versions.value) {
    if (isVersionUnavailable(v)) {
      unavailable++;
    } else if (isVersionUnknown(v)) {
      unknown++;
    } else {
      available++;
    }
  }

  return {
    total,
    latest,
    available,
    unavailable,
    unknown,
  };
});

const filteredVersions = computed(() => {
  let list = [...versions.value];
  if (versionFilterState.value === "unavailable") {
    list = list.filter((v) => isVersionUnavailable(v));
  } else if (versionFilterState.value === "unknown") {
    list = list.filter((v) => isVersionUnknown(v));
  }

  const q = versionSearchQuery.value.trim().toLowerCase();
  if (q) {
    list = list.filter((v) => v.version.toLowerCase().includes(q));
  }

  // 自然倒序排序
  list.sort(compareVersionsDesc);
  return list;
});

// 版本分组数据结构定义
interface VersionMinorGroup {
  minorKey: string;
  items: VersionSummary[];
}

interface VersionGroupEntry {
  type: "single" | "minorGroup";
  item?: VersionSummary;
  group?: VersionMinorGroup;
}

interface VersionMajorGroup {
  majorKey: string;
  totalCount: number;
  unavailableCount: number;
  entries: VersionGroupEntry[];
  allItems: VersionSummary[];
}

// 解析版本号主分类、次分类与排序数字权重
function parseVersionKey(versionStr: string): { majorKey: string; minorKey: string; sortWeights: number[] } {
  const v = versionStr.trim();

  // 1. 8位纯日期格式，如 20260813
  if (/^\d{8}$/.test(v)) {
    const year = v.substring(0, 4);
    const month = v.substring(4, 6);
    return {
      majorKey: year,
      minorKey: `${year}-${month}`,
      sortWeights: [parseInt(v, 10)],
    };
  }

  // 2. 带有日期的格式，如 3.20240115
  const dateMatch = v.match(/^(\d+)\.(\d{4})(\d{2})(\d{2})$/);
  if (dateMatch) {
    const major = dateMatch[1];
    const year = dateMatch[2];
    const month = dateMatch[3];
    return {
      majorKey: `${major}.x`,
      minorKey: `${year}-${month}`,
      sortWeights: [parseInt(major, 10), parseInt(`${year}${month}${dateMatch[4]}`, 10)],
    };
  }

  // 3. 标准语义/数字段版本，如 6.5.1, 2.7.61, 9.0, 13.3.8
  const parts = v.match(/\d+/g)?.map(Number) || [];
  if (parts.length > 0) {
    const majorNum = parts[0];
    const minorNum = parts.length > 1 ? parts[1] : 0;
    return {
      majorKey: `${majorNum}.x`,
      minorKey: `${majorNum}.${minorNum}`,
      sortWeights: parts,
    };
  }

  return {
    majorKey: "其他",
    minorKey: "其他",
    sortWeights: [0],
  };
}

// 自然倒序排序比较函数 (数值大小比较，避免 10.x 排在 2.x 后面)
function compareVersionsDesc(a: VersionSummary, b: VersionSummary): number {
  const aInfo = parseVersionKey(a.version);
  const bInfo = parseVersionKey(b.version);

  const minLen = Math.min(aInfo.sortWeights.length, bInfo.sortWeights.length);
  for (let i = 0; i < minLen; i++) {
    if (aInfo.sortWeights[i] !== bInfo.sortWeights[i]) {
      return bInfo.sortWeights[i] - aInfo.sortWeights[i]; // 倒序
    }
  }
  if (aInfo.sortWeights.length !== bInfo.sortWeights.length) {
    return bInfo.sortWeights.length - aInfo.sortWeights.length;
  }
  return b.version.localeCompare(a.version);
}

// 折叠展开状态管理
const expandedMajorKeys = ref<Set<string>>(new Set());
const expandedMinorKeys = ref<Set<string>>(new Set());
const gameExpandedMajorCache: Record<string, string[]> = {};

function toggleMajorGroup(majorKey: string): void {
  if (expandedMajorKeys.value.has(majorKey)) {
    expandedMajorKeys.value.delete(majorKey);
  } else {
    expandedMajorKeys.value.add(majorKey);
  }
  if (selectedGameId.value) {
    gameExpandedMajorCache[selectedGameId.value] = Array.from(expandedMajorKeys.value);
  }
}

function toggleMinorGroup(minorKey: string): void {
  if (expandedMinorKeys.value.has(minorKey)) {
    expandedMinorKeys.value.delete(minorKey);
  } else {
    expandedMinorKeys.value.add(minorKey);
  }
}

function ensureVersionExpanded(versionStr: string): void {
  const { majorKey, minorKey } = parseVersionKey(versionStr);
  expandedMajorKeys.value.add(majorKey);
  expandedMinorKeys.value.add(minorKey);
  if (selectedGameId.value) {
    gameExpandedMajorCache[selectedGameId.value] = Array.from(expandedMajorKeys.value);
  }
}

function scrollToActiveVersion(): void {
  nextTick(() => {
    const activeEl = document.querySelector(".version-master-item.active");
    activeEl?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

// 智能二级分层版本分组
const groupedVersionList = computed<VersionMajorGroup[]>(() => {
  const list = filteredVersions.value;
  if (list.length === 0) return [];

  const majorMap = new Map<string, {
    majorKey: string;
    minorMap: Map<string, VersionSummary[]>;
    allItems: VersionSummary[];
  }>();

  for (const item of list) {
    const { majorKey, minorKey } = parseVersionKey(item.version);
    let majorEntry = majorMap.get(majorKey);
    if (!majorEntry) {
      majorEntry = {
        majorKey,
        minorMap: new Map(),
        allItems: [],
      };
      majorMap.set(majorKey, majorEntry);
    }
    majorEntry.allItems.push(item);

    let minorList = majorEntry.minorMap.get(minorKey);
    if (!minorList) {
      minorList = [];
      majorEntry.minorMap.set(minorKey, minorList);
    }
    minorList.push(item);
  }

  const result: VersionMajorGroup[] = [];

  for (const majorEntry of majorMap.values()) {
    majorEntry.allItems.sort(compareVersionsDesc);

    const entries: VersionGroupEntry[] = [];
    const sortedMinorEntries = Array.from(majorEntry.minorMap.entries()).sort((a, b) => {
      return compareVersionsDesc(a[1][0], b[1][0]);
    });

    for (const [minorKey, minorItems] of sortedMinorEntries) {
      minorItems.sort(compareVersionsDesc);
      if (minorItems.length === 1) {
        // 只有一个版本，直接平铺
        entries.push({
          type: "single",
          item: minorItems[0],
        });
      } else {
        // 存在多个补丁版本，增加二级折叠
        entries.push({
          type: "minorGroup",
          group: {
            minorKey,
            items: minorItems,
          },
        });
      }
    }

    const unavailableCount = majorEntry.allItems.filter((v) => isVersionUnavailable(v)).length;

    result.push({
      majorKey: majorEntry.majorKey,
      totalCount: majorEntry.allItems.length,
      unavailableCount,
      entries,
      allItems: majorEntry.allItems,
    });
  }

  result.sort((a, b) => {
    if (a.allItems[0] && b.allItems[0]) {
      return compareVersionsDesc(a.allItems[0], b.allItems[0]);
    }
    return b.majorKey.localeCompare(a.majorKey);
  });

  return result;
});

// 监听游戏、模块与版本变化，自动展开与恢复
watch(
  () => [selectedDomainId.value, versions.value],
  () => {
    if (selectedGameId.value && gameExpandedMajorCache[selectedGameId.value]) {
      expandedMajorKeys.value = new Set(gameExpandedMajorCache[selectedGameId.value]);
    } else {
      expandedMajorKeys.value = new Set();
    }

    if (selectedVersion.value) {
      ensureVersionExpanded(selectedVersion.value);
    } else if (groupedVersionList.value.length > 0 && expandedMajorKeys.value.size === 0) {
      expandedMajorKeys.value.add(groupedVersionList.value[0].majorKey);
    }
    scrollToActiveVersion();
  },
  { immediate: true },
);

// 监听健康筛选与搜索，自动展开匹配的大版本并在清除后精准恢复
watch(
  () => [versionFilterState.value, versionSearchQuery.value] as const,
  ([filterState, query]) => {
    if (filterState !== "all" || (typeof query === "string" && query.trim())) {
      // 搜索或筛选中：自动展开所有匹配的大版本
      for (const g of groupedVersionList.value) {
        expandedMajorKeys.value.add(g.majorKey);
      }
    } else {
      // 清除搜索或筛选：恢复原先记忆状态或展开选中版本所在的大版本
      if (selectedGameId.value && gameExpandedMajorCache[selectedGameId.value]) {
        expandedMajorKeys.value = new Set(gameExpandedMajorCache[selectedGameId.value]);
      } else {
        expandedMajorKeys.value = new Set();
      }
      if (selectedVersion.value) {
        ensureVersionExpanded(selectedVersion.value);
      } else if (groupedVersionList.value.length > 0) {
        expandedMajorKeys.value.add(groupedVersionList.value[0].majorKey);
      }
    }
    scrollToActiveVersion();
  },
);

const tabTitle = computed(() => {
  switch (tab.value) {
    case "games": return "游戏入口管理";
    case "domains": return "数据模块管理";
    case "content": return "版本管理";
    case "probe": return "采集与探活监控";
    case "retention": return "数据保留与自动清理";
  }
});

async function refreshAllData(): Promise<void> {
  await withLoading(async (signal) => {
    await loadCatalog(signal);
    if (selectedDomainId.value) {
      const response = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = response.items;
      if (selectedVersion.value) {
        await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
      }
    }
    if (tab.value === "retention") {
      await Promise.all([
        loadRetentionConfig(signal),
        loadRetentionStatus(signal, true),
      ]);
    }
    success.value = "数据已全部刷新至最新状态。";
  });
}

const activeFailuresCount = computed(() => {
  return Object.keys(syncStatus.value?.latest_refresh?.failures || {}).length;
});

function resolveGameIcon(id: string, source?: string): string | undefined {
  const clean = source?.trim();
  if (clean?.startsWith("builtin:")) return gameIcons[clean.slice("builtin:".length)] || gameIcons[id];
  return clean || gameIcons[id];
}

function useFallbackIcon(event: Event, id: string): void {
  const image = event.currentTarget as HTMLImageElement;
  const fallback = gameIcons[id];
  if (fallback && image.src !== fallback) image.src = fallback;
  else image.hidden = true;
}

function abortAndCreate(): AbortController {
  controller?.abort();
  controller = new AbortController();
  return controller;
}

function showError(reason: unknown): void {
  if (reason instanceof DOMException && reason.name === "AbortError") return;
  error.value = reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : String(reason);
  success.value = "";
  if (reason instanceof ApiError && reason.status === 401) authenticated.value = false;
}

async function withLoading(action: (signal: AbortSignal) => Promise<void>): Promise<void> {
  loading.value = true;
  error.value = "";
  success.value = "";
  const request = abortAndCreate();
  try {
    await action(request.signal);
  } catch (reason) {
    showError(reason);
  } finally {
    loading.value = false;
  }
}

async function loadCatalog(signal?: AbortSignal): Promise<void> {
  catalog.value = await adminApi.catalog(token.value.trim(), signal);
  selectedGameId.value = catalog.value.games.some((item) => item.id === selectedGameId.value)
    ? selectedGameId.value
    : catalog.value.games[0]?.id || "";
  selectedDomainId.value = catalog.value.domains.some((item) => item.id === selectedDomainId.value)
    ? selectedDomainId.value
    : gameDomains.value[0]?.id || catalog.value.domains[0]?.id || "";
  if (catalog.value.games.length) selectGame(selectedGameId.value);
}

async function login(): Promise<void> {
  if (!token.value.trim()) {
    error.value = "请输入管理员密码 / Token。";
    return;
  }
  await withLoading(async (signal) => {
    await loadCatalog(signal);
    localStorage.setItem(TOKEN_STORAGE_KEY, token.value.trim());
    authenticated.value = true;
    syncStatus.value = await adminApi.syncStatus(token.value.trim(), signal).catch(() => null);
    await loadSyncRunStatus();
    await resumeAdminOperation();
  });
}

function logout(): void {
  stopProbePolling();
  stopOperationPolling();
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  token.value = "";
  authenticated.value = false;
  catalog.value = { games: [], domains: [] };
  versions.value = [];
  syncStatus.value = null;
}

onMounted(async () => {
  document.title = "管理控制台 | GMI";
  document.addEventListener("click", handleGlobalDropdownClick);
  if (token.value.trim()) {
    await withLoading(async (signal) => {
      await loadCatalog(signal);
      localStorage.setItem(TOKEN_STORAGE_KEY, token.value.trim());
      authenticated.value = true;
      syncStatus.value = await adminApi.syncStatus(token.value.trim(), signal).catch(() => null);
      await loadSyncRunStatus();
      await resumeAdminOperation();
    });
  }
});

async function refreshSyncStatus(): Promise<void> {
  await withLoading(async (signal) => {
    syncStatus.value = await adminApi.syncStatus(token.value.trim(), signal);
    await loadSyncRunStatus();
  });
}

async function loadProbeStatus(): Promise<void> {
  try {
    probeStatus.value = await adminApi.probeStatus(token.value.trim());
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
  }
}

function startProbePolling(): void {
  stopProbePolling();
  probePollTimer = window.setInterval(async () => {
    if (!authenticated.value || tab.value !== "probe") return;
    await loadProbeStatus();
    await loadSyncRunStatus();
  }, 2500);
}

function stopProbePolling(): void {
  if (probePollTimer !== null) {
    window.clearInterval(probePollTimer);
    probePollTimer = null;
  }
}

async function openProbe(): Promise<void> {
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
  tab.value = "probe";
  await loadProbeStatus();
  await loadSyncRunStatus();
  try {
    probeSchedule.value = await adminApi.probeSchedule(token.value.trim());
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
  }
  try {
    const fetchedSyncSchedule = await adminApi.syncSchedule(token.value.trim());
    if (fetchedSyncSchedule) {
      const times = Array.isArray(fetchedSyncSchedule.times) ? [...fetchedSyncSchedule.times] : ["04:45", "14:00"];
      while (times.length < 2) times.push("");
      syncSchedule.value = {
        enabled: Boolean(fetchedSyncSchedule.enabled),
        times,
      };
    }
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
  }
  startProbePolling();
}

async function saveProbeSchedule(): Promise<void> {
  const confirmed = window.confirm("确定要保存并更新下载链接探活策略吗？");
  if (!confirmed) return;
  await withLoading(async (signal) => {
    probeSchedule.value = await adminApi.saveProbeSchedule(probeSchedule.value, token.value, signal);
    success.value = "探活计划已保存。当前仅保存配置，需由系统计划任务按间隔触发。";
  });
}

// --- 数据保留与自动清理控制台 (Retention & Storage Cleanup Console) ---
const retentionConfig = ref<RetentionConfig>({
  cache_days: 30,
  observation_days: 90,
  interval_hours: 24,
});
const retentionStatus = ref<RetentionStatus | null>(null);
const retentionRunning = ref<boolean>(false);
const retentionSaving = ref<boolean>(false);
let retentionStatusTimer: number | null = null;
let retentionStatusController: AbortController | null = null;
let retentionStatusGeneration = 0;
let retentionStatusBusy = false;
let retentionRunController: AbortController | null = null;
let retentionRunGeneration = 0;
let retentionSaveController: AbortController | null = null;
let retentionSaveGeneration = 0;

function cancelRetentionRun(): void {
  retentionRunGeneration += 1;
  retentionRunController?.abort();
  retentionRunController = null;
  retentionRunning.value = false;
}

function cancelRetentionSave(): void {
  retentionSaveGeneration += 1;
  retentionSaveController?.abort();
  retentionSaveController = null;
  retentionSaving.value = false;
}

function cancelRetentionStatusRequests(): void {
  retentionStatusGeneration += 1;
  retentionStatusController?.abort();
  retentionStatusController = null;
  retentionStatusBusy = false;
}

function stopRetentionStatusPolling(): void {
  if (retentionStatusTimer !== null) {
    window.clearInterval(retentionStatusTimer);
    retentionStatusTimer = null;
  }
}

function startRetentionStatusPolling(): void {
  stopRetentionStatusPolling();
  retentionStatusTimer = window.setInterval(() => {
    if (authenticated.value && tab.value === "retention" && !retentionRunning.value && !retentionSaving.value && !retentionStatusBusy) {
      void loadRetentionStatus();
    }
  }, 45_000);
}

function retentionSourceLabel(source: string | null | undefined): string {
  if (source === "manual") return "管理员手动触发";
  if (source === "scheduled") return "定时调度自动执行";
  if (source === "startup") return "系统启动时自动执行";
  return source || "未知来源";
}

function retentionDurationText(startedAt: string | null | undefined, finishedAt: string | null | undefined): string {
  if (!startedAt || !finishedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = new Date(finishedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const sec = (end - start) / 1000;
  return sec < 1 ? `${(sec * 1000).toFixed(0)} ms` : `${sec.toFixed(1)} 秒`;
}

async function loadRetentionConfig(signal?: AbortSignal): Promise<void> {
  try {
    const config = await adminApi.getRetentionConfig(token.value.trim(), signal);
    if (config && typeof config.cache_days === "number") {
      retentionConfig.value = {
        cache_days: config.cache_days,
        observation_days: config.observation_days,
        interval_hours: config.interval_hours,
      };
    }
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) {
      showError(reason);
    }
  }
}

async function loadRetentionStatus(signal?: AbortSignal, force = false): Promise<void> {
  if (retentionStatusBusy && !force) return;
  if (force) cancelRetentionStatusRequests();
  const generation = ++retentionStatusGeneration;
  const controller = new AbortController();
  retentionStatusController?.abort();
  retentionStatusController = controller;
  retentionStatusBusy = true;
  const abortFromCaller = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", abortFromCaller, { once: true });
  }
  try {
    const status = await adminApi.getRetentionStatus(token.value.trim(), controller.signal);
    if (generation === retentionStatusGeneration && !controller.signal.aborted && authenticated.value && tab.value === "retention") {
      retentionStatus.value = status;
    }
  } catch (reason) {
    if (generation === retentionStatusGeneration && !isAbortError(reason)) {
      showError(reason);
    }
  } finally {
    if (signal) signal.removeEventListener("abort", abortFromCaller);
    if (generation === retentionStatusGeneration) {
      retentionStatusBusy = false;
      retentionStatusController = null;
    }
  }
}

async function openRetention(): Promise<void> {
  tab.value = "retention";
  startRetentionStatusPolling();
  await withLoading(async (signal) => {
    cancelRetentionStatusRequests();
    await Promise.all([
        loadRetentionConfig(signal),
        loadRetentionStatus(signal, true),
    ]);
  });
}

async function saveRetentionConfig(): Promise<void> {
  const cfg = retentionConfig.value;
  const cacheDays = Number(cfg.cache_days);
  const obsDays = Number(cfg.observation_days);
  const intHours = Number(cfg.interval_hours);

  if (
    !Number.isInteger(cacheDays) ||
    cacheDays < 1 ||
    cacheDays > 36500 ||
    !Number.isInteger(obsDays) ||
    obsDays < 1 ||
    obsDays > 36500 ||
    !Number.isInteger(intHours) ||
    intHours < 1 ||
    intHours > 8760
  ) {
    error.value = "清理配置参数不合法：保留天数需为 1～36500 之间的整数，清理周期需为 1～8760 小时之间的整数。";
    return;
  }

  cancelRetentionSave();
  const generation = ++retentionSaveGeneration;
  const controller = new AbortController();
  retentionSaveController = controller;
  retentionSaving.value = true;
  cancelRetentionStatusRequests();
  error.value = "";
  success.value = "";
  try {
    const payload: RetentionConfig = {
      cache_days: cacheDays,
      observation_days: obsDays,
      interval_hours: intHours,
    };
    const saved = await adminApi.updateRetentionConfig(payload, token.value.trim(), controller.signal);
    if (generation !== retentionSaveGeneration || controller.signal.aborted || !authenticated.value || tab.value !== "retention") return;
    retentionConfig.value = { ...saved };
    success.value = "数据清理配置已保存并立即唤醒调度器生效！";
  } catch (reason) {
    if (generation === retentionSaveGeneration && !isAbortError(reason)) showError(reason);
  } finally {
    if (generation === retentionSaveGeneration) {
      retentionSaving.value = false;
      retentionSaveController = null;
    }
  }
}

async function runRetentionManual(): Promise<void> {
  const confirmed = window.confirm("确定要立即执行一次数据保留与存储清理吗？该操作将删除过期缓存文件与历史探活观测记录。");
  if (!confirmed) return;

  cancelRetentionRun();
  const generation = ++retentionRunGeneration;
  const controller = new AbortController();
  retentionRunController = controller;
  retentionRunning.value = true;
  cancelRetentionStatusRequests();
  error.value = "";
  success.value = "";
  try {
    const result = await adminApi.runRetention(token.value.trim(), controller.signal);
    if (generation !== retentionRunGeneration || controller.signal.aborted || !authenticated.value || tab.value !== "retention") return;
    retentionStatus.value = result;
    const res = result.result;
    const details = res
      ? `缓存清除: ${res.cache_deleted}，临时文件清除: ${res.temp_deleted}，运维记录清除: ${res.operation_deleted}，探活记录清除: ${res.observations_deleted}，跳过: ${res.skipped}`
      : "";
    success.value = `数据清理任务已执行完成！${details}`;
  } catch (reason) {
    if (generation === retentionRunGeneration && !isAbortError(reason)) showError(reason);
  } finally {
    if (generation === retentionRunGeneration) {
      retentionRunning.value = false;
      retentionRunController = null;
    }
  }
}

function resetRetentionDefaults(): void {
  retentionConfig.value = {
    cache_days: 30,
    observation_days: 90,
    interval_hours: 24,
  };
  success.value = "已载入推荐默认配置（请点击保存以生效）。";
}

function adjustRetentionField(field: "cache_days" | "observation_days" | "interval_hours", delta: number): void {
  const current = Number(retentionConfig.value[field]) || 0;
  let next = current + delta;
  if (field === "cache_days" || field === "observation_days") {
    next = Math.max(1, Math.min(36500, next));
  } else if (field === "interval_hours") {
    next = Math.max(1, Math.min(8760, next));
  }
  retentionConfig.value[field] = next;
}

function setRetentionPreset(field: "cache_days" | "observation_days" | "interval_hours", val: number): void {
  retentionConfig.value[field] = val;
}

const retentionHeroTitle = computed(() => {
  if (retentionRunning.value) return "正在执行数据保留清理…";
  if (!retentionStatus.value || !retentionStatus.value.started_at) return "自动清理引擎待命中";
  if (retentionStatus.value.error) return "上次清理执行异常";
  if (retentionStatus.value.source === "scheduled") return "定时自动清理完成 · 引擎就绪";
  if (retentionStatus.value.source === "manual") return "手动清理执行完成 · 引擎就绪";
  if (retentionStatus.value.source === "startup") return "启动环境清理完成 · 引擎就绪";
  return "数据保留清理引擎已就绪";
});

// --- 运维操作控制台 (start -> status polling -> cancel) ---
const opAction = ref<"both" | "discover" | "probe">("both");
const opScope = ref<"all" | "custom">("all");
const opPlatformScope = ref<"all" | "android" | "pc">("all");
const opSelectedGameIds = ref<string[]>([]);
const opTimeout = ref<number>(10);
const opWorkers = ref<number>(8);
const opRunning = ref<boolean>(false);
const opJob = ref<AdminOperationJob | null>(null);
const opResult = ref<AdminOperationResult | null>(null);
const opExecutionTime = ref<number | null>(null);
const opTerminalLogs = ref<string[]>([]);
const opLogOffset = ref(0);
const opTerminalHidden = ref(false);
let operationPollTimer: number | null = null;
let operationPollBusy = false;

const operationScope = computed(() =>
  restoredOperationScope(opJob.value?.scope ?? opResult.value?.scope),
);
const operationScopeText = computed(() => operationScopeLabel(operationScope.value));
const operationControlsLocked = computed(() =>
  operationControlsDisabled(loading.value, opJob.value?.status),
);

const probeTableFilter = ref<"all" | "available" | "unavailable" | "unknown" | "failed">("all");

const filteredProbeItems = computed(() => {
  if (!opResult.value?.probe?.items) return [];
  const items = opResult.value.probe.items;
  if (probeTableFilter.value === "available") {
    return items.filter((it) => it.available === true);
  }
  if (probeTableFilter.value === "unavailable") {
    return items.filter((it) => it.available === false);
  }
  if (probeTableFilter.value === "unknown") {
    return items.filter((it) => it.available !== true && it.available !== false);
  }
  if (probeTableFilter.value === "failed") {
    return items.filter((it) => it.ok === false);
  }
  return items;
});

const opProgressPercent = computed(() => {
  const total = opJob.value?.total || 0;
  return total > 0 ? Math.min(100, Math.round(((opJob.value?.completed || 0) / total) * 100)) : 0;
});

function stopOperationPolling(): void {
  if (operationPollTimer !== null) {
    window.clearInterval(operationPollTimer);
    operationPollTimer = null;
  }
}

async function applyOperationJob(job: AdminOperationJob, isInitialRestore = false, incremental = false): Promise<void> {
  const sameJob = opJob.value?.job_id === job.job_id;
  opJob.value = job;
  const restoredScope = restoredOperationScope(job.scope ?? job.result?.scope);
  if (restoredScope) opPlatformScope.value = restoredScope;
  opRunning.value = job.status === "running" || job.status === "cancelling";
  if (incremental && sameJob) {
    opTerminalLogs.value = [...opTerminalLogs.value, ...(job.logs || [])];
    opLogOffset.value = job.log_total ?? (opLogOffset.value + (job.logs || []).length);
    if (job.logs?.length) opTerminalHidden.value = false;
  } else {
    opTerminalLogs.value = [...(job.logs || [])];
    opLogOffset.value = job.logs?.length || 0;
    opTerminalHidden.value = false;
  }
  if (opRunning.value) return;

  stopOperationPolling();
  sessionStorage.removeItem(OPERATION_JOB_KEY);
  if (job.result) {
    probeTableFilter.value = "all";
    opResult.value = job.result;
    if (job.started_at && job.finished_at) {
      const start = new Date(job.started_at).getTime();
      const end = new Date(job.finished_at).getTime();
      opExecutionTime.value = Math.max(0, Math.round((end - start) / 100) / 10);
    }
  }
  if (!isInitialRestore) {
    if (job.status === "finished") {
      success.value = "运维操作已全部执行完成！";
      await refreshAllData();
    } else if (job.status === "cancelled") {
      error.value = "运维操作已被管理员手动取消。";
    } else if (job.status === "failed") {
      error.value = `运维操作执行失败：${job.error || "未知异常"}`;
    }
  }
}

async function pollAdminOperation(jobId: string, initial = false): Promise<void> {
  if (operationPollBusy || !authenticated.value) return;
  operationPollBusy = true;
  try {
    const after = initial || opJob.value?.job_id !== jobId ? undefined : opLogOffset.value;
    try {
      await applyOperationJob(await adminApi.operationStatus(jobId, token.value.trim(), undefined, after), initial, after !== undefined);
    } catch (reason) {
      // A stale cursor (or a service-side log reset) is recovered with a full snapshot.
      if (reason instanceof ApiError && reason.status === 422 && after !== undefined) {
        await applyOperationJob(await adminApi.operationStatus(jobId, token.value.trim()), initial, false);
      } else {
        throw reason;
      }
    }
  } catch (reason) {
    stopOperationPolling();
    sessionStorage.removeItem(OPERATION_JOB_KEY);
    showError(reason);
  } finally {
    operationPollBusy = false;
  }
}

function startOperationPolling(jobId: string): void {
  stopOperationPolling();
  operationPollTimer = window.setInterval(() => void pollAdminOperation(jobId), 1000);
}

async function resumeAdminOperation(): Promise<void> {
  if (!authenticated.value) return;
  const jobId = sessionStorage.getItem(OPERATION_JOB_KEY);
  if (jobId) {
    await pollAdminOperation(jobId, true);
    if (opRunning.value) startOperationPolling(jobId);
    return;
  }
  if (!opResult.value && !opRunning.value) {
    try {
      const latestJob = await adminApi.latestOperation(token.value.trim());
      if (latestJob) {
        await applyOperationJob(latestJob, true);
      }
    } catch {
      // 忽略未找到历史记录
    }
  }
}

function toggleGameSelection(gameId: string): void {
  const index = opSelectedGameIds.value.indexOf(gameId);
  if (index >= 0) {
    opSelectedGameIds.value.splice(index, 1);
  } else {
    opSelectedGameIds.value.push(gameId);
  }
}

function selectAllGames(): void {
  opSelectedGameIds.value = catalog.value.games.map((g) => g.id);
}

function clearSelectedGames(): void {
  opSelectedGameIds.value = [];
}

function isGameSelected(gameId: string): boolean {
  return opSelectedGameIds.value.includes(gameId);
}

function appendOpLog(line: string): void {
  opTerminalHidden.value = false;
  opTerminalLogs.value.push(line);
  if (opTerminalLogs.value.length > 300) {
    opTerminalLogs.value = opTerminalLogs.value.slice(-300);
  }
}

async function refreshTerminalLogs(): Promise<void> {
  if (operationPollBusy || !authenticated.value) return;
  operationPollBusy = true;
  try {
    const jobId = opJob.value?.job_id;
    const job = jobId
      ? await adminApi.operationStatus(jobId, token.value.trim())
      : await adminApi.latestOperation(token.value.trim());
    await applyOperationJob(job, false, false);
    await Promise.all([loadProbeStatus(), loadSyncRunStatus()]);
  } catch (reason) {
    showError(reason);
  } finally {
    operationPollBusy = false;
  }
}

function clearOpResult(): void {
  opResult.value = null;
  opExecutionTime.value = null;
  probeTableFilter.value = "all";
}

function gameDisplayName(gameId: string): string {
  const item = catalog.value.games.find((g) => g.id === gameId);
  return item ? `${item.name} (${item.id})` : gameId;
}

async function executeAdminOperation(): Promise<void> {
  const actions: ("discover" | "probe")[] =
    opAction.value === "both"
      ? ["discover", "probe"]
      : [opAction.value];

  if (opScope.value === "custom" && opSelectedGameIds.value.length === 0) {
    error.value = "请至少勾选一款游戏，或切换为【全部游戏】模式。";
    return;
  }

  const payload: AdminOperationPayload = {
    actions,
    scope: opPlatformScope.value,
    all_games: opScope.value === "all",
    game_ids: opScope.value === "custom" ? [...opSelectedGameIds.value] : undefined,
    timeout: Math.max(1, Math.min(60, Number(opTimeout.value) || 10)),
    workers: Math.max(1, Math.min(16, Number(opWorkers.value) || 8)),
  };

  const actionText =
    opAction.value === "both"
      ? "【查找新版本 + 探活全量】"
      : opAction.value === "discover"
      ? "【仅查找新版本 (discover)】"
      : "【仅探活历史版本 (probe)】";
  const scopeText =
    opScope.value === "all"
      ? `全部 ${catalog.value.games.length || "已注册"} 款游戏`
      : `${opSelectedGameIds.value.length} 款指定游戏（${opSelectedGameIds.value.join(", ")}）`;
  const platformText =
    opPlatformScope.value === "all"
      ? "全量数据 (APK + PC)"
      : opPlatformScope.value === "android"
      ? "仅 Android (APK 直链)"
      : "仅 PC 客户端 (Windows)";

  const confirmed = window.confirm(`确定要启动 ${actionText} 操作吗？\n目标范围：${scopeText}\n数据类型：${platformText}\n启动后可查看实时进度，也可以取消未开始的任务。`);
  if (!confirmed) return;

  opRunning.value = true;
  opResult.value = null;
  opExecutionTime.value = null;
  probeTableFilter.value = "all";
  error.value = "";
  success.value = "";

  const timeStr = new Date().toLocaleTimeString();
  appendOpLog(`[${timeStr}] 🚀 启动运维操作 POST /api/v1/admin/operations/start`);
  appendOpLog(`[${timeStr}] 动作: [${actions.join(", ")}] | 数据范围: ${operationScopeLabel(payload.scope)} | 游戏范围: ${opScope.value === "all" ? "全部游戏 (all_games=true)" : opSelectedGameIds.value.join(", ")} | 超时: ${payload.timeout}s | 并发: ${payload.workers}`);

  await withLoading(async (signal) => {
    try {
      const job = await adminApi.startOperation(payload, token.value.trim(), signal);
      sessionStorage.setItem(OPERATION_JOB_KEY, job.job_id);
      await applyOperationJob(job);
      if (opRunning.value) startOperationPolling(job.job_id);
    } catch (err) {
      const finishTime = new Date().toLocaleTimeString();
      appendOpLog(`[${finishTime}] ✕ 运维操作请求失败: ${err instanceof Error ? err.message : "未知错误"}`);
      opRunning.value = false;
      throw err;
    }
  });
}

async function cancelAdminOperation(): Promise<void> {
  const jobId = opJob.value?.job_id;
  if (!jobId || !window.confirm("确定要取消当前运维任务吗？已完成的数据会保留。")) return;
  try {
    await applyOperationJob(await adminApi.cancelOperation(jobId, token.value.trim()));
    if (opRunning.value) startOperationPolling(jobId);
  } catch (reason) {
    showError(reason);
  }
}

const syncRunStatus = ref<SyncRunStatus | null>(null);

async function loadSyncRunStatus(): Promise<void> {
  if (!authenticated.value) return;
  try {
    syncRunStatus.value = await adminApi.syncRunStatus(token.value.trim());
  } catch {
    // optional status
  }
}

const syncSchedule = ref<SyncSchedule>({ enabled: true, times: ["04:45", "14:00"] });

function scheduleTimesText(): string {
  const times = (syncSchedule.value?.times || []).filter(Boolean);
  return times.length ? times.join(" / ") : "未配置";
}

async function saveSyncSchedule(): Promise<void> {
  const validTimes = (syncSchedule.value?.times || [])
    .map((item) => (item || "").trim())
    .filter(Boolean);

  if (syncSchedule.value.enabled && validTimes.length === 0) {
    error.value = "请至少配置一个有效的每日采集时间点（例如 04:45）";
    return;
  }

  const confirmed = window.confirm(`确定要保存每日采集计划（时间点: ${validTimes.join(", ")}）吗？`);
  if (!confirmed) return;

  await withLoading(async (signal) => {
    const payload: SyncSchedule = {
      enabled: syncSchedule.value.enabled,
      times: validTimes,
    };
    const saved = await adminApi.saveSyncSchedule(payload, token.value, signal);
    const times = Array.isArray(saved.times) ? [...saved.times] : validTimes;
    while (times.length < 2) times.push("");
    syncSchedule.value = {
      enabled: saved.enabled,
      times,
    };
    success.value = "采集计划已保存。当前仅保存配置，需由系统计划任务按配置触发。";
  });
}

function probeStuckRows(): string[] {
  const log = probeStatus.value?.log || [];
  const stuck: string[] = [];
  for (const line of log) {
    const m = line.match(/^\[probe\] \(\d+\/\d+\) probing (.+)$/);
    if (m) {
      const url = m[1];
      const hasDone = log.some((item) => item.includes(`done `) && item.includes(url));
      if (!hasDone) {
        stuck.push(url.length > 90 ? url.slice(0, 90) + "…" : url);
      }
    }
  }
  return stuck.slice(-8);
}

function probeProgress(): string {
  const log = probeStatus.value?.log || [];
  const m = log.find((line) => /^\[probe\] \(/.test(line));
  return m ? m.replace(/^\[probe\] /, "") : "准备中…";
}

function openGames(): void {
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
  tab.value = "games";
  stopProbePolling();
  selectGame(selectedGameId.value);
}

function selectGame(id: string): void {
  selectedGameId.value = id;
  newGame.value = false;
  const item = catalog.value.games.find((row) => row.id === id);
  if (item) {
    gameDraft.value = {
      id: item.id,
      name: item.name,
      sub_name: item.sub_name,
      platform: item.platform,
      icon_source: item.icon_source,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order ?? 0,
    };
  }
  const available = catalog.value.domains.filter((row) => row.game_id === id);
  if (!available.some((row) => row.id === selectedDomainId.value)) selectedDomainId.value = available[0]?.id || "";
}

function startGame(): void {
  newGame.value = true;
  gameDraft.value = {
    id: "",
    name: "",
    sub_name: "",
    platform: "PC",
    icon_source: "",
    is_enabled: true,
    sort_order: catalog.value.games.length * 10,
  };
}

function preventEnterSubmit(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && target.tagName === "INPUT") {
    event.preventDefault();
  }
}

async function saveGame(): Promise<void> {
  const actionText = newGame.value
    ? `确定要创建新游戏【${gameDraft.value.name || gameDraft.value.id}】吗？`
    : `确定要保存游戏【${gameDraft.value.name || gameDraft.value.id}】的配置修改吗？`;
  if (!window.confirm(actionText)) return;

  await withLoading(async (signal) => {
    const payload = { ...gameDraft.value };
    if (newGame.value) await adminApi.createGame(payload, token.value, signal);
    else await adminApi.updateGame(payload.id, payload, token.value, signal);
    await loadCatalog(signal);
    selectGame(payload.id);
    success.value = newGame.value ? "游戏已成功创建。" : "游戏配置已成功保存。";
    newGame.value = false;
  });
}

async function removeGame(): Promise<void> {
  if (!newGame.value && !window.confirm(`确定要彻底删除空游戏【${gameDraft.value.name || gameDraft.value.id}】吗？仅空游戏可删除，此操作不可撤销。`)) return;
  await withLoading(async (signal) => {
    await adminApi.deleteGame(gameDraft.value.id, token.value, signal);
    await loadCatalog(signal);
    success.value = "空游戏已删除。";
  });
}

function revertGameDraft(): void {
  if (newGame.value) {
    startGame();
  } else {
    selectGame(gameDraft.value.id);
  }
  success.value = "已还原游戏配置。";
}

function adjustGameSort(delta: number): void {
  const current = gameDraft.value.sort_order ?? 0;
  gameDraft.value.sort_order = Math.max(0, current + delta);
}

function setGamePlatform(platform: string): void {
  gameDraft.value.platform = platform;
}

function setGameIconPreset(preset: string): void {
  gameDraft.value.icon_source = preset;
}

function openDomainsForGame(gameId: string): void {
  domainGameFilter.value = gameId;
  selectedGameId.value = gameId;
  tab.value = "domains";
  const target = catalog.value.domains.find((item) => item.game_id === gameId);
  if (target) selectDomain(target.id);
  else startDomain();
}

const currentGameDomainCount = computed(() =>
  catalog.value.domains.filter((d) => d.game_id === gameDraft.value.id).length
);

function selectDomain(id: string): void {
  selectedDomainId.value = id;
  newDomain.value = false;
  const item = catalog.value.domains.find((row) => row.id === id);
  if (item) {
    domainDraft.value = {
      id: item.id,
      game_id: item.game_id,
      kind: item.kind,
      platform: item.platform,
      capabilities: item.capabilities.join(", "),
      adapter: item.adapter,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order ?? 0,
    };
  }
}

function startDomain(): void {
  newDomain.value = true;
  const targetGameId = (domainGameFilter.value && domainGameFilter.value !== "all")
    ? domainGameFilter.value
    : (selectedGameId.value || catalog.value.games[0]?.id || "");
  domainDraft.value = {
    id: "",
    game_id: targetGameId,
    kind: "packages",
    platform: "Windows",
    capabilities: "packages",
    adapter: "generic",
    is_enabled: true,
    sort_order: catalog.value.domains.length * 10,
  };
}

function openDomains(): void {
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
  tab.value = "domains";
  stopProbePolling();
  const target = catalog.value.domains.find((item) => item.id === selectedDomainId.value) || catalog.value.domains[0];
  if (target) selectDomain(target.id);
  else startDomain();
}

function selectModuleGame(id: string): void {
  selectGame(id);
  const first = gameDomains.value[0];
  if (first) selectDomain(first.id);
  else startDomain();
}

function formatSyncTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function domainBadge(item: AdminDomain): string {
  if (item.kind === "resources") return "RES";
  if (item.kind === "chunks") return "CHK";
  if (item.kind === "apk") return "APK";
  if (item.kind === "files") return "FILE";
  if (item.kind === "patches") return "PATCH";
  return item.platform.toLowerCase().includes("android") ? "APK" : "PC";
}

function domainKindIcon(kind: string): string {
  if (kind === "apk") return "📱";
  if (kind === "chunks") return "🧩";
  if (kind === "patches") return "🔄";
  if (kind === "files") return "📄";
  if (kind === "resources") return "🎨";
  if (kind === "mixed") return "🔀";
  return "📦";
}

const currentDomainObj = computed(() => {
  return catalog.value.domains.find((d) => d.id === domainDraft.value.id) || null;
});

const currentDomainGameName = computed(() => {
  const gid = domainDraft.value.game_id || currentDomainObj.value?.game_id;
  return catalog.value.games.find((g) => g.id === gid)?.name || "未知游戏";
});

const domainCapabilityOptions = [
  { key: "packages", label: "packages 完整包", icon: "📦", desc: "完整游戏客户端离线分卷/压缩包" },
  { key: "files", label: "files 散文件", icon: "📄", desc: "分块离散文件及清单直链" },
  { key: "patches", label: "patches 补丁", icon: "🔄", desc: "游戏小版本增量与差分补丁" },
  { key: "chunks", label: "chunks 块存储", icon: "🧩", desc: "Chunk 流式分块与哈希元数据" },
  { key: "apk", label: "apk 安装包", icon: "📱", desc: "移动端官方原版与渠道安装包" },
  { key: "resources", label: "resources 资源", icon: "🎨", desc: "游戏客户端运行时资源与扩展包" },
  { key: "archive", label: "archive 归档", icon: "🗄️", desc: "全部历史版本数据全量归档浏览" },
];

function isDomainCapabilityActive(cap: string): boolean {
  const list = (domainDraft.value.capabilities || "")
    .split(",")
    .map((c) => c.trim().toLowerCase())
    .filter(Boolean);
  return list.includes(cap.toLowerCase());
}

function toggleDomainCapability(cap: string): void {
  const list = (domainDraft.value.capabilities || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  const idx = list.findIndex((c) => c.toLowerCase() === cap.toLowerCase());
  if (idx >= 0) {
    list.splice(idx, 1);
  } else {
    list.push(cap);
  }
  domainDraft.value.capabilities = list.join(", ");
}

function setDomainKind(k: string): void {
  domainDraft.value.kind = k;
  if (!domainDraft.value.capabilities || domainDraft.value.capabilities === "packages") {
    if (k === "apk") domainDraft.value.capabilities = "apk, archive";
    else if (k === "chunks") domainDraft.value.capabilities = "chunks, archive";
    else if (k === "patches") domainDraft.value.capabilities = "patches, archive";
    else if (k === "resources") domainDraft.value.capabilities = "resources, archive";
    else if (k === "files") domainDraft.value.capabilities = "files, archive";
  }
}

function setDomainPlatform(p: string): void {
  domainDraft.value.platform = p;
}

function setDomainAdapter(a: string): void {
  domainDraft.value.adapter = a;
}

function adjustDomainSort(delta: number): void {
  const cur = Number(domainDraft.value.sort_order) || 0;
  domainDraft.value.sort_order = Math.max(0, cur + delta);
}

function revertDomainDraft(): void {
  if (selectedDomainId.value && !newDomain.value) {
    selectDomain(selectedDomainId.value);
    success.value = "已还原为已保存的模块配置。";
  }
}

function domainPayload(): Partial<AdminDomain> {
  return {
    ...domainDraft.value,
    capabilities: domainDraft.value.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
  };
}

async function saveDomain(): Promise<void> {
  const actionText = newDomain.value
    ? `确定要创建新数据模块【${domainDraft.value.id}】吗？`
    : `确定要保存数据模块【${domainDraft.value.id}】的配置修改吗？`;
  if (!window.confirm(actionText)) return;

  await withLoading(async (signal) => {
    const payload = domainPayload();
    if (newDomain.value) await adminApi.createDomain(payload, token.value, signal);
    else await adminApi.updateDomain(payload.id || "", payload, token.value, signal);
    await loadCatalog(signal);
    selectDomain(payload.id || "");
    success.value = newDomain.value ? "数据模块已创建。" : "数据模块配置已保存。";
    newDomain.value = false;
  });
}

async function removeDomain(): Promise<void> {
  if (!window.confirm(`确定要彻底删除空模块【${domainDraft.value.id}】吗？仅没有版本和候选记录的空模块可删除，此操作不可撤销。`)) return;
  await withLoading(async (signal) => {
    await adminApi.deleteDomain(domainDraft.value.id, token.value, signal);
    await loadCatalog(signal);
    success.value = "空模块已删除。";
  });
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

async function loadEditableVersion(domainId = selectedDomainId.value, version = selectedVersion.value): Promise<void> {
  if (!domainId || !version) {
    editableLoaded.value = false;
    return;
  }
  editableLoading.value = true;
  try {
    const data = await adminApi.editableVersion(domainId, version, token.value.trim());
    const rawArtifacts = (data.artifacts || []).map((art, idx) => ({
      kind: art.kind || "file",
      name: art.name || "",
      part: art.part ?? (idx + 1),
      size: art.size ?? 0,
      checksum_type: art.checksum_type || "",
      checksum_value: art.checksum_value || "",
      attributesJson: JSON.stringify(art.attributes || {}, null, 2),
      urls: (art.urls || []).map((u, uIdx) => ({
        id: u.id,
        persisted_url: u.url || "",
        url: u.url || "",
        priority: u.priority ?? uIdx,
        source_kind: u.source_kind || "official",
      })),
    }));

    const attrs = (data.attributes || {}) as Record<string, any>;
    const firstArt = rawArtifacts[0];
    let artAttrs: Record<string, any> = {};
    if (firstArt?.attributesJson) {
      try {
        artAttrs = JSON.parse(firstArt.attributesJson || "{}");
      } catch {
        // ignore
      }
    }

    editableDraft.value = {
      channel: typeof attrs.channel === "string" ? attrs.channel : "official",
      version_code: typeof attrs.version_code === "number" ? attrs.version_code : null,
      is_visible: data.is_visible ?? true,
      file_created_at_override: data.file_created_at_override || "",
      checksum_etag: String(artAttrs.etag || ""),
      checksum_crc64: String(artAttrs.crc64 || (firstArt?.checksum_type === "crc64" ? firstArt.checksum_value : "")),
      checksum_md5: String(artAttrs.md5 || (firstArt?.checksum_type === "md5" ? firstArt.checksum_value : "")),
      artifacts: rawArtifacts,
      artifactsJson: JSON.stringify(rawArtifacts, null, 2),
      artifactsMode: "visual",
    };

    const initialArtifactsStr = normalizeArtifactsForComparison(
      (data.artifacts || []).map((art) => ({
        kind: art.kind || "file",
        name: art.name || "",
        part: art.part,
        size: art.size,
        checksum_type: art.checksum_type,
        checksum_value: art.checksum_value,
        attributes: (art.attributes || {}) as Record<string, unknown>,
        urls: (art.urls || []).map((u) => ({
          url: u.url || "",
          priority: u.priority ?? 0,
          source_kind: u.source_kind || "official",
        })),
      })),
    );

    originalEditableJson.value = JSON.stringify({
      channel: editableDraft.value.channel.trim(),
      version_code: editableDraft.value.version_code,
      is_visible: editableDraft.value.is_visible,
      file_created_at_override: editableDraft.value.file_created_at_override.trim(),
      checksum_etag: editableDraft.value.checksum_etag.trim(),
      checksum_crc64: editableDraft.value.checksum_crc64.trim(),
      checksum_md5: editableDraft.value.checksum_md5.trim(),
      artifacts: initialArtifactsStr,
    });
    editableLoaded.value = true;
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) {
      showError(reason);
    }
  } finally {
    editableLoading.value = false;
  }
}

async function onContentVersionSelect(version: string): Promise<void> {
  if (selectedVersion.value === version) return;
  if (isEditableDirty.value) {
    const confirmed = window.confirm(
      `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n切换到版本 ${version} 将丢弃未保存的修改，是否确定继续？`,
    );
    if (!confirmed) return;
  }
  selectedVersion.value = version;
  ensureVersionExpanded(version);
  await loadEditableVersion(selectedDomainId.value, version);
  scrollToActiveVersion();
}

function fillCurrentTime(): void {
  editableDraft.value.file_created_at_override = new Date().toISOString();
}

async function discardChanges(): Promise<void> {
  if (!window.confirm("确定要放弃所有未保存的修改并还原为当前服务端配置吗？")) return;
  await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
  success.value = "已放弃修改，表单已还原。";
}

async function saveEditableVersion(): Promise<void> {
  if (!selectedDomainId.value || !selectedVersion.value || !isEditableDirty.value) return;

  const artifactsPayload = buildArtifactsPayload();
  if (artifactsPayload.length !== 1) {
    error.value = "只允许包含一个 APK 文件";
    return;
  }
  const mainArt = artifactsPayload[0];
  mainArt.kind = "apk";
  if (!mainArt.name.trim()) {
    error.value = "APK 文件名不能为空";
    return;
  }
  if (!mainArt.name.trim().toLowerCase().endsWith(".apk")) {
    error.value = "文件名必须以 .apk 结尾";
    return;
  }
  if (mainArt.urls.length !== 1) {
    error.value = "每个版本必须且仅允许包含一条下载链接 (URL)";
    return;
  }
  const firstUrl = mainArt.urls[0].url.trim();
  if (!firstUrl.startsWith("http://") && !firstUrl.startsWith("https://")) {
    error.value = "下载链接 URL 必须使用 http:// 或 https:// 协议";
    return;
  }

  // 注入校验值
  const artAttrs = (mainArt.attributes || {}) as Record<string, unknown>;
  if (editableDraft.value.checksum_etag?.trim()) {
    artAttrs.etag = editableDraft.value.checksum_etag.trim();
  }
  if (editableDraft.value.checksum_crc64?.trim()) {
    artAttrs.crc64 = editableDraft.value.checksum_crc64.trim();
  }
  if (editableDraft.value.checksum_md5?.trim()) {
    artAttrs.md5 = editableDraft.value.checksum_md5.trim();
  }
  mainArt.attributes = artAttrs;

  const payload: AdminEditableVersionPayload = {
    file_created_at_override: editableDraft.value.file_created_at_override.trim() || null,
    file_path: mainArt.name.trim(),
    attributes: {
      channel: editableDraft.value.channel.trim() || "official",
      version_code:
        editableDraft.value.version_code !== null &&
        editableDraft.value.version_code !== undefined &&
        String(editableDraft.value.version_code).trim() !== ""
          ? Number(editableDraft.value.version_code)
          : null,
    },
    artifacts: [mainArt],
  };

  const willProbe = isUrlChanged.value;
  const actionPrompt = willProbe
    ? `确定要保存对版本【${selectedVersion.value}】的修改并立即向官方源探活吗？`
    : `确定要保存对版本【${selectedVersion.value}】的修改吗？`;
  const confirmed = window.confirm(actionPrompt);
  if (!confirmed) return;

  await withLoading(async (signal) => {
    const result = await adminApi.updateEditableVersion(
      selectedDomainId.value,
      selectedVersion.value,
      payload,
      token.value,
      signal,
    );

    // 如果可见性发生变动，同步更新
    if (currentVersionItem.value && currentVersionItem.value.is_visible !== editableDraft.value.is_visible) {
      await adminApi.setVersionVisibility(
        selectedDomainId.value,
        selectedVersion.value,
        editableDraft.value.is_visible,
        token.value,
        signal,
      );
    }

    if (willProbe) {
      try {
        await adminApi.probeVersion(selectedDomainId.value, selectedVersion.value, token.value, signal);
      } catch {
        // 探活失败不阻塞保存
      }
    }

    const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
    versions.value = verRes.items;
    await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
    success.value = willProbe
      ? `版本 ${selectedVersion.value} 修改已保存并已完成探活！`
      : `版本 ${selectedVersion.value} 的配置修改已保存成功。`;
  });
}

async function openContent(id = selectedDomainId.value): Promise<void> {
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
  selectedDomainId.value = id;
  selectDomain(id);
  tab.value = "content";
  stopProbePolling();
  await withLoading(async (signal) => {
    const response = await adminApi.versions(id, token.value, signal);
    versions.value = response.items;
    selectedVersion.value = versions.value[0]?.version || "";
    if (selectedVersion.value) {
      await loadEditableVersion(id, selectedVersion.value);
    } else {
      editableLoaded.value = false;
    }
  });
}

async function toggleVersionVisibility(): Promise<void> {
  const current = selectedVersionSummary.value;
  if (!selectedDomainId.value || !selectedVersion.value || !current) return;
  const actionText = current.is_visible ? "隐藏" : "公开";
  if (!window.confirm(`确定要将版本【${selectedVersion.value}】切换为【${actionText}】状态吗？`)) return;

  await withLoading(async (signal) => {
    await adminApi.setVersionVisibility(
      selectedDomainId.value,
      selectedVersion.value,
      !current.is_visible,
      token.value,
      signal,
    );
    const response = await adminApi.versions(selectedDomainId.value, token.value, signal);
    versions.value = response.items;
    success.value = current.is_visible ? "版本已切换为隐藏状态。" : "版本已切换为公开状态。";
  });
}

async function deleteCurrentVersion(ver = selectedVersion.value): Promise<void> {
  if (!selectedDomainId.value || !ver) return;
  const confirmed = window.confirm(
    `⚠️ 危险操作警告：\n确定要彻底删除版本【${ver}】吗？\n\n此操作将永久清除该版本的所有 Revision 快照、资源文件及下载链接，不可撤销！`,
  );
  if (!confirmed) return;

  await withLoading(async (signal) => {
    await adminApi.deleteVersion(selectedDomainId.value, ver, token.value, signal);
    const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
    versions.value = verRes.items;

    const nextVer = versions.value.find((v) => v.version !== ver)?.version || versions.value[0]?.version || "";
    selectedVersion.value = nextVer;
    if (nextVer) {
      await loadEditableVersion(selectedDomainId.value, nextVer);
    } else {
      editableLoaded.value = false;
    }
    success.value = `版本 ${ver} 已成功永久删除。`;
  });
}

function copyCurrentVersionToCreateDraft(): void {
  if (!editableLoaded.value) {
    error.value = "当前没有加载有效的版本数据供复制。";
    return;
  }
  const clonedArtifacts: EditableArtifactDraft[] = editableDraft.value.artifacts.map((art) => ({
    kind: "apk",
    name: art.name,
    part: 1,
    size: art.size,
    checksum_type: art.checksum_type,
    checksum_value: art.checksum_value,
    attributesJson: art.attributesJson,
    urls: art.urls.map((u) => ({
      url: u.url,
      priority: u.priority,
      source_kind: u.source_kind,
    })),
  }));

  createDraft.value = {
    version: "",
    channel: editableDraft.value.channel,
    version_code: editableDraft.value.version_code,
    file_created_at: editableDraft.value.file_created_at_override || "",
    is_visible: editableDraft.value.is_visible,
    checksum_etag: editableDraft.value.checksum_etag,
    checksum_crc64: editableDraft.value.checksum_crc64,
    checksum_md5: editableDraft.value.checksum_md5,
    artifacts: clonedArtifacts,
    artifactsJson: editableDraft.value.artifactsJson,
    artifactsMode: "visual",
  };
  contentSubTab.value = "create";
  success.value = `已成功复制版本 ${selectedVersion.value} 的配置模板！请输入新版本号。`;
}

function resetCreateDraft(): void {
  createDraft.value = defaultCreateDraft();
  success.value = "新版本录入表单已重置为空白模板。";
}

function fillCreateCurrentTime(): void {
  createDraft.value.file_created_at = new Date().toISOString();
}

function addCreateArtifactItem(): void {
  const nextPart = (createDraft.value.artifacts.length ? Math.max(...createDraft.value.artifacts.map((a) => a.part)) : 0) + 1;
  createDraft.value.artifacts.push({
    kind: "apk",
    name: "",
    part: nextPart,
    size: 0,
    checksum_type: "",
    checksum_value: "",
    attributesJson: "{}",
    urls: [{ url: "", priority: 0, source_kind: "official" }],
  });
  syncCreateArtifactsToJson();
}

function removeCreateArtifactItem(idx: number): void {
  if (createDraft.value.artifacts.length <= 1) {
    error.value = "新版本必须保留至少一个资源分卷 (Artifact)。";
    return;
  }
  createDraft.value.artifacts.splice(idx, 1);
  syncCreateArtifactsToJson();
}

function addCreateArtifactUrlItem(artIdx: number): void {
  const art = createDraft.value.artifacts[artIdx];
  if (!art) return;
  const nextPriority = art.urls.length;
  art.urls.push({ url: "", priority: nextPriority, source_kind: "official" });
  syncCreateArtifactsToJson();
}

function removeCreateArtifactUrlItem(artIdx: number, urlIdx: number): void {
  const art = createDraft.value.artifacts[artIdx];
  if (!art) return;
  art.urls.splice(urlIdx, 1);
  syncCreateArtifactsToJson();
}

function syncCreateArtifactsToJson(): void {
  const payload = buildCreateArtifactsPayload();
  createDraft.value.artifactsJson = JSON.stringify(payload, null, 2);
}

function formatCreateArtifactsJson(): void {
  try {
    const parsed = JSON.parse(createDraft.value.artifactsJson || "[]");
    createDraft.value.artifactsJson = JSON.stringify(parsed, null, 2);
  } catch (err) {
    error.value = err instanceof Error ? `JSON 格式错误: ${err.message}` : "JSON 格式无效";
  }
}

function switchCreateArtifactsMode(mode: "visual" | "json"): void {
  if (mode === "json") {
    syncCreateArtifactsToJson();
    createDraft.value.artifactsMode = "json";
  } else {
    try {
      const parsed = JSON.parse(createDraft.value.artifactsJson || "[]");
      if (!Array.isArray(parsed)) throw new Error("JSON 顶层必须是数组");
      createDraft.value.artifacts = parsed.map((art: any, idx: number) => ({
        kind: art.kind || "file",
        name: art.name || "",
        part: art.part ?? (idx + 1),
        size: art.size ?? 0,
        checksum_type: art.checksum_type || "",
        checksum_value: art.checksum_value || "",
        attributesJson: JSON.stringify(art.attributes || {}, null, 2),
        urls: (art.urls || []).map((u: any, uIdx: number) => ({
          url: u.url || "",
          priority: u.priority ?? uIdx,
          source_kind: u.source_kind || "official",
        })),
      }));
      createDraft.value.artifactsMode = "visual";
    } catch (err) {
      error.value = err instanceof Error ? `切换失败: ${err.message}` : "JSON 解析失败";
    }
  }
}

function handleCreateArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
  const extracted = extractFilenameFromUrl(newUrl);
  if (extracted && extracted.includes(".")) {
    const currentName = (art.name || "").trim();
    const isDefaultOrEmpty =
      !currentName ||
      /^package(\.part\d+)?\.(zip|bin|apk|dat)$/i.test(currentName) ||
      currentName === "未命名文件";

    if (isDefaultOrEmpty) {
      art.name = extracted;
    }
    if (extracted.toLowerCase().endsWith(".apk") && (art.kind === "file" || !art.kind)) {
      art.kind = "apk";
    }
  }
  syncCreateArtifactsToJson();
}

function forceExtractCreateArtifactName(art: EditableArtifactDraft): void {
  const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
  const extracted = extractFilenameFromUrl(firstUrl);
  if (extracted && extracted.includes(".")) {
    art.name = extracted;
    if (extracted.toLowerCase().endsWith(".apk") && (art.kind === "file" || !art.kind)) {
      art.kind = "apk";
    }
    syncCreateArtifactsToJson();
  }
}

function buildCreateArtifactsPayload(): ManualArtifactPayload[] {
  if (createDraft.value.artifactsMode === "json") {
    try {
      const parsed = JSON.parse(createDraft.value.artifactsJson || "[]");
      if (!Array.isArray(parsed)) throw new Error("Artifacts JSON 必须是数组");
      return parsed;
    } catch (err) {
      throw new Error(err instanceof Error ? `Artifacts JSON 格式错误: ${err.message}` : "Artifacts JSON 无效");
    }
  }
  return createDraft.value.artifacts.map((art) => {
    let artAttributes: Record<string, unknown> = {};
    if (art.attributesJson?.trim()) {
      try {
        const parsed = JSON.parse(art.attributesJson);
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
          artAttributes = parsed;
        }
      } catch {
        // ignore
      }
    }
    return {
      kind: art.kind,
      name: art.name.trim(),
      part: art.part,
      size: Number(art.size) || 0,
      checksum_type: art.checksum_type.trim() || undefined,
      checksum_value: art.checksum_value.trim().toLowerCase() || undefined,
      attributes: artAttributes,
      urls: art.urls
        .filter((u) => u.url.trim())
        .map((u) => ({
          url: u.url.trim(),
          priority: Number(u.priority) || 0,
          source_kind: u.source_kind.trim() || "official",
        })),
    };
  });
}

async function addVersion(): Promise<void> {
  const ver = createDraft.value.version.trim();
  if (!selectedDomainId.value || !ver) {
    error.value = "请输入新版本的版本号";
    return;
  }

  let artifactsPayload: ManualArtifactPayload[];
  try {
    artifactsPayload = buildCreateArtifactsPayload();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Artifacts 配置无效";
    return;
  }

  if (artifactsPayload.length !== 1) {
    error.value = "Android 架构只允许包含一个 APK 资源文件 (Artifact)";
    return;
  }
  const mainArt = artifactsPayload[0];
  if (mainArt.kind !== "apk") {
    error.value = "资源文件类型 (kind) 必须为 apk";
    return;
  }
  if (!mainArt.name.trim()) {
    error.value = "APK 文件名不能为空";
    return;
  }
  if (!mainArt.name.trim().toLowerCase().endsWith(".apk")) {
    error.value = "文件名必须以 .apk 结尾";
    return;
  }
  if (mainArt.urls.length !== 1) {
    error.value = "每个版本必须且仅允许包含一条下载链接 (URL)";
    return;
  }
  const firstUrl = mainArt.urls[0].url.trim();
  if (!firstUrl.startsWith("http://") && !firstUrl.startsWith("https://")) {
    error.value = "下载链接 URL 必须使用 http:// 或 https:// 协议";
    return;
  }

  // 注入校验值
  const artAttrs = (mainArt.attributes || {}) as Record<string, unknown>;
  if (createDraft.value.checksum_etag?.trim()) {
    artAttrs.etag = createDraft.value.checksum_etag.trim();
  }
  if (createDraft.value.checksum_crc64?.trim()) {
    artAttrs.crc64 = createDraft.value.checksum_crc64.trim();
  }
  if (createDraft.value.checksum_md5?.trim()) {
    artAttrs.md5 = createDraft.value.checksum_md5.trim();
  }
  mainArt.attributes = artAttrs;

  const attributes: Record<string, unknown> = {
    channel: createDraft.value.channel.trim() || "official",
    version_code:
      createDraft.value.version_code !== null &&
      createDraft.value.version_code !== undefined &&
      String(createDraft.value.version_code).trim() !== ""
        ? Number(createDraft.value.version_code)
        : null,
  };
  if (createDraft.value.file_created_at?.trim()) {
    attributes.file_created_at = createDraft.value.file_created_at.trim();
  }

  const confirmed = window.confirm(
    `确定要为【${selectedDomainGameName.value || selectedDomainId.value}】录入新版本【${ver}】吗？`,
  );
  if (!confirmed) return;

  await withLoading(async (signal) => {
    try {
      const result = await adminApi.addVersion(
        selectedDomainId.value,
        {
          version: ver,
          client_version: ver,
          file_path: mainArt.name.trim(),
          attributes,
          artifacts: [mainArt],
        },
        token.value,
        signal,
      );

      if (!createDraft.value.is_visible) {
        await adminApi.setVersionVisibility(
          selectedDomainId.value,
          ver,
          false,
          token.value,
          signal,
        );
      }

      const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = verRes.items;
      selectedVersion.value = ver;
      await loadEditableVersion(selectedDomainId.value, ver);
      contentSubTab.value = "edit";
      createDraft.value = defaultCreateDraft();

      const probeMsg = result.probe_error ? `（自动验活提示: ${result.probe_error}）` : "，并在后台自动验活成功！";
      success.value = `新版本 ${ver} 已成功录入发布${probeMsg}`;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        error.value = `版本【${ver}】已存在，请勿重复新增 (HTTP 409)。`;
        return;
      }
      throw err;
    }
  });
}

async function probeCurrentVersion(ver = selectedVersion.value): Promise<void> {
  if (!selectedDomainId.value || !ver) return;
  const confirmed = window.confirm(`确定要向官方源发起对版本【${ver}】的实时探活并持久化保存吗？`);
  if (!confirmed) return;

  await withLoading(async (signal) => {
    try {
      await adminApi.probeVersion(selectedDomainId.value, ver, token.value, signal);
      const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = verRes.items;
      await loadEditableVersion(selectedDomainId.value, ver);
      success.value = `版本【${ver}】已成功完成官方源探活并已持久化保存！`;
    } catch (err) {
      if (err instanceof ApiError && err.status === 502) {
        error.value = `探活失败 (HTTP 502)：网络探测异常，未能成功连接官方源。`;
        return;
      }
      throw err;
    }
  });
}

onBeforeUnmount(() => {
  document.removeEventListener("click", handleGlobalDropdownClick);
  controller?.abort();
  stopProbePolling();
  stopOperationPolling();
  stopRetentionStatusPolling();
  cancelRetentionStatusRequests();
  cancelRetentionRun();
  cancelRetentionSave();
});
</script>

<template>
  <div class="admin-app" :class="{ 'is-unauthenticated': !authenticated }">
    <!-- 主页面同款精致图标轨（Game Rail 风格, 88px, 仅登录后展示） -->
    <aside v-if="authenticated" class="admin-rail">
      <div class="rail-brand" title="Game Manifest Index 控制台">
        <div class="rail-logo-box">
          <span>GMI</span>
        </div>
      </div>

      <div v-if="authenticated" class="rail-nav-list">
        <!-- 1. 游戏入口 -->
        <button
          class="rail-item"
          :class="{ active: tab === 'games' }"
          type="button"
          title="游戏入口管理"
          @click="openGames"
        >
          <span class="rail-icon">🎮</span>
          <span class="rail-label">游戏</span>
        </button>

        <!-- 2. 数据模块 -->
        <button
          class="rail-item"
          :class="{ active: tab === 'domains' }"
          type="button"
          title="数据模块管理"
          @click="openDomains"
        >
          <span class="rail-icon">📦</span>
          <span class="rail-label">模块</span>
        </button>

        <!-- 3. 版本内容 -->
        <button
          class="rail-item"
          :class="{ active: tab === 'content' }"
          type="button"
          title="版本内容控制"
          @click="openContent()"
        >
          <span class="rail-icon">📑</span>
          <span class="rail-label">版本</span>
        </button>

        <!-- 4. 采集与探活 -->
        <button
          class="rail-item"
          :class="{ active: tab === 'probe' }"
          type="button"
          title="采集与探活监控"
          @click="openProbe"
        >
          <span class="rail-icon">⚡</span>
          <span class="rail-label">监控</span>
        </button>

        <!-- 5. 数据保留与自动清理 -->
        <button
          class="rail-item"
          :class="{ active: tab === 'retention' }"
          type="button"
          title="数据保留与自动清理"
          @click="openRetention"
        >
          <span class="rail-icon">🧹</span>
          <span class="rail-label">清理</span>
        </button>
      </div>

      <!-- 底部退出操作 -->
      <div class="rail-foot">
        <button
          v-if="authenticated"
          class="rail-action-btn"
          type="button"
          title="退出登录"
          @click="logout"
        >
          <span class="rail-icon">🚪</span>
          <span class="rail-label">退出</span>
        </button>
      </div>
    </aside>

    <!-- 主工作区 Main Dashboard -->
    <main class="admin-main">
      <!-- 登录视窗 Login Screen (未登录时仅显示居中登录面板及返回前台按钮) -->
      <div v-if="!authenticated" class="admin-login-layout">
        <div class="login-top-actions">
          <button class="admin-btn secondary small" type="button" @click="router.push('/')">
            <svg class="admin-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"></line>
              <polyline points="12 19 5 12 12 5"></polyline>
            </svg>
            <span>返回前台</span>
          </button>
        </div>
        <form class="admin-login-card" @submit.prevent="login">
          <div class="login-badge-wrap">
            <div class="login-brand-badge">GMI</div>
          </div>
          <div class="login-head">
            <h2>管理员身份验证</h2>
            <p>请输入统一归档管理 Token / 密码进入后台</p>
          </div>
          
          <div v-if="error" class="admin-alert error">{{ error }}</div>
          
          <div class="login-input-wrap">
            <label for="admin-token-input">管理凭证</label>
            <input
              id="admin-token-input"
              v-model="token"
              type="password"
              placeholder="输入管理 token..."
              autocomplete="current-password"
              required
              autofocus
            />
          </div>
          
          <button class="admin-btn primary large full-width" type="submit" :disabled="loading">
            <span>{{ loading ? '验证中…' : '进入管理系统' }}</span>
          </button>
        </form>
      </div>

      <!-- 已登录主工作区 -->
      <template v-else>
        <!-- 顶栏 TopBar (仅在登录后展示) -->
        <header class="admin-topbar">
          <div class="topbar-left">
            <div class="topbar-title-group">
              <h1>{{ currentTabMeta.title }}</h1>
              <p class="topbar-sub">{{ currentTabMeta.subtitle }}</p>
            </div>
          </div>
          <div class="admin-header-actions">
            <button class="admin-btn secondary small" type="button" :disabled="loading" @click="refreshAllData">
              <svg class="admin-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
              </svg>
              <span>刷新数据</span>
            </button>
            <button class="admin-btn secondary small" type="button" @click="router.push('/')">
              <svg class="admin-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="19" y1="12" x2="5" y2="12"></line>
                <polyline points="12 19 5 12 12 5"></polyline>
              </svg>
              <span>返回前台</span>
            </button>
          </div>
        </header>
        <!-- 全局通知 Toast / Alert -->
        <div v-if="error" class="admin-alert error">
          <span>{{ error }}</span>
          <button class="alert-close" type="button" @click="error = ''">✕</button>
        </div>
        <div v-if="success" class="admin-alert success">
          <span>{{ success }}</span>
          <button class="alert-close" type="button" @click="success = ''">✕</button>
        </div>

        <!-- 模块 1：游戏入口管理 (Games Master-Detail) -->
        <section v-if="tab === 'games'" class="admin-master-detail game-workspace">
          <!-- 左侧索引栏 -->
          <aside class="admin-list-pane game-list-pane">
            <div class="pane-header">
              <div class="pane-title">
                <span class="pane-kicker">GAMES</span>
                <strong>{{ filteredGames.length }} 个游戏入口</strong>
              </div>
              <button class="admin-btn primary small create-module-btn" type="button" @click="startGame">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>新增游戏</span>
              </button>
            </div>

            <div class="pane-search">
              <div class="search-input-wrapper">
                <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8"/>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input
                  v-model="gameSearchQuery"
                  class="admin-input search-styled"
                  placeholder="搜索游戏名称、ID 或副标题…"
                  type="search"
                />
              </div>
            </div>

            <div class="pane-scroll-list">
              <button
                v-for="item in filteredGames"
                :key="item.id"
                class="admin-list-item game-item"
                :class="{ active: item.id === selectedGameId && !newGame }"
                type="button"
                @click="selectGame(item.id)"
              >
                <div class="item-domain-icon-box">
                  <img
                    v-if="resolveGameIcon(item.id, item.icon_source)"
                    :class="{ 'endfield-icon': item.id === 'endfield' }"
                    :src="resolveGameIcon(item.id, item.icon_source)"
                    :alt="item.name"
                    @error="useFallbackIcon($event, item.id)"
                    class="domain-game-avatar"
                  />
                  <div v-else class="domain-fallback-icon">{{ item.id.slice(0, 1).toUpperCase() }}</div>
                  <span class="status-indicator" :class="{ off: !item.is_enabled }" :title="item.is_enabled ? '正常展示中' : '已隐藏停用'"></span>
                </div>
                <div class="item-info">
                  <div class="item-primary-row">
                    <strong class="item-name">{{ item.name }}</strong>
                    <span class="version-count-pill">{{ item.version_count }} 版本</span>
                  </div>
                  <div class="item-secondary-row">
                    <code class="item-id-tag">{{ item.id }}</code>
                    <span v-if="item.sub_name" class="item-sub-name">{{ item.sub_name }}</span>
                  </div>
                </div>
                <div class="item-slot-right">
                  <span class="item-sort-badge" title="显示排序权重">#{{ item.sort_order }}</span>
                </div>
              </button>
              <div v-if="!filteredGames.length" class="admin-empty-state">
                <div class="empty-icon">🎮</div>
                <span>未找到匹配的游戏入口</span>
                <button type="button" class="empty-action-link" @click="startGame">点击新建游戏</button>
              </div>
            </div>
          </aside>

          <!-- 右侧卡片化编辑器 -->
          <form class="admin-form-pane game-form-pane" @keydown.enter="preventEnterSubmit" @submit.prevent="saveGame">
            <!-- 头部 Hero 横幅 -->
            <div class="domain-hero-banner game-hero-banner">
              <div class="hero-identity">
                <div class="hero-icon-container">
                  <img
                    v-if="gameIconPreview"
                    :class="{ 'endfield-icon': gameDraft.id === 'endfield' }"
                    :src="gameIconPreview"
                    :alt="gameDraft.name"
                    @error="useFallbackIcon($event, gameDraft.id)"
                    class="hero-game-avatar"
                  />
                  <b v-else class="hero-fallback-letter">{{ gameDraft.id.slice(0, 1).toUpperCase() || '?' }}</b>
                </div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row">
                    <span class="kicker-tag">{{ newGame ? 'NEW GAME ENTRY' : 'GAME IDENTITY' }}</span>
                    <span class="hero-state-pill" :class="{ off: !gameDraft.is_enabled }">
                      <span class="state-dot"></span>
                      <span>{{ gameDraft.is_enabled ? '前台公开展示中' : '前台已停用隐藏' }}</span>
                    </span>
                    <span v-if="!newGame" class="hero-version-pill">
                      {{ currentGameDomainCount }} 个关联数据模块
                    </span>
                  </div>
                  <div class="hero-title-row">
                    <h2>{{ newGame ? '创建新游戏入口' : gameDraft.name }}</h2>
                    <span v-if="!newGame" class="hero-game-badge">
                      <code class="tag-code">{{ gameDraft.id }}</code> · {{ gameDraft.sub_name }}
                    </span>
                  </div>
                </div>
              </div>

              <div v-if="!newGame && gameDraft.id" class="hero-action-buttons">
                <button type="button" class="admin-btn secondary small hero-jump-btn" @click="openDomainsForGame(gameDraft.id)">
                  <span>管理关联数据模块 ({{ currentGameDomainCount }})</span>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </button>
              </div>
            </div>

            <!-- 上半部 2 列网格：1. 基本身份 (左) + 2. 图标与外观资源 (右) -->
            <div class="domain-cards-grid">
              <!-- 块 1: 基本身份标识 -->
              <div class="form-section-card domain-card block-identity">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🏷️</span>
                    <div>
                      <div class="section-card-title">1. 基本身份标识</div>
                      <p class="section-card-subtitle">设置游戏唯一主键代号、中英文显示名称与默认平台</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">IDENTITY</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- 游戏唯一 ID -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">游戏唯一 ID <b class="text-rose">*</b></span>
                      <button
                        v-if="!newGame && gameDraft.id"
                        type="button"
                        class="field-action-link"
                        @click="copyText(gameDraft.id)"
                      >
                        复制 ID
                      </button>
                    </div>
                    <div class="id-input-container">
                      <span class="id-prefix-icon">{{ newGame ? '✏️' : '🔒' }}</span>
                      <input
                        v-model="gameDraft.id"
                        class="admin-input text-mono id-input"
                        :disabled="!newGame"
                        required
                        placeholder="例如: hk4e、wuwa 或 arknights"
                      />
                    </div>
                    <small class="field-tip">
                      {{ newGame ? '全局唯一英文/数字小写代号，创建后不可更改' : '系统核心主键，用于资产目录索引与分发模块关联' }}
                    </small>
                  </div>

                  <!-- 默认展示平台 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">默认展示平台 <b class="text-rose">*</b></span>
                    </div>
                    <div class="platform-input-row">
                      <div class="platform-presets">
                        <button
                          v-for="p in ['PC', 'Android', 'iOS', 'Web']"
                          :key="p"
                          type="button"
                          class="preset-pill-btn"
                          :class="{ active: gameDraft.platform.toLowerCase() === p.toLowerCase() }"
                          @click="setGamePlatform(p)"
                        >
                          {{ p }}
                        </button>
                      </div>
                      <input
                        v-model="gameDraft.platform"
                        class="admin-input platform-input"
                        required
                        placeholder="PC / Android / iOS / Web"
                      />
                    </div>
                  </div>

                  <!-- 中文主名称 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">中文主名称 <b class="text-rose">*</b></span>
                    </div>
                    <input
                      v-model="gameDraft.name"
                      class="admin-input"
                      required
                      placeholder="例如: 原神、鸣潮、崩坏：星穹铁道"
                    />
                    <small class="field-tip">前台导航栏、概览卡片及页面标题呈现的核心品牌名称。</small>
                  </div>

                  <!-- 英文 / 副标题 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">英文 / 副标题 <b class="text-rose">*</b></span>
                    </div>
                    <input
                      v-model="gameDraft.sub_name"
                      class="admin-input"
                      required
                      placeholder="例如: Genshin Impact 或 Wuthering Waves"
                    />
                    <small class="field-tip">前台英文副标题显示，同时参与搜索匹配索引。</small>
                  </div>
                </div>
              </div>

              <!-- 块 2: 图标与外观资源 -->
              <div class="form-section-card domain-card block-assets">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🎨</span>
                    <div>
                      <div class="section-card-title">2. 图标与外观资源</div>
                      <p class="section-card-subtitle">配置导航与卡片图标解析源，支持内置资源与外部图片</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">ASSETS & ICON</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- 图标实时预览卡片 -->
                  <div class="admin-field full-width">
                    <div class="icon-live-preview-box">
                      <div class="preview-avatar-wrap">
                        <img
                          v-if="gameIconPreview"
                          :class="{ 'endfield-icon': gameDraft.id === 'endfield' }"
                          :src="gameIconPreview"
                          :alt="gameDraft.name"
                          @error="useFallbackIcon($event, gameDraft.id)"
                          class="preview-avatar-img"
                        />
                        <div v-else class="preview-fallback-letter">
                          {{ (gameDraft.name || gameDraft.id).slice(0, 1).toUpperCase() || '?' }}
                        </div>
                      </div>
                      <div class="preview-avatar-meta">
                        <div class="preview-meta-title">图标实时渲染解析</div>
                        <div class="preview-meta-desc">
                          解析结果：<code class="tag-code">{{ gameIconPreview || '默认首字母' }}</code>
                        </div>
                        <div class="icon-quick-presets">
                          <button
                            type="button"
                            class="preset-pill-btn micro"
                            :class="{ active: !gameDraft.icon_source }"
                            @click="setGameIconPreset('')"
                          >
                            默认内置图标 (留空)
                          </button>
                          <button
                            v-if="gameDraft.id"
                            type="button"
                            class="preset-pill-btn micro"
                            :class="{ active: gameDraft.icon_source === `builtin:${gameDraft.id}` }"
                            @click="setGameIconPreset(`builtin:${gameDraft.id}`)"
                          >
                            显式指定 builtin:{{ gameDraft.id }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 图标数据源 (Icon Source) 输入框 -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">图标数据源 (Icon Source)</span>
                      <span class="field-badge-tip">留空自动匹配内置同名图标</span>
                    </div>
                    <input
                      v-model="gameDraft.icon_source"
                      class="admin-input text-mono"
                      placeholder="例如: builtin:hk4e、/assets/icon.png 或 https://…"
                    />
                    <small class="field-tip">
                      支持 <code>builtin:&lt;id&gt;</code> 内置标识、站内绝对路径（如 <code>/assets/custom.png</code>）或外链 HTTPS 图片地址。
                    </small>
                  </div>
                </div>
              </div>
            </div>

            <!-- 下半部卡片：3. 展示与发布控制台 -->
            <div class="form-section-card domain-card block-publish">
              <div class="section-card-header">
                <div class="section-header-left">
                  <span class="section-icon">🚀</span>
                  <div>
                    <div class="section-card-title">3. 展示与发布控制台</div>
                    <p class="section-card-subtitle">设置前台顶部导航排序优先级、对外可见性与模块维护</p>
                  </div>
                </div>
                <div class="section-header-badge">
                  <span class="block-tag-pill">PUBLISH & OPERATIONS</span>
                </div>
              </div>

              <!-- 展示与发布 Bento 网格 -->
              <div class="publish-bento-grid">
                <!-- 1. 显示排序权重 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台显示排序 (sort_order)</span>
                    <span class="sort-tag-val">权重: <b>#{{ gameDraft.sort_order ?? 0 }}</b></span>
                  </div>
                  <div class="sort-stepper-container">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="(gameDraft.sort_order ?? 0) <= 0"
                        @click="adjustGameSort(-5)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                          v-model.number="gameDraft.sort_order"
                          class="stepper-input"
                          type="number"
                          min="0"
                          step="1"
                        />
                      </div>
                      <button
                        type="button"
                        class="stepper-btn inc"
                        @click="adjustGameSort(5)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                    </div>
                    <div class="sort-quick-presets">
                      <button
                        v-for="s in [0, 10, 20, 30]"
                        :key="s"
                        type="button"
                        class="preset-pill-btn micro"
                        :class="{ active: gameDraft.sort_order === s }"
                        @click="gameDraft.sort_order = s"
                      >
                        #{{ s }}{{ s === 0 ? ' (置顶)' : '' }}
                      </button>
                    </div>
                  </div>
                  <small class="field-tip">数字越小在前台导航栏与首页列表中展示越靠前。</small>
                </div>

                <!-- 2. 前台公开可见性 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台公开可见性</span>
                  </div>
                  <div class="visibility-toggle-card mini" :class="{ enabled: gameDraft.is_enabled }">
                    <div class="vis-info">
                      <span class="vis-icon">{{ gameDraft.is_enabled ? '🟢' : '⚪' }}</span>
                      <div>
                        <strong>{{ gameDraft.is_enabled ? '前台导航公开展示中' : '前台隐藏暂不对外展示' }}</strong>
                        <p>{{ gameDraft.is_enabled ? '普通访客可直接在导航和首页看到该游戏。' : '仅在管理控制台可见，对公众隐藏。' }}</p>
                      </div>
                    </div>
                    <label class="admin-toggle-label">
                      <input v-model="gameDraft.is_enabled" class="admin-toggle-checkbox" type="checkbox" />
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                </div>

                <!-- 3. 数据模块关联状态 -->
                <div class="publish-bento-cell version-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">关联数据分发模块</span>
                  </div>
                  <div class="version-portal-box">
                    <div class="version-stat-group">
                      <span class="version-stat-num">{{ currentGameDomainCount }}</span>
                      <span class="version-stat-unit">个分发模块</span>
                    </div>
                    <button
                      v-if="!newGame && gameDraft.id"
                      type="button"
                      class="admin-btn primary small version-portal-btn"
                      @click="openDomainsForGame(gameDraft.id)"
                    >
                      <span>进入模块管理</span>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </button>
                    <span v-else class="version-portal-hint">创建保存后可添加分发模块</span>
                  </div>
                </div>
              </div>

              <!-- 4. 保存 / 还原与危险删除操作栏 -->
              <div class="publish-actions-row">
                <div class="actions-left">
                  <button
                    v-if="!newGame && gameDraft.id"
                    type="button"
                    class="admin-btn danger outline"
                    :title="currentGameDomainCount > 0 ? '该游戏下存在数据模块，不可直接删除' : '彻底删除此空游戏入口'"
                    @click="removeGame"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    <span>删除空游戏</span>
                  </button>
                </div>

                <div class="actions-right">
                  <button
                    v-if="!newGame"
                    type="button"
                    class="admin-btn secondary"
                    :disabled="loading"
                    @click="revertGameDraft"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                      <path d="M3 3v5h5"/>
                    </svg>
                    <span>还原配置</span>
                  </button>

                  <button
                    class="admin-btn primary domain-save-btn"
                    type="submit"
                    :disabled="loading || !gameDraft.id"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                      <polyline points="17 21 17 13 7 13 7 21"/>
                      <polyline points="7 3 7 8 15 8"/>
                    </svg>
                    <span>{{ loading ? '保存中…' : (newGame ? '立即创建游戏入口' : '保存游戏设置') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section>

        <!-- 模块 2：数据模块管理 (Domains Master-Detail) -->
        <section v-else-if="tab === 'domains'" class="admin-master-detail domain-workspace">
          <!-- 左侧索引栏 -->
          <aside class="admin-list-pane domain-list-pane">
            <div class="pane-header">
              <div class="pane-title">
                <span class="pane-kicker">MODULES</span>
                <strong>{{ filteredDomains.length }} 个数据分发模块</strong>
              </div>
              <button class="admin-btn primary small create-module-btn" type="button" @click="startDomain">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>新增模块</span>
              </button>
            </div>

            <!-- 游戏级联选择器 -->
            <div class="pane-game-select">
              <div class="pane-select-header">
                <span class="select-label">筛选游戏范围</span>
                <span class="game-badge-chip">{{ domainGameFilter === 'all' ? '全部游戏' : (catalog.games.find(g => g.id === domainGameFilter)?.name || '全部') }}</span>
              </div>
              <CustomSelect
                :model-value="domainGameFilter"
                :options="domainGameOptions"
                size="small"
                @change="domainGameFilter = String($event)"
              />
            </div>

            <div class="pane-search">
              <div class="search-input-wrapper">
                <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8"/>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input
                  v-model="domainSearchQuery"
                  class="admin-input search-styled"
                  placeholder="搜索游戏、模块 ID 或类型…"
                  type="search"
                />
              </div>
            </div>

            <div class="pane-scroll-list">
              <button
                v-for="item in filteredDomains"
                :key="item.id"
                class="admin-list-item domain-item"
                :class="{ active: item.id === selectedDomainId && !newDomain }"
                type="button"
                @click="selectDomain(item.id)"
              >
                <!-- 真实游戏图标容器 (替代 emoji 占位) -->
                <div class="item-domain-icon-box">
                  <img
                    v-if="getDomainGame(item.game_id) && resolveGameIcon(item.game_id, getDomainGame(item.game_id)?.icon_source)"
                    :class="{ 'endfield-icon': item.game_id === 'endfield' }"
                    :src="resolveGameIcon(item.game_id, getDomainGame(item.game_id)?.icon_source)"
                    :alt="getDomainGame(item.game_id)?.name || item.id"
                    @error="useFallbackIcon($event, item.game_id)"
                    class="domain-game-avatar"
                  />
                  <div v-else class="domain-fallback-icon">
                    {{ (getDomainGame(item.game_id)?.name || item.id).slice(0, 1).toUpperCase() }}
                  </div>
                  <span class="status-indicator" :class="{ off: !item.is_enabled }" :title="item.is_enabled ? '正常展示中' : '已隐藏停用'"></span>
                </div>
                <div class="item-info">
                  <div class="item-primary-row">
                    <strong class="item-name">{{ getDomainGame(item.game_id)?.name || item.id }}</strong>
                    <span class="version-count-pill">{{ item.version_count }} 版本</span>
                  </div>
                  <div class="item-secondary-row">
                    <code class="item-id-tag">{{ item.id }}</code>
                    <span class="item-kind-pill" :class="item.kind">{{ item.kind }}</span>
                    <span class="item-adapter-pill">{{ item.adapter }}</span>
                  </div>
                </div>
                <div class="item-slot-right">
                  <span class="item-sort-badge" title="显示排序权重">#{{ item.sort_order }}</span>
                </div>
              </button>
              <div v-if="!filteredDomains.length" class="admin-empty-state">
                <div class="empty-icon">📂</div>
                <span>未找到匹配的数据模块</span>
                <button type="button" class="empty-action-link" @click="startDomain">点击新建模块</button>
              </div>
            </div>
          </aside>

          <!-- 右侧卡片化编辑器 -->
          <form class="admin-form-pane domain-form-pane" @keydown.enter="preventEnterSubmit" @submit.prevent="saveDomain">
            <!-- 头部 Hero 横幅 -->
            <div class="domain-hero-banner">
              <div class="hero-identity">
                <div class="hero-icon-container">
                  <img
                    v-if="domainDraft.game_id && resolveGameIcon(domainDraft.game_id, getDomainGame(domainDraft.game_id)?.icon_source)"
                    :class="{ 'endfield-icon': domainDraft.game_id === 'endfield' }"
                    :src="resolveGameIcon(domainDraft.game_id, getDomainGame(domainDraft.game_id)?.icon_source)"
                    :alt="currentDomainGameName"
                    class="hero-game-avatar"
                  />
                  <span v-else class="hero-kind-icon">{{ domainKindIcon(domainDraft.kind) }}</span>
                </div>
                <div class="hero-text-block">
                  <div class="hero-kicker-row">
                    <span class="kicker-tag">{{ newDomain ? 'NEW DISTRIBUTION MODULE' : 'DISTRIBUTION MODULE' }}</span>
                    <span class="hero-state-pill" :class="{ off: !domainDraft.is_enabled }">
                      <span class="state-dot"></span>
                      <span>{{ domainDraft.is_enabled ? '前台公开展示中' : '前台已隐藏停用' }}</span>
                    </span>
                  </div>
                  <div class="hero-title-row">
                    <h2>{{ newDomain ? '创建新数据模块' : domainDraft.id }}</h2>
                    <span v-if="!newDomain" class="hero-game-badge">
                      {{ currentDomainGameName }} · {{ domainDraft.platform }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 上半部 2 列网格：1. 基础身份 (左) + 2. 数据驱动与能力 (右) -->
            <div class="domain-cards-grid">
              <!-- 块 1: 基础身份 -->
              <div class="form-section-card domain-card block-identity">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">🏷️</span>
                    <div>
                      <div class="section-card-title">1. 基础身份</div>
                      <p class="section-card-subtitle">回答：这个模块是谁，归谁，属于什么类型</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">IDENTITY</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- 模块 ID -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">模块 ID <b class="text-rose">*</b></span>
                      <button
                        v-if="!newDomain && domainDraft.id"
                        type="button"
                        class="field-action-link"
                        @click="copyText(domainDraft.id)"
                      >
                        复制 ID
                      </button>
                    </div>
                    <div class="id-input-container">
                      <span class="id-prefix-icon">{{ newDomain ? '✏️' : '🔒' }}</span>
                      <input
                        v-model="domainDraft.id"
                        class="admin-input text-mono id-input"
                        :disabled="!newDomain"
                        required
                        placeholder="例如: hk4e-pc 或 wuwa-android"
                      />
                    </div>
                    <small class="field-tip">
                      {{ newDomain ? '推荐: 游戏代号-平台/形态，创建后不可变' : '系统唯一主键，用于数据隔离与目录索引' }}
                    </small>
                  </div>

                  <!-- 所属游戏 -->
                  <div class="admin-field">
                    <div class="field-label-row">
                      <span class="field-label">所属游戏 <b class="text-rose">*</b></span>
                    </div>
                    <CustomSelect
                      v-model="domainDraft.game_id"
                      :options="catalog.games.map((g) => ({ label: `${g.name} (${g.id})`, value: g.id }))"
                      :disabled="!newDomain"
                      placeholder="选择所属游戏"
                    />
                    <small class="field-tip">定义该模块关联的具体游戏产品与资产库。</small>
                  </div>

                  <!-- 模块主类型 (Kind) -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">模块主类型 (Kind) <b class="text-rose">*</b></span>
                      <span class="field-badge-tip">当前选定: <b>{{ domainDraft.kind }}</b></span>
                    </div>
                    <div class="kind-selector-row">
                      <button
                        v-for="k in [
                          { key: 'packages', label: '完整包 packages', icon: '📦' },
                          { key: 'apk', label: '官方安装包 apk', icon: '📱' },
                          { key: 'chunks', label: 'Chunk 块存储', icon: '🧩' },
                          { key: 'patches', label: '增量补丁 patches', icon: '🔄' },
                          { key: 'files', label: '散文件 files', icon: '📄' },
                          { key: 'resources', label: '热更资源 resources', icon: '🎨' },
                          { key: 'mixed', label: '混合分发 mixed', icon: '🔀' },
                        ]"
                        :key="k.key"
                        type="button"
                        class="kind-chip"
                        :class="{ active: domainDraft.kind === k.key }"
                        @click="setDomainKind(k.key)"
                      >
                        <span class="chip-icon">{{ k.icon }}</span>
                        <span class="chip-label">{{ k.label }}</span>
                      </button>
                    </div>
                  </div>

                  <!-- 平台 (Platform) -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">平台 (Platform) <b class="text-rose">*</b></span>
                    </div>
                    <div class="platform-input-row">
                      <div class="platform-presets">
                        <button
                          v-for="p in ['Windows', 'Android', 'iOS', 'Web / 全平台']"
                          :key="p"
                          type="button"
                          class="preset-pill-btn"
                          :class="{ active: domainDraft.platform.toLowerCase() === p.toLowerCase() || (p.includes('Android') && domainDraft.platform.toLowerCase() === 'android') }"
                          @click="setDomainPlatform(p.includes('Android') ? 'android' : (p.includes('Windows') ? 'Windows' : p))"
                        >
                          {{ p }}
                        </button>
                      </div>
                      <input
                        v-model="domainDraft.platform"
                        class="admin-input platform-input"
                        required
                        placeholder="Windows / Android / iOS / 全平台"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 块 2: 数据驱动与能力 -->
              <div class="form-section-card domain-card block-driver">
                <div class="section-card-header">
                  <div class="section-header-left">
                    <span class="section-icon">⚙️</span>
                    <div>
                      <div class="section-card-title">2. 数据驱动与能力</div>
                      <p class="section-card-subtitle">回答：这个模块靠什么适配，提供什么能力</p>
                    </div>
                  </div>
                  <div class="section-header-badge">
                    <span class="block-tag-pill">DRIVER & CAPABILITIES</span>
                  </div>
                </div>

                <div class="admin-field-grid">
                  <!-- Adapter 源 -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">Adapter 源 <b class="text-rose">*</b></span>
                      <span class="field-badge-tip">驱动引擎标识</span>
                    </div>
                    <div class="adapter-input-group">
                      <div class="adapter-presets">
                        <button
                          v-for="a in ['hoyo', 'wuwa', 'arknights', 'endfield', 'android', 'patchersdk', 'generic']"
                          :key="a"
                          type="button"
                          class="adapter-chip"
                          :class="{ active: domainDraft.adapter.toLowerCase() === a.toLowerCase() }"
                          @click="setDomainAdapter(a)"
                        >
                          {{ a }}
                        </button>
                      </div>
                      <input
                        v-model="domainDraft.adapter"
                        class="admin-input text-mono adapter-input"
                        required
                        placeholder="hoyo / wuwa / arknights / generic"
                      />
                    </div>
                    <small class="field-tip">选择驱动引擎解析下载清单结构与探活校验规则。</small>
                  </div>

                  <!-- 功能模式 Capabilities (交互式矩阵) -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">功能模式 Capabilities <b class="text-rose">*</b></span>
                      <span class="field-badge-tip">点击卡片切换能力模式</span>
                    </div>

                    <!-- 交互式能力标签矩阵 -->
                    <div class="capabilities-matrix">
                      <button
                        v-for="cap in domainCapabilityOptions"
                        :key="cap.key"
                        type="button"
                        class="capability-toggle-card"
                        :class="{ active: isDomainCapabilityActive(cap.key) }"
                        @click="toggleDomainCapability(cap.key)"
                      >
                        <div class="cap-card-top">
                          <span class="cap-icon">{{ cap.icon }}</span>
                          <span class="cap-key">{{ cap.key }}</span>
                          <span class="cap-check-dot"></span>
                        </div>
                        <span class="cap-desc">{{ cap.desc }}</span>
                      </button>
                    </div>
                  </div>

                  <!-- 底层标识字符串 -->
                  <div class="admin-field full-width">
                    <div class="field-label-row">
                      <span class="field-label">底层契约配置串 (Capabilities)</span>
                    </div>
                    <div class="raw-config-container">
                      <div class="raw-row-item">
                        <span class="raw-prefix-badge">capabilities</span>
                        <input
                          v-model="domainDraft.capabilities"
                          class="admin-input text-mono raw-cap-input"
                          placeholder="例如: apk, archive 或 packages, files"
                          required
                        />
                      </div>
                    </div>
                    <small class="field-tip">底层能力枚举标识串，用于 API 契约协议分发与解析。</small>
                  </div>
                </div>
              </div>
            </div>

            <!-- 下半部卡片：3. 展示与发布 -->
            <div class="form-section-card domain-card block-publish">
              <div class="section-card-header">
                <div class="section-header-left">
                  <span class="section-icon">🚀</span>
                  <div>
                    <div class="section-card-title">3. 展示与发布</div>
                    <p class="section-card-subtitle">回答：这个模块在前台怎么显示，是否启用，怎么发布</p>
                  </div>
                </div>
                <div class="section-header-badge">
                  <span class="block-tag-pill">PUBLISH & OPERATIONS</span>
                </div>
              </div>

              <!-- 展示与发布 Bento 网格 -->
              <div class="publish-bento-grid">
                <!-- 1. 显示排序与权重 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台显示排序 (sort_order)</span>
                    <span class="sort-tag-val">权重: <b>#{{ domainDraft.sort_order ?? 0 }}</b></span>
                  </div>
                  <div class="sort-stepper-container">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="(domainDraft.sort_order ?? 0) <= 0"
                        @click="adjustDomainSort(-5)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                          v-model.number="domainDraft.sort_order"
                          class="stepper-input"
                          type="number"
                          min="0"
                          step="1"
                        />
                      </div>
                      <button
                        type="button"
                        class="stepper-btn inc"
                        @click="adjustDomainSort(5)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                    </div>
                    <div class="sort-quick-presets">
                      <button
                        v-for="s in [0, 10, 20, 30]"
                        :key="s"
                        type="button"
                        class="preset-pill-btn micro"
                        :class="{ active: domainDraft.sort_order === s }"
                        @click="domainDraft.sort_order = s"
                      >
                        #{{ s }}{{ s === 0 ? ' (置顶)' : '' }}
                      </button>
                    </div>
                  </div>
                  <small class="field-tip">数字越小排序越靠前（前台导航标签展示顺序）。</small>
                </div>

                <!-- 2. 是否公开展示 -->
                <div class="publish-bento-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">前台公开展示状态</span>
                  </div>
                  <div class="visibility-toggle-card mini" :class="{ enabled: domainDraft.is_enabled }">
                    <div class="vis-info">
                      <span class="vis-icon">{{ domainDraft.is_enabled ? '🟢' : '⚪' }}</span>
                      <div>
                        <strong>{{ domainDraft.is_enabled ? '前台公开展示中' : '前台已隐藏停用' }}</strong>
                        <p>{{ domainDraft.is_enabled ? '在前台游戏页与导航栏中公开展示。' : '仅管理员可见，对普通访客隐藏。' }}</p>
                      </div>
                    </div>
                    <label class="admin-toggle-label">
                      <input v-model="domainDraft.is_enabled" class="admin-toggle-checkbox" type="checkbox" />
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                </div>

                <!-- 3. 入库版本数与版本管理入口 -->
                <div class="publish-bento-cell version-cell">
                  <div class="cell-label-row">
                    <span class="cell-label">版本内容库</span>
                  </div>
                  <div class="version-portal-box">
                    <div class="version-stat-group">
                      <span class="version-stat-num">{{ currentDomainObj?.version_count ?? 0 }}</span>
                      <span class="version-stat-unit">个已入库版本</span>
                    </div>
                    <button
                      v-if="!newDomain && domainDraft.id"
                      type="button"
                      class="admin-btn primary small version-portal-btn"
                      @click="openContent(domainDraft.id)"
                    >
                      <span>前往版本管理</span>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </button>
                    <span v-else class="version-portal-hint">创建保存后可录入版本</span>
                  </div>
                </div>
              </div>

              <!-- 4. 保存 / 还原与危险删除操作栏 -->
              <div class="publish-actions-row">
                <div class="actions-left">
                  <button
                    v-if="!newDomain && domainDraft.id"
                    type="button"
                    class="admin-btn danger outline"
                    :title="currentDomainObj && currentDomainObj.version_count > 0 ? '仅无版本的空模块可删除' : '彻底删除此空模块'"
                    @click="removeDomain"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    <span>删除空模块</span>
                  </button>
                </div>

                <div class="actions-right">
                  <button
                    v-if="!newDomain"
                    type="button"
                    class="admin-btn secondary"
                    :disabled="loading"
                    @click="revertDomainDraft"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                      <path d="M3 3v5h5"/>
                    </svg>
                    <span>还原配置</span>
                  </button>

                  <button
                    class="admin-btn primary domain-save-btn"
                    type="submit"
                    :disabled="loading || !domainDraft.id"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                      <polyline points="17 21 17 13 7 13 7 21"/>
                      <polyline points="7 3 7 8 15 8"/>
                    </svg>
                    <span>{{ loading ? '保存中…' : (newDomain ? '立即创建数据模块' : '保存模块配置') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section>

        <!-- 模块 3：版本内容管理 (Content Management) -->
        <section v-else-if="tab === 'content'" class="admin-content-grid">
          <!-- 顶部数据范围选择条 (宽敞舒适双列选择框) -->
          <div class="content-cascade-bar two-cols">
            <!-- 游戏选择器 -->
            <div class="cascade-item">
              <div class="custom-dropdown-container game-dropdown">
                <button
                  class="custom-dropdown-trigger"
                  :class="{ active: gameDropdownOpen }"
                  type="button"
                  @click="gameDropdownOpen = !gameDropdownOpen; domainDropdownOpen = false"
                >
                  <div class="trigger-content">
                    <img
                      v-if="selectedGame && resolveGameIcon(selectedGame.id, selectedGame.icon_source)"
                      :src="resolveGameIcon(selectedGame.id, selectedGame.icon_source)"
                      class="game-dropdown-icon"
                      :class="{ 'endfield-icon': selectedGame.id === 'endfield' }"
                      alt=""
                    />
                    <div v-else class="game-dropdown-icon fallback-icon">🎮</div>
                    <div class="trigger-texts">
                      <strong class="trigger-title">{{ selectedGame?.name || '选择游戏…' }}</strong>
                      <span v-if="selectedGame?.sub_name" class="trigger-subtitle">{{ selectedGame.sub_name }}</span>
                    </div>
                  </div>
                  <span class="dropdown-chevron" :class="{ open: gameDropdownOpen }">▼</span>
                </button>

                <!-- 游戏下拉浮层 -->
                <transition name="dropdown-fade">
                  <div v-if="gameDropdownOpen" class="custom-dropdown-menu">
                    <div class="dropdown-search-box" @click.stop>
                      <input
                        v-model="gameDropdownSearch"
                        class="dropdown-search-input"
                        placeholder="搜索游戏名称 / 代号…"
                        autofocus
                      />
                      <span v-if="gameDropdownSearch" class="clear-search-btn" @click="gameDropdownSearch = ''">✕</span>
                    </div>
                    <div class="dropdown-options-scroll">
                      <div v-if="filteredDropdownGames.length === 0" class="dropdown-empty-item">
                        无匹配游戏
                      </div>
                      <button
                        v-for="game in filteredDropdownGames"
                        :key="game.id"
                        class="dropdown-option-item"
                        :class="{ selected: game.id === selectedGameId }"
                        type="button"
                        @click="handleDropdownSelectGame(game.id)"
                      >
                        <img
                          v-if="resolveGameIcon(game.id, game.icon_source)"
                          :src="resolveGameIcon(game.id, game.icon_source)"
                          class="option-game-icon"
                          :class="{ 'endfield-icon': game.id === 'endfield' }"
                          alt=""
                        />
                        <div v-else class="option-game-icon fallback-icon">🎮</div>
                        <div class="option-info">
                          <strong class="option-name">{{ game.name }}</strong>
                          <span class="option-sub">{{ game.sub_name || game.id }}</span>
                        </div>
                        <span v-if="game.id === selectedGameId" class="selected-check">✔</span>
                      </button>
                    </div>
                  </div>
                </transition>
              </div>
            </div>

            <!-- 数据模块选择器 (宽敞下拉) -->
            <div class="cascade-item">
              <div class="custom-dropdown-container domain-dropdown">
                <button
                  class="custom-dropdown-trigger"
                  :class="{ active: domainDropdownOpen }"
                  type="button"
                  @click="domainDropdownOpen = !domainDropdownOpen; gameDropdownOpen = false"
                >
                  <div class="trigger-content">
                    <span
                      v-if="selectedDomain"
                      class="domain-kind-badge"
                      :class="selectedDomain.kind"
                    >
                      {{ selectedDomain.kind.toUpperCase() }}
                    </span>
                    <div class="trigger-texts">
                      <strong class="trigger-title">{{ getDomainFriendlyName(selectedDomain) }}</strong>
                      <span v-if="selectedDomain" class="trigger-subtitle">
                        {{ selectedDomain.id }}
                      </span>
                    </div>
                  </div>
                  <span class="dropdown-chevron" :class="{ open: domainDropdownOpen }">▼</span>
                </button>

                <!-- 模块下拉浮层 -->
                <transition name="dropdown-fade">
                  <div v-if="domainDropdownOpen" class="custom-dropdown-menu">
                    <div class="dropdown-options-scroll">
                      <div v-if="gameDomains.length === 0" class="dropdown-empty-item">
                        该游戏下暂无数据模块
                      </div>
                      <button
                        v-for="d in gameDomains"
                        :key="d.id"
                        class="dropdown-option-item domain-option"
                        :class="{ selected: d.id === selectedDomainId }"
                        type="button"
                        @click="handleDropdownSelectDomain(d.id)"
                      >
                        <span class="domain-kind-badge" :class="d.kind">{{ d.kind.toUpperCase() }}</span>
                        <div class="option-info">
                          <strong class="option-name">{{ getDomainFriendlyName(d) }}</strong>
                          <span class="option-sub">{{ d.id }} · {{ d.platform }}</span>
                        </div>
                        <span v-if="d.id === selectedDomainId" class="selected-check">✔</span>
                      </button>
                    </div>
                  </div>
                </transition>
              </div>
            </div>
          </div>

          <!-- 顶部全局归档健康条 (可交互一键筛选) -->
          <div class="archive-health-overview-bar">
            <div class="overview-title-group">
              <strong class="overview-game-name">{{ selectedDomainGameName }}</strong>
              <span class="overview-slash">/</span>
              <span class="overview-domain-name">{{ getDomainFriendlyName(selectedDomain) }}</span>
            </div>

            <div class="overview-metrics-group">
              <span class="metric-item">{{ archiveHealthStats.total }} 个版本</span>
              <span class="metric-divider">·</span>
              <span class="metric-item">最新 {{ archiveHealthStats.latest }}</span>
              <span class="metric-divider">·</span>
              <span class="metric-item">{{ archiveHealthStats.available }} 个可用</span>

              <!-- 链接失效状态药丸（可交互筛选） -->
              <button
                v-if="archiveHealthStats.unavailable > 0"
                class="filter-pill-btn danger"
                :class="{ active: versionFilterState === 'unavailable' }"
                type="button"
                :title="versionFilterState === 'unavailable' ? '点击取消筛选' : '点击筛选链接失效版本'"
                @click="toggleVersionFilter('unavailable')"
              >
                ● 链接失效 {{ archiveHealthStats.unavailable }}
              </button>

              <!-- 尚未探活状态药丸（可交互筛选） -->
              <button
                v-if="archiveHealthStats.unknown > 0"
                class="filter-pill-btn warning"
                :class="{ active: versionFilterState === 'unknown' }"
                type="button"
                :title="versionFilterState === 'unknown' ? '点击取消筛选' : '点击筛选尚未探活版本'"
                @click="toggleVersionFilter('unknown')"
              >
                ○ 尚未探活 {{ archiveHealthStats.unknown }}
              </button>

              <!-- 重置筛选提示 -->
              <button
                v-if="versionFilterState !== 'all'"
                class="filter-pill-btn reset"
                type="button"
                title="清除状态筛选并恢复最新可用版本"
                @click="resetVersionFilter"
              >
                ✕ 清除筛选
              </button>
            </div>
          </div>

          <!-- 下方 Master-Detail 双栏布局 -->
          <div class="content-panels-layout">
            <!-- 左侧：精简版 Master 垂直版本列表 -->
            <div class="content-version-master-pane">
              <div class="pane-header">
                <div class="pane-title">
                  <span>VERSION LIST</span>
                  <strong>版本列表 ({{ filteredVersions.length }})</strong>
                </div>
              </div>

              <!-- 快速检索输入框 -->
              <div class="pane-search">
                <input
                  v-model="versionSearchQuery"
                  class="admin-input small"
                  placeholder="搜索版本号…"
                />
              </div>

              <!-- 独立滚动的版本项列表（分层智能折叠） -->
              <div class="version-master-scroll-list">
                <div v-if="groupedVersionList.length === 0" class="admin-empty-state">
                  未找到匹配的版本
                </div>

                <!-- 大版本分组 (Major Group) -->
                <div
                  v-for="majorGroup in groupedVersionList"
                  :key="majorGroup.majorKey"
                  class="version-major-group"
                >
                  <!-- 大版本折叠标题栏 -->
                  <button
                    class="major-group-header"
                    :class="{ expanded: expandedMajorKeys.has(majorGroup.majorKey) }"
                    type="button"
                    @click="toggleMajorGroup(majorGroup.majorKey)"
                  >
                    <div class="major-title-left">
                      <span class="group-chevron" :class="{ open: expandedMajorKeys.has(majorGroup.majorKey) }">▶</span>
                      <strong class="major-key-text">{{ majorGroup.majorKey }}</strong>
                    </div>
                    <div class="major-meta-right">
                      <span class="major-count-text">
                        {{ majorGroup.totalCount }} 个版本
                        <template v-if="majorGroup.unavailableCount > 0">
                          <span class="meta-dot">·</span>
                          <span class="text-danger-highlight">{{ majorGroup.unavailableCount }} 个失效</span>
                        </template>
                      </span>
                    </div>
                  </button>

                  <!-- 大版本展开容器 -->
                  <div
                    v-if="expandedMajorKeys.has(majorGroup.majorKey)"
                    class="major-group-body"
                  >
                    <template v-for="entry in majorGroup.entries" :key="entry.type === 'single' ? (entry.item?.version || '') : (entry.group?.minorKey || '')">
                      <!-- 情况 A：单版本直接平铺 (避免无意义多层折叠) -->
                      <button
                        v-if="entry.type === 'single' && entry.item"
                        class="version-master-item"
                        :class="{ active: entry.item.version === selectedVersion }"
                        type="button"
                        @click="onContentVersionSelect(entry.item.version)"
                      >
                        <div class="version-item-top">
                          <div class="version-item-title-row">
                            <span
                              class="version-status-dot"
                              :class="isVersionAvailable(entry.item) ? 'available' : 'unavailable'"
                              :title="isVersionAvailable(entry.item) ? '链接可用' : '链接不可用'"
                            ></span>
                            <strong class="version-item-title">{{ entry.item.version }}</strong>
                          </div>
                          <span v-if="!entry.item.is_visible" class="status-pill hidden">已隐藏</span>
                          <span v-else-if="!isVersionAvailable(entry.item)" class="status-pill danger">链接不可用</span>
                          <span v-else class="version-time-muted">{{ formatSyncTime(entry.item.source_released_at || entry.item.observed_at) || '未记录时间' }}</span>
                        </div>
                      </button>

                      <!-- 情况 B：存在多个补丁版本的二级小版本折叠组 -->
                      <div
                        v-else-if="entry.type === 'minorGroup' && entry.group"
                        class="version-minor-group"
                      >
                        <button
                          class="minor-group-header"
                          :class="{ expanded: expandedMinorKeys.has(entry.group.minorKey) }"
                          type="button"
                          @click="toggleMinorGroup(entry.group.minorKey)"
                        >
                          <div class="minor-title-left">
                            <span class="group-chevron small" :class="{ open: expandedMinorKeys.has(entry.group.minorKey) }">▶</span>
                            <strong class="minor-key-text">{{ entry.group.minorKey }}</strong>
                          </div>
                          <span class="minor-count">{{ entry.group.items.length }} 个补丁</span>
                        </button>

                        <div
                          v-if="expandedMinorKeys.has(entry.group.minorKey)"
                          class="minor-group-body"
                        >
                          <button
                            v-for="subItem in entry.group.items"
                            :key="subItem.version"
                            class="version-master-item sub-item"
                            :class="{ active: subItem.version === selectedVersion }"
                            type="button"
                            @click="onContentVersionSelect(subItem.version)"
                          >
                            <div class="version-item-top">
                              <div class="version-item-title-row">
                                <span
                                  class="version-status-dot"
                                  :class="isVersionAvailable(subItem) ? 'available' : 'unavailable'"
                                  :title="isVersionAvailable(subItem) ? '链接可用' : '链接不可用'"
                                ></span>
                                <strong class="version-item-title">{{ subItem.version }}</strong>
                              </div>
                              <span v-if="!subItem.is_visible" class="status-pill hidden">已隐藏</span>
                              <span v-else-if="!isVersionAvailable(subItem)" class="status-pill danger">链接不可用</span>
                              <span v-else class="version-time-muted">{{ formatSyncTime(subItem.source_released_at || subItem.observed_at) || '未记录时间' }}</span>
                            </div>
                          </button>
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右侧：版本工作台（编辑版本 / 新建版本） -->
            <div class="content-work-card">
              <!-- 子功能切换 Tab -->
              <div class="content-sub-tabs">
                <button
                  class="sub-tab-btn"
                  :class="{ active: contentSubTab === 'edit' }"
                  type="button"
                  @click="contentSubTab = 'edit'"
                >
                  <span>🛠️ 编辑版本</span>
                </button>
                <button
                  class="sub-tab-btn"
                  :class="{ active: contentSubTab === 'create' }"
                  type="button"
                  @click="contentSubTab = 'create'"
                >
                  <span>➕ 新建版本</span>
                </button>
              </div>

              <!-- 表单 A：编辑版本 -->
              <form v-if="contentSubTab === 'edit'" class="version-edit-form" @keydown.enter="preventEnterSubmit" @submit.prevent="saveEditableVersion">
                <!-- 顶部版本状态栏 -->
                <div class="version-status-topbar">
                  <div class="version-header-meta">
                    <div class="version-title-row">
                      <h2>{{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }} <span class="divider">/</span> {{ selectedVersion || '未选择版本' }}</h2>
                      <span v-if="!editableDraft.is_visible" class="status-pill hidden">已隐藏</span>
                    </div>
                  </div>

                  <!-- 右侧操作区：探活并保存 + 更多菜单 -->
                  <div class="version-header-actions">
                    <button
                      type="button"
                      class="admin-btn secondary"
                      :disabled="editableLoading || loading || !selectedVersion"
                      title="探活官方链接并持久化更新到 version.json"
                      @click="probeCurrentVersion()"
                    >
                      <span>⚡ 探活并保存</span>
                    </button>

                    <!-- 更多操作下拉菜单 -->
                    <div class="custom-dropdown-container more-actions-dropdown">
                      <button
                        type="button"
                        class="admin-btn secondary"
                        title="更多操作"
                        @click.stop="moreActionsOpen = !moreActionsOpen"
                      >
                        <span>更多 ▾</span>
                      </button>
                      <transition name="dropdown-fade">
                        <div v-if="moreActionsOpen" class="more-dropdown-menu" @click.stop>
                          <button
                            type="button"
                            class="more-dropdown-item"
                            @click="toggleVersionVisibility(); moreActionsOpen = false"
                          >
                            <span>{{ editableDraft.is_visible ? '👁️ 隐藏此版本' : '👁️ 恢复公开' }}</span>
                          </button>
                          <button
                            type="button"
                            class="more-dropdown-item"
                            @click="copyCurrentVersionToCreateDraft(); moreActionsOpen = false"
                          >
                            <span>📋 复制为新版本模板</span>
                          </button>
                          <hr class="more-divider" />
                          <button
                            type="button"
                            class="more-dropdown-item danger"
                            @click="deleteCurrentVersion(); moreActionsOpen = false"
                          >
                            <span>🗑️ 删除此版本</span>
                          </button>
                        </div>
                      </transition>
                    </div>
                  </div>
                </div>

                <div v-if="!selectedVersion" class="admin-empty-state">
                  请先在左侧列表中选择一个目标版本。
                </div>

                <template v-else>
                  <!-- 链接健康条 (Health Banner - 紧凑低饱和) -->
                  <div
                    class="health-banner-card"
                    :class="currentVersionHealth.isOk ? 'success' : (currentVersionHealth.isChecked ? 'danger' : 'neutral')"
                  >
                    <div class="banner-left">
                      <span class="banner-dot">●</span>
                      <strong class="banner-status">
                        {{ currentVersionHealth.isOk ? '链接可用' : (currentVersionHealth.isChecked ? '链接不可用' : '待探活') }}
                      </strong>
                      <span v-if="currentVersionHealth.httpCode" class="banner-badge">HTTP {{ currentVersionHealth.httpCode }}</span>
                      <span v-if="currentVersionHealth.size" class="banner-badge">{{ formatBytes(currentVersionHealth.size) }}</span>
                      <span v-if="currentVersionHealth.lastCheckedAt" class="banner-time">
                        最后检查：{{ formatSyncTime(currentVersionHealth.lastCheckedAt) }}
                      </span>
                    </div>
                    <div class="banner-right">
                      <button
                        v-if="!currentVersionHealth.isOk && currentVersionHealth.isChecked"
                        class="banner-action-btn"
                        type="button"
                        @click="probeCurrentVersion()"
                      >
                        ⚡ 重新探活
                      </button>
                    </div>
                  </div>

                  <!-- 基本信息 -->
                  <div class="form-section-card">
                    <div class="section-card-title">基本信息</div>
                    <div class="admin-field-grid compact-3col">
                      <label class="admin-field">
                        <span class="field-label">渠道 <small class="field-sublabel">channel</small></span>
                        <input
                          v-model="editableDraft.channel"
                          class="admin-input"
                          placeholder="official / bilibili"
                          required
                        />
                      </label>

                      <label class="admin-field">
                        <span class="field-label">版本代码 <small class="field-sublabel">version_code</small></span>
                        <input
                          v-model.number="editableDraft.version_code"
                          class="admin-input"
                          type="number"
                          placeholder="例如: 12345"
                        />
                      </label>

                      <div class="admin-field">
                        <div class="field-header-row">
                          <span class="field-label">
                            文件时间 <small class="field-sublabel">file_time</small>
                          </span>
                          <button
                            v-if="editableDraft.file_created_at_override"
                            class="field-mini-btn"
                            type="button"
                            title="清空后将由后端自动识别 URL 或 Last-Modified 时间"
                            @click="clearFileTime"
                          >
                            🔄 清空 (恢复自动识别)
                          </button>
                        </div>
                        <input
                          v-model="editableDraft.file_created_at_override"
                          class="admin-input"
                          placeholder="例如: 2026-08-03T07:53:01Z"
                        />
                        <small class="field-tip">
                          来源：<strong>{{ getFileTimeSourceDescription(editableDraft.file_created_at_override, editableDraft.artifacts[0]?.urls[0]?.url) }}</strong>
                        </small>
                      </div>
                    </div>
                  </div>

                  <!-- APK 文件平铺卡片 -->
                  <div v-if="editableDraft.artifacts[0]" class="form-section-card apk-file-card">
                    <div class="section-card-title">APK 文件</div>

                    <div class="admin-field-grid">
                      <div class="admin-field">
                        <div class="field-header-row">
                          <span class="field-label">文件名</span>
                          <button
                            v-if="editableDraft.artifacts[0].urls[0]?.url"
                            class="field-mini-btn"
                            type="button"
                            title="根据当前 URL 自动解析并填入文件名"
                            @click="forceExtractArtifactName(editableDraft.artifacts[0])"
                          >
                            🎯 根据 URL 填写文件名
                          </button>
                        </div>
                        <input
                          v-model="editableDraft.artifacts[0].name"
                          class="admin-input"
                          placeholder="例如: yuanshen_7.0.0.apk"
                          required
                          @input="syncArtifactsToJson"
                        />
                      </div>

                      <label class="admin-field">
                        <span class="field-label">文件大小</span>
                        <input
                          v-model.number="editableDraft.artifacts[0].size"
                          class="admin-input"
                          type="number"
                          min="0"
                          placeholder="字节数"
                          @input="syncArtifactsToJson"
                        />
                        <small class="field-tip">
                          当前换算：<strong>{{ formatBytes(editableDraft.artifacts[0].size) }}</strong>
                        </small>
                      </label>
                    </div>

                    <!-- URL 独占一行 -->
                    <div class="admin-field full-width url-line-field">
                      <span class="field-label">下载 URL</span>
                      <div class="url-input-action-row">
                        <input
                          v-model="editableDraft.artifacts[0].urls[0].url"
                          class="admin-input text-mono url-long-input"
                          placeholder="https://..."
                          required
                          @input="handleArtifactUrlChange(editableDraft.artifacts[0], editableDraft.artifacts[0].urls[0].url)"
                        />
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="复制下载链接"
                          @click="copyUrl(editableDraft.artifacts[0].urls[0].url)"
                        >
                          📋 复制
                        </button>
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="在新窗口打开"
                          @click="openUrl(editableDraft.artifacts[0].urls[0].url)"
                        >
                          ↗ 打开
                        </button>
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="仅检查网络连通性，不修改或保存任何数据"
                          :disabled="urlProbeMap[editableDraft.artifacts[0].urls[0].url]?.loading"
                          @click="probeUrlItem(editableDraft.artifacts[0].urls[0].url)"
                        >
                          {{ urlProbeMap[editableDraft.artifacts[0].urls[0].url]?.loading ? '⏳ 测试中' : '🔍 测试 URL' }}
                        </button>
                      </div>
                    </div>

                    <!-- 校验值折叠面板 -->
                    <div class="checksums-collapse-section">
                      <button
                        class="collapse-toggle-btn"
                        type="button"
                        @click="checksumsOpen = !checksumsOpen"
                      >
                        <span class="chevron" :class="{ open: checksumsOpen }">▶</span>
                        <span class="collapse-title">文件校验值</span>
                        <span v-if="getChecksumSummaryText(editableDraft.checksum_etag, editableDraft.checksum_crc64, editableDraft.checksum_md5)" class="checksum-tag">
                          {{ getChecksumSummaryText(editableDraft.checksum_etag, editableDraft.checksum_crc64, editableDraft.checksum_md5) }}
                        </span>
                        <span v-else class="checksum-tag-empty">未配置</span>
                      </button>

                      <div v-if="checksumsOpen" class="collapse-fields-grid">
                        <label class="admin-field">
                          <span class="field-label">ETag</span>
                          <input
                            v-model="editableDraft.checksum_etag"
                            class="admin-input text-mono"
                            placeholder="例如: &quot;abcd1234...&quot;"
                          />
                        </label>
                        <label class="admin-field">
                          <span class="field-label">CRC64</span>
                          <input
                            v-model="editableDraft.checksum_crc64"
                            class="admin-input text-mono"
                            placeholder="例如: 15852710230531907"
                          />
                        </label>
                        <label class="admin-field">
                          <span class="field-label">MD5</span>
                          <input
                            v-model="editableDraft.checksum_md5"
                            class="admin-input text-mono"
                            placeholder="32位 MD5 字符串"
                          />
                        </label>
                      </div>
                    </div>
                  </div>

                  <!-- 底部吸附保存交互条（唯一保存入口） -->
                  <div class="sticky-save-bar" :class="{ dirty: isEditableDirty }">
                    <div class="bar-left">
                      <span v-if="isEditableDirty" class="save-status-badge dirty">⚠️ 有 {{ dirtyChangesCount }} 项未保存修改</span>
                      <span v-else class="save-status-badge clean">● 没有未保存修改</span>
                    </div>
                    <div class="bar-right">
                      <button
                        v-if="isEditableDirty"
                        class="admin-btn secondary small"
                        type="button"
                        @click="discardChanges"
                      >
                        放弃修改
                      </button>
                      <button
                        class="admin-btn primary small"
                        type="submit"
                        :disabled="loading || !selectedVersion || !isEditableDirty"
                      >
                        <span>{{ isUrlChanged ? '💾 保存并探活' : '💾 保存更改' }}</span>
                      </button>
                    </div>
                  </div>
                </template>
              </form>

              <!-- 表单 B：新建版本 (极简录入工作台) -->
              <form v-else class="version-create-form" @keydown.enter="preventEnterSubmit" @submit.prevent="addVersion">
                <!-- 顶部新建版本标题栏 -->
                <div class="version-status-topbar">
                  <div class="version-header-meta">
                    <div class="version-title-row">
                      <h2>新建版本 · {{ selectedDomainGameName }} {{ selectedDomainPlatform }}</h2>
                      <span class="status-pill success">新建模式</span>
                    </div>
                  </div>

                  <div class="version-header-actions">
                    <button
                      v-if="selectedVersion && editableLoaded"
                      class="admin-btn secondary"
                      type="button"
                      @click="copyCurrentVersionToCreateDraft"
                    >
                      <span>📋 复制当前 ({{ selectedVersion }}) 为模板</span>
                    </button>
                    <button
                      class="admin-btn secondary"
                      type="button"
                      @click="resetCreateDraft"
                    >
                      <span>🔄 重置</span>
                    </button>
                  </div>
                </div>

                <!-- 基本信息 -->
                <div class="form-section-card">
                  <div class="section-card-title">基本信息</div>
                  <div class="admin-field-grid compact-4col">
                    <label class="admin-field">
                      <span class="field-label">版本号 <small class="field-sublabel">version</small> <b class="text-rose">*</b></span>
                      <input
                        v-model="createDraft.version"
                        class="admin-input"
                        placeholder="例如: 7.1.0"
                        required
                      />
                    </label>

                    <label class="admin-field">
                      <span class="field-label">渠道 <small class="field-sublabel">channel</small></span>
                      <input
                        v-model="createDraft.channel"
                        class="admin-input"
                        placeholder="official"
                        required
                      />
                    </label>

                    <label class="admin-field">
                      <span class="field-label">版本代码 <small class="field-sublabel">version_code</small></span>
                      <input
                        v-model.number="createDraft.version_code"
                        class="admin-input"
                        type="number"
                        placeholder="例如: 12345 (可留空)"
                      />
                    </label>

                    <div class="admin-field">
                      <div class="field-header-row">
                        <span class="field-label">
                          文件时间 <small class="field-sublabel">file_time</small>
                        </span>
                        <button
                          v-if="createDraft.file_created_at"
                          class="field-mini-btn"
                          type="button"
                          @click="clearCreateFileTime"
                        >
                          🔄 清空
                        </button>
                      </div>
                      <input
                        v-model="createDraft.file_created_at"
                        class="admin-input"
                        placeholder="例如: 2026-08-03T07:53:01Z"
                      />
                      <small class="field-tip">
                        来源：<strong>{{ getFileTimeSourceDescription(createDraft.file_created_at, createDraft.artifacts[0]?.urls[0]?.url) }}</strong>
                      </small>
                    </div>
                  </div>
                </div>

                <!-- APK 文件平铺卡片 -->
                <div v-if="createDraft.artifacts[0]" class="form-section-card apk-file-card">
                  <div class="section-card-title">APK 文件</div>

                  <div class="admin-field-grid">
                    <div class="admin-field">
                      <div class="field-header-row">
                        <span class="field-label">文件名 <b class="text-rose">*</b></span>
                        <button
                          v-if="createDraft.artifacts[0].urls[0]?.url"
                          class="field-mini-btn"
                          type="button"
                          title="根据当前 URL 自动解析并填入文件名"
                          @click="forceExtractCreateArtifactName(createDraft.artifacts[0])"
                        >
                          🎯 根据 URL 填写文件名
                        </button>
                      </div>
                      <input
                        v-model="createDraft.artifacts[0].name"
                        class="admin-input"
                        placeholder="例如: yuanshen_7.1.0.apk"
                        required
                        @input="syncCreateArtifactsToJson"
                      />
                    </div>

                    <label class="admin-field">
                      <span class="field-label">文件大小</span>
                      <input
                        v-model.number="createDraft.artifacts[0].size"
                        class="admin-input"
                        type="number"
                        min="0"
                        placeholder="字节数"
                        @input="syncCreateArtifactsToJson"
                      />
                      <small class="field-tip">
                        当前换算：<strong>{{ formatBytes(createDraft.artifacts[0].size) }}</strong>
                      </small>
                    </label>
                  </div>

                  <!-- URL 独占一行 -->
                  <div class="admin-field full-width url-line-field">
                    <span class="field-label">下载 URL <b class="text-rose">*</b></span>
                    <div class="url-input-action-row">
                      <input
                        v-model="createDraft.artifacts[0].urls[0].url"
                        class="admin-input text-mono url-long-input"
                        placeholder="https://..."
                        required
                        @input="handleCreateArtifactUrlChange(createDraft.artifacts[0], createDraft.artifacts[0].urls[0].url)"
                      />
                      <button
                        class="url-action-pill-btn"
                        type="button"
                        title="复制下载链接"
                        @click="copyUrl(createDraft.artifacts[0].urls[0].url)"
                      >
                        📋 复制
                      </button>
                      <button
                        class="url-action-pill-btn"
                        type="button"
                        title="在新窗口打开"
                        @click="openUrl(createDraft.artifacts[0].urls[0].url)"
                      >
                        ↗ 打开
                      </button>
                      <button
                        class="url-action-pill-btn"
                        type="button"
                        :disabled="urlProbeMap[createDraft.artifacts[0].urls[0].url]?.loading"
                        @click="probeUrlItem(createDraft.artifacts[0].urls[0].url)"
                      >
                        {{ urlProbeMap[createDraft.artifacts[0].urls[0].url]?.loading ? '⏳ 验活中' : '🔍 快速验活' }}
                      </button>
                    </div>
                  </div>

                  <!-- 校验值折叠面板 -->
                  <div class="checksums-collapse-section">
                    <button
                      class="collapse-toggle-btn"
                      type="button"
                      @click="createChecksumsOpen = !createChecksumsOpen"
                    >
                      <span class="chevron" :class="{ open: createChecksumsOpen }">▶</span>
                      <span class="collapse-title">文件校验值 (ETag / CRC64 / MD5)</span>
                      <span v-if="createDraft.checksum_md5 || createDraft.checksum_crc64 || createDraft.checksum_etag" class="checksum-tag">已配置</span>
                    </button>

                    <div v-if="createChecksumsOpen" class="collapse-fields-grid">
                      <label class="admin-field">
                        <span class="field-label">ETag</span>
                        <input
                          v-model="createDraft.checksum_etag"
                          class="admin-input text-mono"
                          placeholder="例如: &quot;abcd1234...&quot;"
                        />
                      </label>
                      <label class="admin-field">
                        <span class="field-label">CRC64</span>
                        <input
                          v-model="createDraft.checksum_crc64"
                          class="admin-input text-mono"
                          placeholder="例如: 15852710230531907"
                        />
                      </label>
                      <label class="admin-field">
                        <span class="field-label">MD5</span>
                        <input
                          v-model="createDraft.checksum_md5"
                          class="admin-input text-mono"
                          placeholder="32位 MD5 字符串"
                        />
                      </label>
                    </div>
                  </div>
                </div>

                <!-- 底部提交操作条 -->
                <div class="form-actions-bar">
                  <div class="actions-left">
                    <button
                      type="button"
                      class="admin-btn secondary"
                      @click="resetCreateDraft"
                    >
                      <span>🔄 重置表单</span>
                    </button>
                  </div>

                  <div class="actions-right">
                    <button
                      class="admin-btn primary"
                      type="submit"
                      :disabled="loading || !selectedDomainId || !createDraft.version.trim()"
                    >
                      <span>{{ loading ? '录入中…' : '＋ 保存并录入新版本' }}</span>
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>
        </section>

        <!-- 模块 4：采集与探活监控中心 (Operations & Probe Console) -->
        <section v-else-if="tab === 'probe'" class="admin-probe-dashboard">
          <!-- 上方两列：操作控制台 + 自动化定时调度 -->
          <div class="probe-top-grid">
            <!-- 卡片 1: 运维操作控制台 (start / status / cancel) -->
            <div class="probe-card">
              <div class="card-title-group">
                <div class="kicker-tag">OPERATIONS CONSOLE</div>
                <h3>数据采集与版本探活控制台</h3>
                <p class="card-subtitle">支持单款/多款/全量游戏执行新版本查找与历史版本探活，并实时显示进度</p>
              </div>

              <!-- 动作模式选择 -->
              <div class="op-action-options">
                <label
                  class="op-action-card"
                  :class="{ active: opAction === 'both' }"
                  @click="opAction = 'both'"
                >
                  <input v-model="opAction" class="op-radio" type="radio" value="both" />
                  <div class="op-action-text">
                    <span class="op-action-title">✨ 查找新版本 + 探活全量 (discover + probe)</span>
                    <span class="op-action-desc">先查询官方入口获取最新版本并入库更新索引，再探活全部历史版本（推荐）</span>
                  </div>
                </label>

                <label
                  class="op-action-card"
                  :class="{ active: opAction === 'discover' }"
                  @click="opAction = 'discover'"
                >
                  <input v-model="opAction" class="op-radio" type="radio" value="discover" />
                  <div class="op-action-text">
                    <span class="op-action-title">🔍 仅查找新版本 (discover)</span>
                    <span class="op-action-desc">查询官方入口，获取最新版本，探活后保存 version.json 并更新索引</span>
                  </div>
                </label>

                <label
                  class="op-action-card"
                  :class="{ active: opAction === 'probe' }"
                  @click="opAction = 'probe'"
                >
                  <input v-model="opAction" class="op-radio" type="radio" value="probe" />
                  <div class="op-action-text">
                    <span class="op-action-title">⚡ 仅探活历史版本 (probe)</span>
                    <span class="op-action-desc">批量探活所选游戏在本地存储的所有历史版本可用性</span>
                  </div>
                </label>
              </div>

              <!-- 数据类型选择 (全量 / APK / PC) -->
              <div class="op-scope-tabs" style="margin-top: 10px;">
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opPlatformScope === 'all' }"
                  :disabled="operationControlsLocked"
                  :aria-pressed="opPlatformScope === 'all'"
                  @click="opPlatformScope = 'all'"
                >
                  🌐 全量数据 (APK + 已接入的 PC)
                </button>
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opPlatformScope === 'android' }"
                  :disabled="operationControlsLocked"
                  :aria-pressed="opPlatformScope === 'android'"
                  @click="opPlatformScope = 'android'"
                >
                  📱 仅 Android (APK)
                </button>
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opPlatformScope === 'pc' }"
                  :disabled="operationControlsLocked"
                  :aria-pressed="opPlatformScope === 'pc'"
                  @click="opPlatformScope = 'pc'"
                >
                  💻 仅 PC 客户端（已接入适配器）
                </button>
              </div>

              <!-- 游戏范围选择 -->
              <div class="op-scope-tabs" style="margin-top: 10px;">
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opScope === 'all' }"
                  @click="opScope = 'all'"
                >
                  全部游戏 (all_games=true)
                </button>
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opScope === 'custom' }"
                  @click="opScope = 'custom'"
                >
                  指定游戏 ({{ opSelectedGameIds.length }}/{{ catalog.games.length }})
                </button>
              </div>

              <!-- 指定游戏多选网格 -->
              <div v-if="opScope === 'custom'" class="op-games-selector">
                <div class="op-games-toolbar">
                  <span class="text-muted">点击游戏勾选/取消：</span>
                  <div class="op-games-actions">
                    <button type="button" class="op-mini-btn" @click="selectAllGames">全选</button>
                    <button type="button" class="op-mini-btn" @click="clearSelectedGames">清空</button>
                  </div>
                </div>
                <div class="op-games-grid">
                  <div
                    v-for="game in catalog.games"
                    :key="game.id"
                    class="op-game-chip"
                    :class="{ selected: isGameSelected(game.id) }"
                    @click="toggleGameSelection(game.id)"
                  >
                    <img
                      :src="resolveGameIcon(game.id, game.icon_source)"
                      class="op-game-icon"
                      alt=""
                      @error="useFallbackIcon($event, game.id)"
                    />
                    <span class="op-game-name" :title="game.name">{{ game.name }}</span>
                  </div>
                </div>
              </div>

              <!-- 高级参数配置 -->
              <div class="op-params-grid">
                <label class="admin-field">
                  <span class="field-label">请求超时 (秒)</span>
                  <input v-model.number="opTimeout" class="admin-input" type="number" min="1" max="60" />
                </label>
                <label class="admin-field">
                  <span class="field-label">并发线程数 (Workers)</span>
                  <input v-model.number="opWorkers" class="admin-input" type="number" min="1" max="16" />
                </label>
              </div>

              <!-- 执行操作按钮 -->
              <button
                class="admin-btn full-width"
                :class="opRunning ? 'danger' : 'primary'"
                type="button"
                :disabled="loading || opJob?.status === 'cancelling'"
                @click="opRunning ? cancelAdminOperation() : executeAdminOperation()"
              >
                <span>{{ opJob?.status === 'cancelling' ? '正在取消，等待当前请求结束…' : opRunning ? '■ 取消当前运维任务' : '▶ 启动运维任务' }}</span>
              </button>

              <div v-if="opJob" class="probe-progress-box">
                <div class="op-games-toolbar">
                  <strong>{{ opJob.phase === 'discover' ? '查找新版本' : opJob.phase === 'probe' ? '历史版本探活' : '准备中' }} · {{ operationScopeText }}</strong>
                  <span class="text-mono">{{ opJob.completed }} / {{ opJob.total }} · {{ opProgressPercent }}%</span>
                </div>
                <progress :value="opJob.completed" :max="Math.max(1, opJob.total)" style="width: 100%;"></progress>
                <div class="text-muted" style="font-size: 12px;">
                  当前阶段 {{ opJob.phase_completed }} / {{ opJob.phase_total }}
                  <template v-if="opJob.current?.game_id">
                    · {{ gameDisplayName(opJob.current.game_id) }}
                    <span v-if="opJob.current.version" class="text-mono"> v{{ opJob.current.version }}</span>
                  </template>
                  · 成功 {{ opJob.succeeded }} · 失败 {{ opJob.failed }}
                </div>
              </div>
            </div>

            <!-- 卡片 2: 定时调度与策略配置 -->
            <div class="probe-card">
              <div class="card-title-group">
                <div class="kicker-tag">AUTOMATION & SCHEDULES</div>
                <h3>定时调度策略配置</h3>
                <p class="card-subtitle">配置后台每日定时采集与定时探活周期计划</p>
              </div>

              <!-- 每日采集计划 -->
              <div class="schedule-toggle-row">
                <label class="admin-toggle-label">
                  <input v-model="syncSchedule.enabled" class="admin-toggle-checkbox" type="checkbox" />
                  <span class="toggle-slider"></span>
                  <span class="toggle-text">{{ syncSchedule.enabled ? '每日定时采集已启用' : '每日定时采集已停用' }}</span>
                </label>
              </div>
              <div class="schedule-inputs-row">
                <label class="admin-field">
                  <span class="field-label">时间点 1 (北京时间)</span>
                  <input v-model="syncSchedule.times[0]" class="admin-input" type="time" />
                </label>
                <label class="admin-field">
                  <span class="field-label">时间点 2 (北京时间)</span>
                  <input v-model="syncSchedule.times[1]" class="admin-input" type="time" />
                </label>
              </div>
              <button class="admin-btn secondary full-width" type="button" :disabled="loading" @click="saveSyncSchedule">
                <span>保存每日采集调度计划</span>
              </button>

              <hr style="border: 0; border-top: 1px solid var(--line-soft); margin: 6px 0;" />

              <!-- 定时探活计划 -->
              <div class="schedule-toggle-row">
                <label class="admin-toggle-label">
                  <input v-model="probeSchedule.enabled" class="admin-toggle-checkbox" type="checkbox" />
                  <span class="toggle-slider"></span>
                  <span class="toggle-text">{{ probeSchedule.enabled ? '定时探活已启用' : '定时探活已停用' }}</span>
                </label>
              </div>
              <div class="schedule-inputs-row">
                <label class="admin-field">
                  <span class="field-label">执行周期 (小时)</span>
                  <input v-model.number="probeSchedule.interval_hours" class="admin-input" type="number" min="1" max="168" />
                </label>
                <div class="admin-field">
                  <span class="field-label">默认模式</span>
                  <CustomSelect
                    v-model="probeSchedule.mode"
                    :options="[
                      { label: '正常轮 (TTL 20h)', value: 'normal' },
                      { label: '全量轮 (全部)', value: 'full' }
                    ]"
                  />
                </div>
              </div>
              <button class="admin-btn secondary full-width" type="button" :disabled="loading" @click="saveProbeSchedule">
                <span>保存定时探活计划</span>
              </button>
            </div>
          </div>

          <!-- 执行结果实时明细看板 (当有操作结果时展示) -->
          <div v-if="opResult" class="op-results-container">
            <div class="op-results-header">
              <div class="card-title-group">
                <div class="kicker-tag text-emerald">OPERATION RESULT SUMMARY</div>
                <h3>运维操作执行结果报告</h3>
                <p class="card-subtitle">
                  执行动作：<span class="text-mono font-bold">{{ opResult.actions.join(' + ') }}</span>
                  · 数据范围：<span class="text-mono font-bold">{{ operationScopeText }}</span>
                  · 目标游戏：<span class="text-mono font-bold">{{ opResult.game_ids.length }} 款</span>
                  · 总耗时：<span class="text-emerald text-mono font-bold">{{ opExecutionTime }} 秒</span>
                </p>
              </div>
              <button type="button" class="op-mini-btn" @click="clearOpResult">✕ 关闭结果卡片</button>
            </div>

            <!-- 汇总统计卡片 -->
            <div class="op-summary-cards">
              <div v-if="opResult.discover" class="op-stat-card">
                <span class="op-stat-label">查找成功任务</span>
                <div class="op-stat-value text-emerald">{{ opResult.discover.succeeded }} / {{ opResult.discover.selected }}</div>
              </div>
              <div v-if="opResult.discover" class="op-stat-card">
                <span class="op-stat-label">发现全新版本</span>
                <div class="op-stat-value text-cyan">{{ opResult.discover.new_versions }} 个</div>
              </div>
              <div v-if="opResult.discover && opResult.discover.failed > 0" class="op-stat-card">
                <span class="op-stat-label">查找失败任务</span>
                <div class="op-stat-value text-rose">{{ opResult.discover.failed }}</div>
              </div>
              <div v-if="opResult.discover && discoverSkippedCount(opResult.discover) > 0" class="op-stat-card">
                <span class="op-stat-label">不支持而跳过</span>
                <div class="op-stat-value text-amber">{{ discoverSkippedCount(opResult.discover) }}</div>
              </div>

              <div
                v-if="opResult.probe"
                class="op-stat-card clickable"
                :class="{ active: probeTableFilter === 'all' }"
                title="点击筛选：显示全部探活记录"
                @click="probeTableFilter = 'all'"
              >
                <span class="op-stat-label">探活 URL 总数</span>
                <div class="op-stat-value text-mono">{{ probeCheckedUrls(opResult.probe) }}</div>
              </div>
              <div
                v-if="opResult.probe"
                class="op-stat-card clickable tone-emerald"
                :class="{ active: probeTableFilter === 'available' }"
                title="点击筛选：仅显示可用 URL"
                @click="probeTableFilter = 'available'"
              >
                <span class="op-stat-label">可用 URL (Available)</span>
                <div class="op-stat-value text-emerald">{{ probeAvailableUrls(opResult.probe) }}</div>
              </div>
              <div
                v-if="opResult.probe"
                class="op-stat-card clickable tone-rose"
                :class="{ active: probeTableFilter === 'unavailable' }"
                title="点击筛选：仅显示失效 URL"
                @click="probeTableFilter = 'unavailable'"
              >
                <span class="op-stat-label">失效 URL (Unavailable)</span>
                <div class="op-stat-value text-rose">{{ probeUnavailableUrls(opResult.probe) }}</div>
              </div>
              <div
                v-if="opResult.probe && probeUnknownUrls(opResult.probe) > 0"
                class="op-stat-card clickable tone-amber"
                :class="{ active: probeTableFilter === 'unknown' }"
                title="点击筛选：仅显示未知/未判定 URL"
                @click="probeTableFilter = 'unknown'"
              >
                <span class="op-stat-label">未知 URL (Unknown)</span>
                <div class="op-stat-value text-amber">{{ probeUnknownUrls(opResult.probe) }}</div>
              </div>
              <div
                v-if="opResult.probe && probeFailedUrls(opResult.probe) > 0"
                class="op-stat-card clickable tone-amber"
                :class="{ active: probeTableFilter === 'failed' }"
                title="点击筛选：仅显示异常记录"
                @click="probeTableFilter = 'failed'"
              >
                <span class="op-stat-label">探活异常数</span>
                <div class="op-stat-value text-amber">{{ probeFailedUrls(opResult.probe) }}</div>
              </div>
            </div>

            <!-- 查找新版本明细表 -->
            <div v-if="opResult.discover" class="op-table-section">
              <h4 style="margin: 0 0 10px; font-size: 13.5px; font-weight: 750; color: #7dd3fc;">🔍 查找新版本 (Discover) 执行明细</h4>
              <div class="op-table-wrapper">
                <table class="op-table">
                  <thead>
                    <tr>
                      <th>游戏</th>
                      <th>平台</th>
                      <th>执行状态</th>
                      <th>官方最新版本</th>
                      <th>版本标记</th>
                      <th>下载可用性</th>
                      <th>存储路径 / 错误详情</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in opResult.discover.items" :key="`${item.game_id}-${item.platform || item.scope || 'unknown'}-${item.version || 'none'}`">
                      <td>
                        <strong class="text-mono">{{ gameDisplayName(item.game_id) }}</strong>
                      </td>
                      <td><span class="text-mono">{{ item.platform || item.scope || '--' }}</span></td>
                      <td>
                        <span v-if="discoverItemState(item) === 'skipped'" class="op-badge warning">↷ 跳过（不支持）</span>
                        <span v-else-if="discoverItemState(item) === 'success'" class="op-badge success">✓ 成功</span>
                        <span v-else class="op-badge danger">✕ 失败</span>
                      </td>
                      <td>
                        <span class="text-mono font-bold">{{ item.version || '--' }}</span>
                      </td>
                      <td>
                        <span v-if="item.new" class="op-badge info">🆕 全新版本</span>
                        <span v-else-if="discoverItemState(item) === 'success'" class="op-badge muted">现有最新</span>
                        <span v-else class="text-muted">--</span>
                      </td>
                      <td>
                        <span v-if="discoverItemState(item) === 'skipped'" class="op-badge warning">不适用</span>
                        <span v-else-if="item.available === true" class="op-badge success">可用 (200)</span>
                        <span v-else-if="item.available === false" class="op-badge danger">不可用</span>
                        <span v-else-if="discoverItemState(item) === 'success'" class="op-badge warning">未探活</span>
                        <span v-else class="text-muted">--</span>
                      </td>
                      <td>
                        <span v-if="item.error" class="text-rose text-mono" style="font-size: 11.5px;">{{ item.error }}</span>
                        <span v-else-if="item.path" class="text-muted text-mono" style="font-size: 11.5px;">{{ item.path }}</span>
                        <span v-else class="text-muted">--</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 探活历史版本明细表 -->
            <div v-if="opResult.probe" class="op-table-section">
              <div class="op-table-head-row">
                <h4 style="margin: 0; font-size: 13.5px; font-weight: 750; color: #34d399;">
                  ⚡ 历史版本探活 (Probe) 执行明细
                  <span v-if="probeTableFilter === 'all'" class="text-muted" style="font-weight: 400; margin-left: 6px;">(共 {{ filteredProbeItems.length }} 条)</span>
                  <span v-else-if="probeTableFilter === 'available'" style="color: #34d399; font-weight: 700; margin-left: 6px;">(仅显示可用: {{ filteredProbeItems.length }} 条)</span>
                  <span v-else-if="probeTableFilter === 'unavailable'" style="color: #f43f5e; font-weight: 700; margin-left: 6px;">(仅显示失效: {{ filteredProbeItems.length }} 条)</span>
                  <span v-else-if="probeTableFilter === 'unknown'" style="color: #fbbf24; font-weight: 700; margin-left: 6px;">(仅显示未知: {{ filteredProbeItems.length }} 条)</span>
                  <span v-else-if="probeTableFilter === 'failed'" style="color: #fbbf24; font-weight: 700; margin-left: 6px;">(仅显示异常: {{ filteredProbeItems.length }} 条)</span>
                </h4>
                <div class="op-filter-chips">
                  <button
                    type="button"
                    class="op-filter-chip"
                    :class="{ active: probeTableFilter === 'all' }"
                    @click="probeTableFilter = 'all'"
                  >全部 ({{ opResult.probe.items.length }})</button>
                  <button
                    type="button"
                    class="op-filter-chip tone-emerald"
                    :class="{ active: probeTableFilter === 'available' }"
                    @click="probeTableFilter = 'available'"
                  >✓ 可用 ({{ probeAvailableUrls(opResult.probe) }})</button>
                  <button
                    type="button"
                    class="op-filter-chip tone-rose"
                    :class="{ active: probeTableFilter === 'unavailable' }"
                    @click="probeTableFilter = 'unavailable'"
                  >✕ 失效 ({{ probeUnavailableUrls(opResult.probe) }})</button>
                  <button
                    v-if="probeUnknownUrls(opResult.probe) > 0"
                    type="button"
                    class="op-filter-chip tone-amber"
                    :class="{ active: probeTableFilter === 'unknown' }"
                    @click="probeTableFilter = 'unknown'"
                  >? 未知 ({{ probeUnknownUrls(opResult.probe) }})</button>
                  <button
                    v-if="probeFailedUrls(opResult.probe) > 0"
                    type="button"
                    class="op-filter-chip tone-amber"
                    :class="{ active: probeTableFilter === 'failed' }"
                    @click="probeTableFilter = 'failed'"
                  >⚠ 异常 ({{ probeFailedUrls(opResult.probe) }})</button>
                </div>
              </div>
              <div class="op-table-wrapper" style="max-height: 340px; overflow-y: auto;">
                <table class="op-table">
                  <thead>
                    <tr>
                      <th>游戏</th>
                      <th>平台</th>
                      <th>版本</th>
                      <th>Artifact / URL</th>
                      <th>可用性状态</th>
                      <th>探活适配器</th>
                      <th>错误 / 异常信息</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="pItem in filteredProbeItems" :key="probeItemKey(pItem)">
                      <td><strong class="text-mono">{{ gameDisplayName(pItem.game_id) }}</strong></td>
                      <td><span class="text-mono">{{ pItem.platform || '--' }}</span></td>
                      <td><span class="text-mono font-bold">{{ pItem.version }}</span></td>
                      <td>
                        <span v-if="pItem.kind" class="op-badge muted">{{ pItem.kind }}</span>
                        <span v-if="pItem.url" class="text-mono text-muted" style="display: block; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px;" :title="pItem.url">{{ pItem.url }}</span>
                        <span v-if="pItem.artifact_index !== undefined || pItem.url_index !== undefined" class="text-muted" style="font-size: 10.5px;">#{{ pItem.artifact_index ?? '-' }}/{{ pItem.url_index ?? '-' }}</span>
                      </td>
                      <td>
                        <span v-if="pItem.available === true" class="op-badge success">✓ 可用</span>
                        <span v-else-if="pItem.available === false" class="op-badge danger">✕ 失效</span>
                        <span v-else-if="pItem.ok" class="op-badge warning">? 未知</span>
                        <span v-else class="op-badge danger">✕ 探测失败</span>
                      </td>
                      <td><span class="text-mono text-muted" style="font-size: 11.5px;">{{ pItem.adapter || 'default' }}</span></td>
                      <td>
                        <span v-if="pItem.error" class="text-rose text-mono" style="font-size: 11.5px;">{{ pItem.error }}</span>
                        <span v-else class="text-emerald" style="font-size: 11.5px;">正常</span>
                      </td>
                    </tr>
                    <tr v-if="filteredProbeItems.length === 0">
                      <td colspan="7" style="text-align: center; padding: 24px; color: var(--muted);">
                        当前筛选条件下没有匹配的探活记录
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- 底部全宽黑曜石终端日志窗口 (Terminal Console) -->
          <div class="admin-terminal-window">
            <div class="terminal-titlebar">
              <div class="terminal-dots">
                <span class="dot red"></span>
                <span class="dot yellow"></span>
                <span class="dot green"></span>
              </div>
              <div class="terminal-title">CONSOLE LOG STREAM · {{ operationScopeText }} · OPERATIONS & PROBE LOGS</div>
              <div class="terminal-actions">
                <button class="terminal-refresh-btn" type="button" @click="opTerminalHidden = true">
                  <span>🧹 清屏（仅当前页面）</span>
                </button>
                <button class="terminal-refresh-btn" type="button" :disabled="loading || operationPollBusy" @click="refreshTerminalLogs">
                  <span>🔄 刷新日志</span>
                </button>
              </div>
            </div>
            <div class="terminal-viewport">
              <pre class="terminal-pre"><code>{{ opTerminalHidden ? '--- 已清屏，仅隐藏当前页面日志；新日志到达后会继续显示 ---' : (opTerminalLogs.length ? opTerminalLogs.join('\n') : (syncRunStatus?.result?.log_tail || (probeStatus?.log || []).slice(-150).join('\n') || '--- 暂无实时运维或探活日志，点击上方执行按钮开始操作 ---')) }}</code></pre>
            </div>
          </div>
        </section>

        <!-- 模块 5：数据保留与自动清理 (Retention & Cleanup Console) -->
        <section v-else-if="tab === 'retention'" class="admin-retention-dashboard">
          <!-- 上方双列：策略配置 + 最近执行状态 -->
          <div class="retention-top-grid">
            <!-- 卡片 1: 保留与自动清理策略配置 -->
            <div class="retention-card">
              <div class="card-title-group">
                <div class="kicker-tag">RETENTION POLICY</div>
                <h3>自动清理与保留策略配置</h3>
                <p class="card-subtitle">
                  配置本地缓存生命周期、旧运维记录与探活历史轮转天数。保存后立即热加载生效，无需重启服务。
                </p>
              </div>

              <form class="retention-form" @submit.prevent="saveRetentionConfig">
                <!-- 1. cache_days -->
                <div class="retention-setting-block">
                  <div class="setting-block-header">
                    <div class="setting-title-wrap">
                      <span class="setting-icon-badge">📦</span>
                      <div class="setting-title-text">
                        <strong>缓存与临时文件保留</strong>
                        <code>cache_days</code>
                      </div>
                    </div>
                    <span class="setting-range-pill">1 ～ 36,500 天</span>
                  </div>

                  <div class="setting-stepper-row">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="retentionConfig.cache_days <= 1"
                        @click="adjustRetentionField('cache_days', -1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                          id="retention-cache-days"
                          v-model.number="retentionConfig.cache_days"
                          class="stepper-input"
                          type="number"
                          min="1"
                          max="36500"
                          step="1"
                          required
                        />
                        <span class="stepper-unit">天</span>
                      </div>
                      <button
                        type="button"
                        class="stepper-btn inc"
                        :disabled="retentionConfig.cache_days >= 36500"
                        @click="adjustRetentionField('cache_days', 1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                    </div>

                    <div class="preset-chips">
                      <button
                        v-for="preset in [7, 15, 30, 90, 180]"
                        :key="preset"
                        type="button"
                        class="preset-chip"
                        :class="{ active: retentionConfig.cache_days === preset }"
                        @click="setRetentionPreset('cache_days', preset)"
                      >
                        {{ preset }}天{{ preset === 30 ? ' · 推荐' : '' }}
                      </button>
                    </div>
                  </div>

                  <p class="setting-desc">
                    安全轮转 <code>data/.cache</code> 下的下载临时文件、解压残留分块及超期运维任务历史记录。
                  </p>
                </div>

                <!-- 2. observation_days -->
                <div class="retention-setting-block">
                  <div class="setting-block-header">
                    <div class="setting-title-wrap">
                      <span class="setting-icon-badge">🔭</span>
                      <div class="setting-title-text">
                        <strong>探活历史观测数据保留</strong>
                        <code>observation_days</code>
                      </div>
                    </div>
                    <span class="setting-range-pill">1 ～ 36,500 天</span>
                  </div>

                  <div class="setting-stepper-row">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="retentionConfig.observation_days <= 1"
                        @click="adjustRetentionField('observation_days', -1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                          id="retention-obs-days"
                          v-model.number="retentionConfig.observation_days"
                          class="stepper-input"
                          type="number"
                          min="1"
                          max="36500"
                          step="1"
                          required
                        />
                        <span class="stepper-unit">天</span>
                      </div>
                      <button
                        type="button"
                        class="stepper-btn inc"
                        :disabled="retentionConfig.observation_days >= 36500"
                        @click="adjustRetentionField('observation_days', 1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                    </div>

                    <div class="preset-chips">
                      <button
                        v-for="preset in [30, 60, 90, 180, 365]"
                        :key="preset"
                        type="button"
                        class="preset-chip"
                        :class="{ active: retentionConfig.observation_days === preset }"
                        @click="setRetentionPreset('observation_days', preset)"
                      >
                        {{ preset }}天{{ preset === 90 ? ' · 推荐' : '' }}
                      </button>
                    </div>
                  </div>

                  <p class="setting-desc">
                    控制已归档版本下载直链的历史观测（observations）最长存储天数，超期将安全裁剪。
                  </p>
                </div>

                <!-- 3. interval_hours -->
                <div class="retention-setting-block">
                  <div class="setting-block-header">
                    <div class="setting-title-wrap">
                      <span class="setting-icon-badge">⏱️</span>
                      <div class="setting-title-text">
                        <strong>后台自动清理周期</strong>
                        <code>interval_hours</code>
                      </div>
                    </div>
                    <span class="setting-range-pill">1 ～ 8,760 小时</span>
                  </div>

                  <div class="setting-stepper-row">
                    <div class="stepper-control">
                      <button
                        type="button"
                        class="stepper-btn dec"
                        :disabled="retentionConfig.interval_hours <= 1"
                        @click="adjustRetentionField('interval_hours', -1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                      <div class="stepper-input-wrap">
                        <input
                          id="retention-interval-hours"
                          v-model.number="retentionConfig.interval_hours"
                          class="stepper-input"
                          type="number"
                          min="1"
                          max="8760"
                          step="1"
                          required
                        />
                        <span class="stepper-unit">小时</span>
                      </div>
                      <button
                        type="button"
                        class="stepper-btn inc"
                        :disabled="retentionConfig.interval_hours >= 8760"
                        @click="adjustRetentionField('interval_hours', 1)"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      </button>
                    </div>

                    <div class="preset-chips">
                      <button
                        v-for="preset in [6, 12, 24, 48, 168]"
                        :key="preset"
                        type="button"
                        class="preset-chip"
                        :class="{ active: retentionConfig.interval_hours === preset }"
                        @click="setRetentionPreset('interval_hours', preset)"
                      >
                        {{ preset === 168 ? '7天(168h)' : `${preset}小时` }}{{ preset === 24 ? ' · 推荐' : '' }}
                      </button>
                    </div>
                  </div>

                  <p class="setting-desc">
                    后台自动执行清理的任务间隔。保存后直接唤醒事件循环重置倒计时，实时生效。
                  </p>
                </div>

                <div class="retention-actions-footer">
                  <button
                    class="retention-btn-save"
                    type="submit"
                    :disabled="loading || retentionSaving || retentionRunning"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                      <polyline points="17 21 17 13 7 13 7 21" />
                      <polyline points="7 3 7 8 15 8" />
                    </svg>
                    <span>{{ retentionSaving ? '保存唤醒中…' : '保存配置并立即生效' }}</span>
                  </button>
                  <button
                    class="retention-btn-reset"
                    type="button"
                    :disabled="loading || retentionSaving || retentionRunning"
                    @click="resetRetentionDefaults"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                      <path d="M3 3v5h5" />
                    </svg>
                    <span>恢复推荐默认值</span>
                  </button>
                </div>
              </form>
            </div>

            <!-- 卡片 2: 最近一次清理状态与指标 -->
            <div class="retention-card">
              <div class="card-title-group">
                <div class="kicker-tag">LATEST RUN STATUS</div>
                <h3>最近执行状态与删除统计</h3>
                <p class="card-subtitle">
                  保存于 <code>data/.cache/retention_status.json</code>，记录上次自动调度或管理员手动执行清理的完整统计指标。
                </p>
              </div>

              <!-- 状态概览栏 -->
              <div class="retention-hero-card" :class="retentionStatus?.error ? 'is-error' : (retentionStatus?.source ? 'is-active' : 'is-idle')">
                <div class="hero-status-left">
                  <div class="pulse-indicator-wrap">
                    <span class="pulse-ring"></span>
                    <span class="pulse-core"></span>
                  </div>
                  <div class="hero-title-group">
                    <div class="hero-status-title">
                      {{ retentionHeroTitle }}
                    </div>
                    <div class="hero-status-meta">
                      <span>完成时间: <b>{{ formatSyncTime(retentionStatus?.finished_at || retentionStatus?.started_at) || '无历史记录' }}</b></span>
                      <span class="meta-dot">·</span>
                      <span>耗时: <b>{{ retentionDurationText(retentionStatus?.started_at, retentionStatus?.finished_at) }}</b></span>
                    </div>
                  </div>
                </div>
                <div class="hero-status-right">
                  <span class="source-tag" :class="retentionStatus?.source || 'none'">
                    {{ retentionSourceLabel(retentionStatus?.source) }}
                  </span>
                </div>
              </div>

              <!-- 错误提醒 -->
              <div v-if="retentionStatus?.error" class="admin-alert error" style="margin: 0;">
                <span>执行异常：{{ retentionStatus.error }}</span>
              </div>

              <!-- 6 大删除指标网格 -->
              <div class="retention-metrics-grid">
                <div class="metric-card theme-cyan">
                  <div class="metric-header">
                    <span class="metric-icon">🗄️</span>
                    <span class="metric-label">过期缓存清除</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.cache_deleted ?? 0 }}</strong>
                    <span class="metric-unit">项</span>
                  </div>
                  <span class="metric-hint">data/.cache 临时文件</span>
                </div>

                <div class="metric-card theme-blue">
                  <div class="metric-header">
                    <span class="metric-icon">📑</span>
                    <span class="metric-label">临时文件清除</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.temp_deleted ?? 0 }}</strong>
                    <span class="metric-unit">项</span>
                  </div>
                  <span class="metric-hint">下载解压中间产物</span>
                </div>

                <div class="metric-card theme-purple">
                  <div class="metric-header">
                    <span class="metric-icon">📋</span>
                    <span class="metric-label">旧运维记录清除</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.operation_deleted ?? 0 }}</strong>
                    <span class="metric-unit">条</span>
                  </div>
                  <span class="metric-hint">超期历史任务日志</span>
                </div>

                <div class="metric-card theme-indigo">
                  <div class="metric-header">
                    <span class="metric-icon">📡</span>
                    <span class="metric-label">探活观测清除</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.observations_deleted ?? 0 }}</strong>
                    <span class="metric-unit">条</span>
                  </div>
                  <span class="metric-hint">历史版本探测明细</span>
                </div>

                <div class="metric-card theme-amber" :class="{ 'has-value': (retentionStatus?.result?.skipped ?? 0) > 0 }">
                  <div class="metric-header">
                    <span class="metric-icon">🔒</span>
                    <span class="metric-label">锁冲突 / 跳过数</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.skipped ?? 0 }}</strong>
                    <span class="metric-unit">项</span>
                  </div>
                  <span class="metric-hint">保护中或并发占用</span>
                </div>

                <div class="metric-card" :class="(retentionStatus?.result?.errors ?? 0) > 0 ? 'theme-rose has-value' : 'theme-emerald'">
                  <div class="metric-header">
                    <span class="metric-icon">{{ (retentionStatus?.result?.errors ?? 0) > 0 ? '⚠️' : '✅' }}</span>
                    <span class="metric-label">清理错误数</span>
                  </div>
                  <div class="metric-value-row">
                    <strong class="metric-number">{{ retentionStatus?.result?.errors ?? 0 }}</strong>
                    <span class="metric-unit">项</span>
                  </div>
                  <span class="metric-hint">{{ (retentionStatus?.result?.errors ?? 0) === 0 ? '运行状态健康' : '存在异常排查' }}</span>
                </div>
              </div>

              <!-- 立即手动执行操作栏 -->
              <div class="retention-card-footer">
                <div class="footer-security-pill">
                  <span class="sec-dot"></span>
                  <span>受限沙盒与进程互斥锁防护生效中</span>
                </div>
                <div class="footer-actions">
                  <button
                    class="action-btn-ghost"
                    type="button"
                    :disabled="loading || retentionRunning"
                    title="重新获取最新清理执行状态"
                    @click="loadRetentionStatus(undefined, true)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
                    </svg>
                    <span>刷新状态</span>
                  </button>
                  <button
                    class="action-btn-run"
                    type="button"
                    :disabled="loading || retentionRunning || retentionSaving"
                    @click="runRetentionManual"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                    <span>{{ retentionRunning ? '正在执行清理…' : '立即执行清理' }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 下方全宽：数据生命周期与安全性 Bento 矩阵 -->
          <div class="retention-security-bento">
            <div class="bento-feature-card">
              <div class="bento-icon-box">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
              </div>
              <h4>核心元数据不可变</h4>
              <p>仅安全轮转临时缓存与过期探活观测，绝不修改或删除任何游戏已入库的 <code>version.json</code> 核心版本清单。</p>
            </div>

            <div class="bento-feature-card">
              <div class="bento-icon-box">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
              </div>
              <h4>受限沙盒与越界防御</h4>
              <p>所有清理路径均严格校验于 <code>data/.cache</code> 目录范围，自动拦截阻断软链接、符号链接与跨目录穿透。</p>
            </div>

            <div class="bento-feature-card">
              <div class="bento-icon-box">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
                  <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
                  <line x1="6" y1="6" x2="6.01" y2="6"/>
                  <line x1="6" y1="18" x2="6.01" y2="18"/>
                </svg>
              </div>
              <h4>跨进程排他文件锁</h4>
              <p>执行期间独占 <code>.retention.lock</code> 互斥锁，彻底杜绝数据清理与并发探活、自动同步任务之间的文件读写冲突。</p>
            </div>

            <div class="bento-feature-card">
              <div class="bento-icon-box">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
              </div>
              <h4>毫秒级热重载生效</h4>
              <p>配置保存后立即向后台异步事件循环发送唤醒信号重置倒计时，无需重启后端服务即可即时生效。</p>
            </div>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>
