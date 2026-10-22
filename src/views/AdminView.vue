<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import "../styles/admin.css";
import { ApiError, adminApi } from "../api";
import {
  adminUiCapabilities,
  externalScheduleNotice,
  manualVersionSavedMessage,
  probeScheduleNotice,
  supportsApkVersionEditor,
} from "../admin-ui-capabilities";
import { gameIcons } from "../game-icons";
import { formatBytes, formatSyncTime, getFileTimeSourceDescription } from "../admin-format";
import { formatFileTimeLabel, isoToLocalInput, localInputToIso } from "../admin-date-time";
import CustomSelect from "../components/CustomSelect.vue";
import AdminGameCatalog from "../components/admin/AdminGameCatalog.vue";
import AdminDomainCatalog from "../components/admin/AdminDomainCatalog.vue";
import AdminConfirmDialog, {
  type ConfirmDialogRequest,
} from "../components/admin/AdminConfirmDialog.vue";
import AdminIcon from "../components/admin/AdminIcon.vue";
import AdminLoginView from "../components/admin/AdminLoginView.vue";
import AdminRail from "../components/admin/AdminRail.vue";
import AdminPcArtifactFields from "../components/admin/AdminPcArtifactFields.vue";
import AdminOperationProgress from "../components/admin/AdminOperationProgress.vue";
import {
  discoverItemState,
  discoverSkippedCount,
  isProbeUnknownItem,
  operationControlsDisabled,
  operationScopeLabel,
  probeAvailableUrls,
  probeCheckedUrls,
  probeFailedUrls,
  probeItemKey,
  probeResultReason,
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
  ProbeSchedulerStatus,
  ProbeStatus,
  ProbeUrlResult,
  SyncRunStatus,
  SyncSchedule,
  VersionSummary,
} from "../types";

type Tab = "games" | "domains" | "content" | "probe";

const TOKEN_STORAGE_KEY = "game-manifest-index-web-admin-token-v1";
const OPERATION_JOB_KEY = "game-manifest-index-web-operation-job-v1";
const AVAILABILITY_INVALIDATION_EVENT = "gmi-availability-invalidated";
const AVAILABILITY_INVALIDATION_STORAGE_KEY = "gmi-availability-invalidated-at";
let lastInvalidatedOperationJobId: string | null = null;
let availabilityInvalidationSequence = 0;

const router = useRouter();
const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY) || "");
const authenticated = ref(false);
const catalog = ref<AdminCatalog>({ games: [], domains: [] });
const tab = ref<Tab>("games");
const loading = ref(false);
const error = ref("");
const success = ref("");

interface PendingConfirm extends ConfirmDialogRequest {
  resolve: (accepted: boolean) => void;
}

const pendingConfirm = ref<PendingConfirm | null>(null);

function askConfirm(
  message: string,
  options: Partial<Omit<ConfirmDialogRequest, "message">> = {},
): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    pendingConfirm.value = {
      title: options.title ?? "请确认操作",
      message,
      confirmLabel: options.confirmLabel ?? "确认",
      cancelLabel: options.cancelLabel ?? "取消",
      tone: options.tone ?? "default",
      resolve,
    };
  });
}

function resolveConfirm(accepted: boolean): void {
  const pending = pendingConfirm.value;
  pendingConfirm.value = null;
  pending?.resolve(accepted);
}

const currentTabMeta = computed(() => {
  switch (tab.value) {
    case "games":
      return {
        title: "游戏入口目录",
        subtitle: "维护游戏入口、图标资源、展示排序与前台可见性",
      };
    case "domains":
      return {
        title: "数据模块目录",
        subtitle: "维护数据模块、适配器契约与版本能力",
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
const probeSchedulerStatus = ref<ProbeSchedulerStatus | null>(null);
let probePollTimer: number | null = null;
const newGame = ref(false);
const newDomain = ref(false);
interface EditableArtifactDraft {
  artifact_id?: string;
  kind: string;
  name: string;
  part: number;
  size: number;
  component: string;
  package_type: string;
  delivery_mode: string;
  language: string;
  route_from: string;
  route_to: string;
  decompressed_size: number | null;
  manifestJson: string;
  sourceJson: string;
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
const moreActionsOpen = ref(false);

const editableDraft = ref<VersionDraft>({
  version: "",
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

function supportsPcVersionEditor(domain: AdminDomain | null | undefined): boolean {
  const normalized = (domain?.platform || "").trim().toLowerCase();
  if (normalized !== "windows" && normalized !== "pc") return false;
  const capabilities = new Set((domain?.capabilities || []).map((item) => item.trim().toLowerCase()));
  const kind = (domain?.kind || "").trim().toLowerCase();
  return capabilities.has("packages") || capabilities.has("patches") || kind === "packages" || kind === "patches";
}

const selectedDomainSupportsCreateVersion = computed(() =>
  supportsApkVersionEditor(selectedDomainObj.value?.platform),
);

const selectedDomainUsesPcEditor = computed(() =>
  supportsPcVersionEditor(selectedDomainObj.value),
);

const selectedDomainSupportsManualVersion = computed(() =>
  selectedDomainSupportsCreateVersion.value || selectedDomainUsesPcEditor.value,
);

const currentVersionItem = computed(() =>
  versions.value.find((v) => v.version === selectedVersion.value) || null,
);

const currentVersionHealth = computed(() => {
  const summary = currentVersionItem.value;
  if (summary) {
    if (isVersionUnavailable(summary)) {
      return {
        isChecked: true,
        isOk: false,
        httpCode: null as number | null,
        available: false,
        lastCheckedAt: null as string | null,
        size: summary.packed_size || 0,
      };
    }
    if (!isVersionUnknown(summary)) {
      return {
        isChecked: true,
        isOk: true,
        httpCode: null as number | null,
        available: true,
        lastCheckedAt: null as string | null,
        size: summary.packed_size || 0,
      };
    }
  }

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

const pcArtifactsOverview = computed(() => {
  const artifacts = editableDraft.value.artifacts || [];
  const packageCount = artifacts.filter((item) => item.kind === "package").length;
  const patchCount = artifacts.filter((item) => item.kind === "patch").length;
  const urlCount = artifacts.reduce((total, item) =>
    total + (item.urls || []).filter((urlItem) => urlItem.url.trim()).length, 0);
  const totalSize = artifacts.reduce((total, item) => total + (Number(item.size) || 0), 0);
  return {
    total: artifacts.length,
    packageCount,
    patchCount,
    urlCount,
    totalSize,
  };
});

const isUrlChanged = computed(() => {
  if (!editableLoaded.value || !editableDraft.value.artifacts.length) return false;
  const currentUrl = editableDraft.value.artifacts[0]?.urls[0]?.url?.trim() || "";
  const initialUrl = editableDraft.value.artifacts[0]?.urls[0]?.persisted_url?.trim() || "";
  return initialUrl !== "" && currentUrl !== initialUrl;
});

function isVersionAvailable(item: VersionSummary): boolean {
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  if (unavailableCount > 0 && availableCount === 0 && canonicalCount === 0) {
    return false;
  }
  return true;
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

  let currentArtifacts = "";
  try {
    currentArtifacts = normalizeArtifactsForComparison(buildArtifactsPayload());
  } catch {
    count++;
    return count;
  }
  if (currentArtifacts !== (original.artifacts || "")) count++;

  return count;
});

function clearActiveFileTime(): void {
  versionDraft.value.file_created_at_override = "";
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

const ARTIFACT_ATTRIBUTE_KEYS = [
  "component",
  "package_type",
  "delivery_mode",
  "language",
  "route_from",
  "route_to",
  "decompressed_size",
  "manifest",
  "source",
] as const;

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function jsonValueToText(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function parseOptionalJsonOrString(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function compactArtifactAttributes(attributes: Record<string, unknown>): string {
  const extra = { ...attributes };
  for (const key of ARTIFACT_ATTRIBUTE_KEYS) {
    delete extra[key];
  }
  return JSON.stringify(extra, null, 2);
}

type ArtifactUrlInput = { id?: number; url?: unknown; priority?: unknown; source_kind?: unknown };

function normalizeArtifactUrls(
  urls: readonly ArtifactUrlInput[] | undefined,
  filterEmpty = false,
  preservePersistedUrl = false,
  parsePriority: (value: unknown, index: number) => number = (value, index) => Number.isFinite(Number(value)) ? Number(value) : index,
) {
  return (urls || [])
    .map((u, index) => {
      const rawUrl = String(u.url || "");
      return {
        id: u.id,
        ...(preservePersistedUrl ? { persisted_url: rawUrl } : {}),
        url: rawUrl.trim(),
        priority: parsePriority(u.priority, index),
        source_kind: String(u.source_kind || "official").trim(),
      };
    })
    .filter((u) => !filterEmpty || Boolean(u.url));
}

function artifactDraftFromPayload(item: any, idx: number): EditableArtifactDraft {
  const attrs: Record<string, unknown> =
    typeof item.attributes === "object" && item.attributes !== null && !Array.isArray(item.attributes)
      ? item.attributes
      : {};
  return {
    artifact_id: typeof item.artifact_id === "string" ? item.artifact_id : undefined,
    kind: String(item.kind || "file").trim(),
    name: String(item.name || "").trim(),
    part: Number(item.part) || idx + 1,
    size: Number(item.size) || 0,
    component: String(item.component ?? attrs.component ?? "game"),
    package_type: String(item.package_type ?? attrs.package_type ?? ""),
    delivery_mode: String(item.delivery_mode ?? attrs.delivery_mode ?? ""),
    language: String(item.language ?? attrs.language ?? ""),
    route_from: String(item.route_from ?? attrs.route_from ?? ""),
    route_to: String(item.route_to ?? attrs.route_to ?? ""),
    decompressed_size: numberOrNull(item.decompressed_size ?? attrs.decompressed_size),
    manifestJson: jsonValueToText(item.manifest ?? attrs.manifest),
    sourceJson: jsonValueToText(item.source ?? attrs.source),
    checksum_type: item.checksum_type ? String(item.checksum_type).trim() : "",
    checksum_value: item.checksum_value ? String(item.checksum_value).trim() : "",
    attributesJson: compactArtifactAttributes(attrs),
    urls: Array.isArray(item.urls) ? normalizeArtifactUrls(item.urls, false, true) : [],
  };
}

function buildVisualArtifactAttributes(art: EditableArtifactDraft): Record<string, unknown> {
  let attributes: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(art.attributesJson || "{}");
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      attributes = parsed as Record<string, unknown>;
    }
  } catch {
    throw new Error(`${art.name || art.kind || "artifact"} 的附加属性 JSON 格式错误`);
  }
  const common: Array<[string, unknown]> = [
    ["component", art.component.trim() || "game"],
    ["package_type", art.package_type.trim()],
    ["delivery_mode", art.delivery_mode.trim()],
    ["language", art.language.trim()],
    ["route_from", art.route_from.trim()],
    ["route_to", art.route_to.trim()],
    ["decompressed_size", getNormalizedUnpackedSize(art.decompressed_size)],
    ["manifest", parseOptionalJsonOrString(art.manifestJson)],
    ["source", parseOptionalJsonOrString(art.sourceJson)],
  ];
  for (const [key, value] of common) {
    if (value !== undefined && value !== null && value !== "") {
      attributes[key] = value;
    } else {
      delete attributes[key];
    }
  }
  return attributes;
}

function normalizeArtifactPayloadFromJson(item: any, idx: number): ManualArtifactPayload {
  const attributes: Record<string, unknown> =
    typeof item.attributes === "object" && item.attributes !== null && !Array.isArray(item.attributes)
      ? { ...item.attributes }
      : {};
  for (const key of ARTIFACT_ATTRIBUTE_KEYS) {
    if (item[key] !== undefined && attributes[key] === undefined) {
      attributes[key] = item[key];
    }
  }
  return {
    artifact_id: typeof item.artifact_id === "string" ? item.artifact_id : undefined,
    kind: String(item.kind || "file").trim(),
    name: String(item.name || `part_${idx + 1}`).trim(),
    part: Number(item.part) || idx + 1,
    size: Number(item.size) || 0,
    checksum_type: item.checksum_type ? String(item.checksum_type).trim() : null,
    checksum_value: item.checksum_value ? String(item.checksum_value).trim().toLowerCase() : null,
    attributes,
    urls: Array.isArray(item.urls) ? normalizeArtifactUrls(item.urls, true) : [],
  };
}

function parseArtifactsJsonPayload(jsonText: string): ManualArtifactPayload[] {
  const parsed = JSON.parse(jsonText || "[]");
  if (!Array.isArray(parsed)) {
    throw new Error("Artifacts JSON 顶层必须是数组");
  }
  return parsed.map(normalizeArtifactPayloadFromJson);
}

function buildArtifactsPayload(): ManualArtifactPayload[] {
  if (editableDraft.value.artifactsMode === "json") {
    return parseArtifactsJsonPayload(editableDraft.value.artifactsJson);
  }

  return editableDraft.value.artifacts.map((art, idx) => {
    return {
      artifact_id: art.artifact_id,
      kind: art.kind.trim() || "file",
      name: art.name.trim() || `part_${idx + 1}`,
      part: Number(art.part) || idx + 1,
      size: Number(art.size) || 0,
      checksum_type: art.checksum_type.trim() || null,
      checksum_value: art.checksum_value.trim().toLowerCase() || null,
      attributes: buildVisualArtifactAttributes(art),
      urls: normalizeArtifactUrls(art.urls, true),
    };
  });
}

const PC_COMPONENTS = new Set(["game", "voice", "launcher", "other"]);
const PC_PACKAGE_TYPES = new Set(["full", "segment", "optional", "differential"]);
const PC_DELIVERY_MODES = new Set(["direct", "archive", "file_manifest"]);
const COMPACT_SOURCE_KEYS = new Set(["source_kind", "source_name", "source_url", "source_repo", "source_commit"]);
const COMPACT_SOURCE_KINDS = new Set(["official_sync", "third_party_history", "legacy_migration", "manual"]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validatePcArtifacts(artifacts: ManualArtifactPayload[]): void {
  artifacts.forEach((artifact, index) => {
    const label = `PC artifact #${index + 1}`;
    const attributes = isPlainObject(artifact.attributes) ? artifact.attributes : {};
    const component = String(attributes.component || "").trim();
    const packageType = String(attributes.package_type || "").trim();
    const deliveryMode = String(attributes.delivery_mode || "").trim();
    const language = String(attributes.language || "").trim();
    const routeFrom = String(attributes.route_from || "").trim();
    const routeTo = String(attributes.route_to || "").trim();
    const part = Number(artifact.part);
    const size = Number(artifact.size);
    const decompressedSize = attributes.decompressed_size;
    const checksumType = (artifact.checksum_type || "").trim().toLowerCase();
    const checksumValue = (artifact.checksum_value || "").trim();

    if (!PC_COMPONENTS.has(component)) {
      throw new Error(`${label} 的 component 必须是 game、voice、launcher 或 other`);
    }
    if (!PC_PACKAGE_TYPES.has(packageType)) {
      throw new Error(`${label} 的 package_type 无效`);
    }
    if (!PC_DELIVERY_MODES.has(deliveryMode)) {
      throw new Error(`${label} 的 delivery_mode 必须是 direct、archive 或 file_manifest`);
    }
    if (!Number.isInteger(size) || size < 0) {
      throw new Error(`${label} 的 size 必须是非负整数`);
    }
    if (decompressedSize !== undefined && decompressedSize !== null && (!Number.isInteger(Number(decompressedSize)) || Number(decompressedSize) < 0)) {
      throw new Error(`${label} 的 decompressed_size 必须是非负整数`);
    }
    if ((checksumType && !checksumValue) || (!checksumType && checksumValue)) {
      throw new Error(`${label} 的 checksum_type 和 checksum_value 必须同时填写`);
    }
    if (checksumType && !new Set(["md5", "sha256", "crc64"]).has(checksumType)) {
      throw new Error(`${label} 的 checksum_type 无效`);
    }
    if (artifact.kind === "patch") {
      if (packageType !== "differential" || !routeFrom || !routeTo) {
        throw new Error(`${label} 为 patch 时必须使用 differential 并填写 route_from、route_to`);
      }
    } else {
      if (packageType === "differential") {
        throw new Error(`${label} 的 differential 资源必须使用 patch kind`);
      }
      if (routeFrom || routeTo) {
        throw new Error(`${label} 只有 patch 资源允许填写 route_from、route_to`);
      }
    }
    if (packageType === "segment" && (!Number.isInteger(part) || part < 1)) {
      throw new Error(`${label} 的 segment part 必须是正整数`);
    }
    if (packageType !== "segment" && part !== 1) {
      throw new Error(`${label} 只有 segment 资源允许使用非 1 的 part`);
    }
    if (language && component !== "voice") {
      throw new Error(`${label} 只有 voice 资源允许填写 language`);
    }

    const manifest = attributes.manifest;
    if (manifest !== undefined) {
      if (deliveryMode !== "file_manifest" || !isPlainObject(manifest)) {
        throw new Error(`${label} 的 manifest 必须是 file_manifest 使用的 JSON 对象`);
      }
      if (typeof manifest.path !== "string" || !manifest.path || manifest.path.includes("\\") || manifest.path.includes("\x00") || manifest.path.includes(":") || manifest.path.startsWith("/") || manifest.path.split("/").some((partName) => !partName || partName === "." || partName === "..")) {
        throw new Error(`${label} 的 manifest.path 必须是安全的相对 POSIX 路径`);
      }
      const manifestKeys = Object.keys(manifest);
      if (manifestKeys.some((key) => key !== "path" && key !== "base_urls")) {
        throw new Error(`${label} 的 manifest 只允许 path 和 base_urls`);
      }
      if (manifest.base_urls !== undefined) {
        if (!Array.isArray(manifest.base_urls)) {
          throw new Error(`${label} 的 manifest.base_urls 必须是数组`);
        }
        for (const baseUrl of manifest.base_urls) {
          if (!isPlainObject(baseUrl) || typeof baseUrl.url !== "string" || !/^https?:\/\/[^\s]+$/i.test(baseUrl.url) || typeof baseUrl.provider !== "string" || !baseUrl.provider.trim() || typeof baseUrl.source_kind !== "string" || !baseUrl.source_kind.trim() || typeof baseUrl.priority !== "number" || !Number.isInteger(baseUrl.priority) || baseUrl.priority < 0) {
            throw new Error(`${label} 的 manifest.base_urls 项必须包含有效的 url、provider、source_kind、priority`);
          }
        }
      }
    }
    if (deliveryMode === "file_manifest" && (!isPlainObject(manifest) || typeof manifest.path !== "string" || !manifest.path)) {
      throw new Error(`${label} 使用 file_manifest 时必须填写 manifest.path`);
    }

    const source = attributes.source;
    if (source !== undefined) {
      if (!isPlainObject(source) || Object.keys(source).some((key) => !COMPACT_SOURCE_KEYS.has(key))) {
        throw new Error(`${label} 的 source 必须是 compact provenance JSON 对象`);
      }
      if (source.source_kind !== undefined && !COMPACT_SOURCE_KINDS.has(String(source.source_kind))) {
        throw new Error(`${label} 的 source_kind 无效`);
      }
      for (const [key, value] of Object.entries(source)) {
        if (key !== "source_kind" && value !== null && (typeof value !== "string" || !value.trim())) {
          throw new Error(`${label} 的 source.${key} 必须是非空字符串或 null`);
        }
      }
    }

    const priorities = new Set<number>();
    if (!artifact.urls.length) {
      throw new Error(`${label} 至少需要一条 URL`);
    }
    for (const url of artifact.urls) {
      let parsedUrl: URL;
      try {
        parsedUrl = new URL(url.url);
      } catch {
        throw new Error(`${label} 包含无效 URL`);
      }
      if (!/^https?:$/i.test(parsedUrl.protocol) || !parsedUrl.hostname || parsedUrl.username || parsedUrl.password || parsedUrl.hash || /[\u0000-\u001f\u007f]/.test(url.url)) {
        throw new Error(`${label} 包含无效 URL`);
      }
      if (!Number.isInteger(url.priority) || url.priority < 0 || priorities.has(url.priority)) {
        throw new Error(`${label} 的 URL priority 必须是互不重复的非负整数`);
      }
      if (!url.source_kind.trim()) {
        throw new Error(`${label} 的 URL source_kind 不能为空`);
      }
      priorities.add(url.priority);
    }
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
    kind: selectedDomainUsesPcEditor.value ? "package" : "file",
    name: "",
    part: nextPart,
    size: 0,
    component: "game",
    package_type: selectedDomainUsesPcEditor.value ? "segment" : "",
    delivery_mode: selectedDomainUsesPcEditor.value ? "direct" : "",
    language: "",
    route_from: "",
    route_to: "",
    decompressed_size: null,
    manifestJson: "",
    sourceJson: "",
    checksum_type: "",
    checksum_value: "",
    attributesJson: "{}",
    urls: [{ url: "", priority: 0, source_kind: "official" }],
  });
  syncArtifactsToJson();
}

function removeArtifactItem(index: number): void {
  if (editableDraft.value.artifacts.length <= 1) {
    error.value = "版本必须包含至少一个资源文件 (Artifact)。";
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

function applyArtifactFilenameFromUrl(art: EditableArtifactDraft, rawUrl: string, force = false): boolean {
  const extracted = extractFilenameFromUrl(rawUrl);
  if (!extracted || !extracted.includes(".")) return false;

  const currentName = (art.name || "").trim();
  const isDefaultOrEmpty =
    !currentName ||
    /^package(\.part\d+)?\.(zip|bin|apk|dat)$/i.test(currentName) ||
    currentName === "未命名文件";
  if (force || isDefaultOrEmpty) art.name = extracted;
  if (extracted.toLowerCase().endsWith(".apk") && (art.kind === "file" || !art.kind)) {
    art.kind = "apk";
  }
  return true;
}

function handleArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
  applyArtifactFilenameFromUrl(art, newUrl);
  syncArtifactsToJson();
}

function forceExtractArtifactName(art: EditableArtifactDraft): void {
  const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
  if (applyArtifactFilenameFromUrl(art, firstUrl, true)) syncArtifactsToJson();
}

function switchArtifactsMode(mode: "visual" | "json"): void {
  if (mode === "json") {
    syncArtifactsToJson();
    editableDraft.value.artifactsMode = "json";
  } else {
    try {
      const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
      if (!Array.isArray(parsed)) throw new Error("Artifacts JSON 必须是数组");
      editableDraft.value.artifacts = parsed.map(artifactDraftFromPayload);
      editableDraft.value.artifactsMode = "visual";
    } catch (err) {
      error.value = err instanceof Error ? `切换失败: ${err.message}` : "JSON 解析失败";
    }
  }
}

function syncArtifactsToJson(): void {
  try {
    const payload = buildArtifactsPayload();
    editableDraft.value.artifactsJson = JSON.stringify(payload, null, 2);
  } catch {
    // Keep the visual form editable while a nested JSON field is temporarily invalid.
  }
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
  let currentArtifactsStr = "";
  try {
    currentArtifactsStr = normalizeArtifactsForComparison(buildArtifactsPayload());
  } catch {
    return true;
  }
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

interface VersionDraft {
  version: string;
  channel: string;
  version_code: number | null;
  file_created_at_override: string;
  is_visible: boolean;
  checksum_etag: string;
  checksum_crc64: string;
  checksum_md5: string;
  artifacts: EditableArtifactDraft[];
  artifactsJson: string;
  artifactsMode: "visual" | "json";
}

function defaultCreateDraft(): VersionDraft {
  const initialArtifacts: EditableArtifactDraft[] = [
    {
      kind: "apk",
      name: "",
      part: 1,
      size: 0,
      component: "game",
      package_type: "",
      delivery_mode: "",
      language: "",
      route_from: "",
      route_to: "",
      decompressed_size: null,
      manifestJson: "",
      sourceJson: "",
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
    file_created_at_override: "",
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

const createDraft = ref<VersionDraft>(defaultCreateDraft());

const isCreateMode = computed(() => contentSubTab.value === "create");

const versionDraft = computed(() => (isCreateMode.value ? createDraft.value : editableDraft.value));

const showApkFileCard = computed(
  () => Boolean(versionDraft.value.artifacts[0]) && (isCreateMode.value || selectedDomainSupportsCreateVersion.value),
);

const fileTimeRaw = computed(() => versionDraft.value.file_created_at_override.trim());

const fileTimeInputValue = computed(() => isoToLocalInput(fileTimeRaw.value));

const fileTimeLabel = computed(() => formatFileTimeLabel(fileTimeRaw.value));

const fileTimeUnparsable = computed(() => Boolean(fileTimeRaw.value) && !fileTimeLabel.value);

function onFileTimeInput(event: Event): void {
  const input = event.target as HTMLInputElement;
  versionDraft.value.file_created_at_override = localInputToIso(input.value);
}

async function submitVersionForm(): Promise<void> {
  if (isCreateMode.value) {
    await addVersion();
    return;
  }
  await saveEditableVersion();
}


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

const domainGameFilter = ref<string>("all");

const versionFilterState = ref<"all" | "unavailable" | "unknown">("all");

async function toggleVersionFilter(target: "unavailable" | "unknown"): Promise<void> {
  if (isEditableDirty.value) {
    const confirmed = await askConfirm(
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
    const confirmed = await askConfirm(
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
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  return unavailableCount > 0 && availableCount === 0 && canonicalCount === 0;
}

function isVersionUnknown(item: VersionSummary): boolean {
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  return availableCount === 0 && canonicalCount === 0 && unavailableCount === 0;
}

function versionAvailabilityCounts(item: VersionSummary): {
  available: number;
  unavailable: number;
  unknown: number;
  canonical: number;
} {
  const summary = item.availability_states || {};
  const hasSummary = Object.values(summary).some((value) => Number(value) > 0);
  if (hasSummary) {
    return {
      available: Number(summary.available) || 0,
      unavailable: Number(summary.unavailable) || 0,
      unknown: Number(summary.unknown) || 0,
      canonical: Number(summary.canonical) || 0,
    };
  }

  return Object.values(item.artifact_kinds || {}).reduce(
    (counts, artifact) => {
      const states = artifact.availability_states || {};
      counts.available += Number(states.available) || 0;
      counts.unavailable += Number(states.unavailable) || 0;
      counts.unknown += Number(states.unknown) || 0;
      counts.canonical += Number(states.canonical) || 0;
      return counts;
    },
    { available: 0, unavailable: 0, unknown: 0, canonical: 0 },
  );
}

function versionHealthClass(item: VersionSummary): "available" | "unavailable" | "unknown" {
  if (isVersionUnavailable(item)) return "unavailable";
  if (isVersionUnknown(item)) return "unknown";
  return "available";
}

function versionHealthTitle(item: VersionSummary): string {
  if (isVersionUnavailable(item)) return "链接不可用";
  if (isVersionUnknown(item)) return "尚未探活";
  return "链接可用";
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

watch(
  () => selectedDomainSupportsCreateVersion.value,
  (supportsCreate) => {
    if (!supportsCreate && contentSubTab.value === "create") {
      contentSubTab.value = "edit";
    }
  },
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
    success.value = "数据已全部刷新至最新状态。";
  });
}

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

async function loadProbeStatus(): Promise<void> {
  try {
    probeStatus.value = await adminApi.probeStatus(token.value.trim());
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
  }
}

async function loadProbeSchedulerStatus(): Promise<void> {
  try {
    probeSchedulerStatus.value = await adminApi.probeScheduler(token.value.trim());
  } catch (reason) {
    probeSchedulerStatus.value = null;
    if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
  }
}

function startProbePolling(): void {
  stopProbePolling();
  probePollTimer = window.setInterval(async () => {
    if (!authenticated.value || tab.value !== "probe") return;
    await loadProbeStatus();
    await loadProbeSchedulerStatus();
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
  tab.value = "probe";
  await loadProbeStatus();
  await loadProbeSchedulerStatus();
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
  const confirmed = await askConfirm("确定要保存并更新下载链接探活策略吗？");
  if (!confirmed) return;
  await withLoading(async (signal) => {
    probeSchedule.value = await adminApi.saveProbeSchedule(probeSchedule.value, token.value, signal);
    await loadProbeSchedulerStatus();
    success.value = "定时探活计划已保存。";
  });
}

// --- 运维操作控制台 (start -> status polling -> cancel) ---
const opAction = ref<"both" | "discover">("both");
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
const OP_TERMINAL_LOG_LIMIT = 256;
const opLogOffset = ref(0);
const opTerminalHidden = ref(false);
let operationPollTimer: number | null = null;
let operationPollBusy = false;

type TerminalLogTone = "success" | "danger" | "warning" | "info";
type TerminalLogEntry = {
  id: number;
  raw: string;
  phase: string;
  target: string;
  outcome: string;
  tone: TerminalLogTone;
  detail: string;
};

const terminalLogSource = computed(() => {
  if (opTerminalLogs.value.length) return opTerminalLogs.value;
  const syncTail = syncRunStatus.value?.result?.log_tail;
  if (syncTail) return syncTail.split(/\r?\n/).filter(Boolean);
  return (probeStatus.value?.log || []).slice(-150);
});

function terminalLogTone(outcome: string): TerminalLogTone {
  if (/失败|失效|错误|异常|取消/i.test(outcome)) return "danger";
  if (/未知|未判定|跳过|等待/i.test(outcome)) return "warning";
  if (/成功|可用|完成|正常/i.test(outcome)) return "success";
  return "info";
}

function parseTerminalLog(raw: string, id: number): TerminalLogEntry {
  const match = raw.match(/^\[([^\]]+)\]\s+(.+?)\s+(可用|不可用|未判定|未知|失败(?::.*)?|成功|跳过.*)$/u);
  if (!match) {
    return { id, raw, phase: "系统", target: "运维任务", outcome: "记录", tone: "info", detail: raw };
  }
  const [scope, target, outcome] = match.slice(1);
  const [phase, platform] = scope.split("/");
  return {
    id,
    raw,
    phase: phase === "probe" ? "探活" : phase === "discover" ? "发现" : phase,
    target: `${target}${platform ? ` · ${platform}` : ""}`,
    outcome: outcome.startsWith("失败:") ? "失败" : outcome,
    tone: terminalLogTone(outcome),
    detail: outcome.startsWith("失败:") ? outcome.slice(3) : "",
  };
}

const terminalLogEntries = computed<TerminalLogEntry[]>(() =>
  terminalLogSource.value.map((line, index) => parseTerminalLog(line, index + 1)),
);

const terminalLogStats = computed(() => terminalLogEntries.value.reduce(
  (stats, entry) => {
    stats.total += 1;
    if (entry.tone === "success") stats.success += 1;
    if (entry.tone === "danger") stats.danger += 1;
    if (entry.tone === "warning") stats.warning += 1;
    return stats;
  },
  { total: 0, success: 0, danger: 0, warning: 0 },
));

const terminalStatusText = computed(() => {
  if (opJob.value?.status === "cancelling") return "正在取消";
  if (opRunning.value) return "执行中";
  if (opJob.value?.status === "finished") return "已完成";
  if (opJob.value?.status === "failed") return "执行失败";
  if (opJob.value?.status === "cancelled") return "已取消";
  if (probeStatus.value?.status === "running") return "探活中";
  return terminalLogEntries.value.length ? "最近记录" : "等待任务";
});

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
    return items.filter(isProbeUnknownItem);
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

const opCurrentGameLabel = computed(() => {
  const gameId = opJob.value?.current?.game_id;
  return gameId ? gameDisplayName(gameId) : "";
});

function stopOperationPolling(): void {
  if (operationPollTimer !== null) {
    window.clearInterval(operationPollTimer);
    operationPollTimer = null;
  }
}

function notifyAvailabilityInvalidated(jobId: string): void {
  if (lastInvalidatedOperationJobId === jobId) return;
  lastInvalidatedOperationJobId = jobId;
  window.dispatchEvent(new CustomEvent(AVAILABILITY_INVALIDATION_EVENT, { detail: { jobId } }));
  try {
    localStorage.setItem(AVAILABILITY_INVALIDATION_STORAGE_KEY, `${jobId}:${Date.now()}`);
  } catch {
    // Storage unavailable; the same-tab CustomEvent has already fired.
  }
}

function nextVersionProbeInvalidationId(domainId: string, version: string): string {
  availabilityInvalidationSequence += 1;
  return `version-probe:${domainId}:${version}:${Date.now()}:${availabilityInvalidationSequence}`;
}

async function applyOperationJob(job: AdminOperationJob, isInitialRestore = false, incremental = false): Promise<void> {
  const sameJob = opJob.value?.job_id === job.job_id;
  opJob.value = job;
  const restoredScope = restoredOperationScope(job.scope ?? job.result?.scope);
  if (restoredScope) opPlatformScope.value = restoredScope;
  opRunning.value = job.status === "running" || job.status === "cancelling";
  if (incremental && sameJob) {
    opTerminalLogs.value = [...opTerminalLogs.value, ...(job.logs || [])].slice(-OP_TERMINAL_LOG_LIMIT);
    opLogOffset.value = job.log_total ?? (opLogOffset.value + (job.logs || []).length);
    if (job.logs?.length) opTerminalHidden.value = false;
  } else {
    opTerminalLogs.value = (job.logs || []).slice(-OP_TERMINAL_LOG_LIMIT);
    opLogOffset.value = job.log_total ?? ((job.log_offset ?? 0) + (job.logs?.length || 0));
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
      if (job.actions.includes("probe")) notifyAvailabilityInvalidated(job.job_id);
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
  if (opTerminalLogs.value.length > OP_TERMINAL_LOG_LIMIT) {
    opTerminalLogs.value = opTerminalLogs.value.slice(-OP_TERMINAL_LOG_LIMIT);
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
    opAction.value === "discover" ? ["discover"] : ["discover", "probe"];

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
    opAction.value === "discover"
      ? "【仅查找新版本 (discover)】"
      : "【查找新版本 + 探活全量 (discover + probe)】";
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

  const confirmed = await askConfirm(
    `确定要启动 ${actionText} 操作吗？\n目标范围：${scopeText}\n数据类型：${platformText}\n启动后可查看实时进度，也可以取消未开始的任务。`,
    { title: "启动运维任务", confirmLabel: "启动" },
  );
  if (!confirmed) return;

  opRunning.value = true;
  opResult.value = null;
  opExecutionTime.value = null;
  probeTableFilter.value = "all";
  error.value = "";
  success.value = "";

  const timeStr = new Date().toLocaleTimeString();
  appendOpLog(`[${timeStr}] 启动运维操作 POST /api/v1/admin/operations/start`);
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
  if (
    !jobId ||
    !(await askConfirm("确定要取消当前运维任务吗？已完成的数据会保留。", {
      title: "取消运维任务",
      confirmLabel: "取消任务",
    }))
  )
    return;
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

async function saveSyncSchedule(): Promise<void> {
  const validTimes = (syncSchedule.value?.times || [])
    .map((item) => (item || "").trim())
    .filter(Boolean);

  if (syncSchedule.value.enabled && validTimes.length === 0) {
    error.value = "请至少配置一个有效的每日采集时间点（例如 04:45）";
    return;
  }

  const confirmed = await askConfirm(`确定要保存每日采集计划（时间点: ${validTimes.join(", ")}）吗？`);
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
    success.value = `采集计划参数已保存。${externalScheduleNotice}`;
  });
}

function openGames(): void {
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
  if (!adminUiCapabilities.catalogMutations) return;
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

function cancelCreateGame(): void {
  if (!newGame.value) return;
  newGame.value = false;
  const target = selectedGameId.value || catalog.value.games[0]?.id;
  if (target) {
    selectGame(target);
  } else {
    gameDraft.value = {
      id: "",
      name: "",
      sub_name: "",
      platform: "PC",
      icon_source: "",
      is_enabled: true,
      sort_order: 0,
    };
  }
}

function preventEnterSubmit(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && target.tagName === "INPUT") {
    event.preventDefault();
  }
}

async function saveGame(): Promise<void> {
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启游戏目录写入能力。";
    return;
  }
  const actionText = newGame.value
    ? `确定要创建新游戏【${gameDraft.value.name || gameDraft.value.id}】吗？`
    : `确定要保存游戏【${gameDraft.value.name || gameDraft.value.id}】的配置修改吗？`;
  if (!(await askConfirm(actionText, {
    title: newGame.value ? "创建游戏入口" : "保存游戏配置",
    confirmLabel: newGame.value ? "创建" : "保存",
  })))
    return;

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
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启游戏目录写入能力。";
    return;
  }
  if (
    !newGame.value &&
    !(await askConfirm(
      `确定要彻底删除空游戏【${gameDraft.value.name || gameDraft.value.id}】吗？仅空游戏可删除，此操作不可撤销。`,
      { title: "删除空游戏", confirmLabel: "永久删除", tone: "danger" },
    ))
  )
    return;
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
  if (!adminUiCapabilities.catalogMutations) return;
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

function cancelCreateDomain(): void {
  if (!newDomain.value) return;
  newDomain.value = false;
  const target = selectedDomainId.value
    || catalog.value.domains.find((item) => item.id === selectedDomainId.value)?.id
    || catalog.value.domains[0]?.id;
  if (target) {
    selectDomain(target);
    return;
  }
  domainDraft.value = {
    id: "",
    game_id: selectedGameId.value || catalog.value.games[0]?.id || "",
    kind: "packages",
    platform: "Windows",
    capabilities: "packages",
    adapter: "generic",
    is_enabled: true,
    sort_order: 0,
  };
}

function openDomains(): void {
  tab.value = "domains";
  stopProbePolling();
  const target = catalog.value.domains.find((item) => item.id === selectedDomainId.value) || catalog.value.domains[0];
  if (target) selectDomain(target.id);
  else startDomain();
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

function setDomainPlatform(platform: string): void {
  domainDraft.value.platform = platform;
}

function setDomainAdapter(adapter: string): void {
  domainDraft.value.adapter = adapter;
}

function adjustDomainSort(delta: number): void {
  const current = Number(domainDraft.value.sort_order) || 0;
  domainDraft.value.sort_order = Math.max(0, current + delta);
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
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启数据模块写入能力。";
    return;
  }
  const actionText = newDomain.value
    ? `确定要创建新数据模块【${domainDraft.value.id}】吗？`
    : `确定要保存数据模块【${domainDraft.value.id}】的配置修改吗？`;
  if (!(await askConfirm(actionText, {
    title: newDomain.value ? "新建数据模块" : "保存模块配置",
    confirmLabel: newDomain.value ? "新建" : "保存",
  })))
    return;

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
  if (!adminUiCapabilities.catalogMutations) {
    error.value = "当前管理会话未开启数据模块写入能力。";
    return;
  }
  if (
    !(await askConfirm(
      `确定要彻底删除空模块【${domainDraft.value.id}】吗？仅没有版本和候选记录的空模块可删除，此操作不可撤销。`,
      { title: "删除空模块", confirmLabel: "永久删除", tone: "danger" },
    ))
  )
    return;
  await withLoading(async (signal) => {
    await adminApi.deleteDomain(domainDraft.value.id, token.value, signal);
    await loadCatalog(signal);
    success.value = "空模块已删除。";
  });
}

function pcArtifactTitle(artifact: EditableArtifactDraft, index: number): string {
  return artifact.name.trim() || `未命名资源 #${index + 1}`;
}

function pcArtifactSummaryTags(artifact: EditableArtifactDraft): string[] {
  const tags = [
    artifact.kind || "package",
    `part ${Number(artifact.part) || 1}`,
    formatBytes(artifact.size),
    `${(artifact.urls || []).filter((item) => item.url.trim()).length} URL`,
  ];
  if (artifact.route_from || artifact.route_to) {
    tags.push(`${artifact.route_from || "?"} -> ${artifact.route_to || "?"}`);
  }
  return tags;
}

async function loadEditableVersion(domainId = selectedDomainId.value, version = selectedVersion.value): Promise<void> {
  const domain = catalog.value.domains.find((item) => item.id === domainId);
  const isAndroid = supportsApkVersionEditor(domain?.platform);
  const isPc = supportsPcVersionEditor(domain);
  if (!isAndroid && !isPc) {
    editableLoaded.value = false;
    return;
  }
  if (!domainId || !version) {
    editableLoaded.value = false;
    return;
  }
  editableLoading.value = true;
  try {
    const data = await adminApi.editableVersion(domainId, version, token.value.trim());
    const editableArtifactsPayload = (data.artifacts || []).map((art) => ({
      artifact_id: art.artifact_id,
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
    }));
    const rawArtifacts = (data.artifacts || []).map((art, idx) => artifactDraftFromPayload({
      artifact_id: art.artifact_id,
      kind: art.kind || "file",
      name: art.name || "",
      part: art.part ?? (idx + 1),
      size: art.size ?? 0,
      checksum_type: art.checksum_type || "",
      checksum_value: art.checksum_value || "",
      attributes: art.attributes || {},
      urls: art.urls || [],
    }, idx));

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
      version: "",
      channel: typeof attrs.channel === "string" ? attrs.channel : "official",
      version_code: typeof attrs.version_code === "number" ? attrs.version_code : null,
      is_visible: data.is_visible ?? true,
      file_created_at_override: data.file_created_at_override || "",
      checksum_etag: String(artAttrs.etag || ""),
      checksum_crc64: String(artAttrs.crc64 || (firstArt?.checksum_type === "crc64" ? firstArt.checksum_value : "")),
      checksum_md5: String(artAttrs.md5 || (firstArt?.checksum_type === "md5" ? firstArt.checksum_value : "")),
      artifacts: rawArtifacts,
      artifactsJson: JSON.stringify(editableArtifactsPayload, null, 2),
      artifactsMode: "visual",
    };

    // 用草稿回写后的形态作为基线：视觉编辑器会补默认属性、清理空值，
    // 直接拿接口原始 payload 当基线会让表单一打开就显示“未保存修改”。
    let initialArtifactsStr = "";
    try {
      initialArtifactsStr = normalizeArtifactsForComparison(buildArtifactsPayload());
    } catch {
      initialArtifactsStr = normalizeArtifactsForComparison(editableArtifactsPayload);
    }

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
    const confirmed = await askConfirm(
      `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n切换到版本 ${version} 将丢弃未保存的修改，是否确定继续？`,
    );
    if (!confirmed) return;
  }
  selectedVersion.value = version;
  ensureVersionExpanded(version);
  await loadEditableVersion(selectedDomainId.value, version);
  scrollToActiveVersion();
}

async function discardChanges(): Promise<void> {
  if (!(await askConfirm("确定要放弃所有未保存的修改并还原为当前服务端配置吗？", {
    title: "放弃未保存的修改",
    confirmLabel: "放弃修改",
  })))
    return;
  await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
  success.value = "已放弃修改，表单已还原。";
}

async function saveEditableVersion(): Promise<void> {
  if (!selectedDomainSupportsManualVersion.value) {
    error.value = "当前模块暂不支持手工编辑。";
    return;
  }
  if (!selectedDomainId.value || !selectedVersion.value || !isEditableDirty.value) return;

  let artifactsPayload: ManualArtifactPayload[];
  try {
    artifactsPayload = buildArtifactsPayload();
  } catch (err) {
    error.value = err instanceof Error ? `Artifacts JSON 格式错误: ${err.message}` : "Artifacts 配置无效";
    return;
  }
  if (!artifactsPayload.length) {
    error.value = "Artifacts 至少需要包含一个资源文件";
    return;
  }

  const payload: AdminEditableVersionPayload = {
    attributes: {
      channel: editableDraft.value.channel.trim() || "official",
      version_code:
        editableDraft.value.version_code !== null &&
        editableDraft.value.version_code !== undefined &&
        String(editableDraft.value.version_code).trim() !== ""
          ? Number(editableDraft.value.version_code)
          : null,
    },
    artifacts: artifactsPayload,
  };

  const willProbe = selectedDomainSupportsCreateVersion.value && isUrlChanged.value;
  if (selectedDomainSupportsCreateVersion.value) {
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
    payload.file_created_at_override = editableDraft.value.file_created_at_override.trim() || null;
    payload.file_path = mainArt.name.trim();
    payload.artifacts = [mainArt];
  } else if (selectedDomainUsesPcEditor.value) {
    try {
      validatePcArtifacts(artifactsPayload);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "PC artifact 配置无效";
      return;
    }
    payload.file_created_at_override = editableDraft.value.file_created_at_override.trim() || null;
  }

  const actionPrompt = willProbe
    ? `确定要保存对版本【${selectedVersion.value}】的修改并立即向官方源探活吗？`
    : `确定要保存对版本【${selectedVersion.value}】的修改吗？`;
  const confirmed = await askConfirm(actionPrompt, {
    title: "保存版本修改",
    confirmLabel: willProbe ? "保存并探活" : "保存",
  });
  if (!confirmed) return;

  await withLoading(async (signal) => {
    await adminApi.updateEditableVersion(
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

    let probeCompleted = false;
    if (willProbe) {
      try {
        await adminApi.probeVersion(selectedDomainId.value, selectedVersion.value, token.value, signal);
        probeCompleted = true;
        notifyAvailabilityInvalidated(nextVersionProbeInvalidationId(selectedDomainId.value, selectedVersion.value));
      } catch {
        // 探活失败不阻塞保存
      }
    }

    const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
    versions.value = verRes.items;
    await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
    success.value = willProbe
      ? probeCompleted
        ? `版本 ${selectedVersion.value} 修改已保存并已完成探活！`
        : `版本 ${selectedVersion.value} 修改已保存，但探活失败，请重试。`
      : `版本 ${selectedVersion.value} 的配置修改已保存成功。`;
  });
}

function openTab(next: Tab): void {
  if (next === "games") {
    openGames();
    return;
  }
  if (next === "domains") {
    openDomains();
    return;
  }
  if (next === "content") {
    void openContent();
    return;
  }
  void openProbe();
}

async function openContent(id = selectedDomainId.value): Promise<void> {
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
  if (
    !(await askConfirm(`确定要将版本【${selectedVersion.value}】切换为【${actionText}】状态吗？`, {
      title: "切换版本可见性",
      confirmLabel: actionText,
    }))
  )
    return;

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
  const confirmed = await askConfirm(
    `确定要彻底删除版本【${ver}】吗？\n\n此操作将永久清除该版本的所有 Revision 快照、资源文件及下载链接，不可撤销。`,
    { title: "删除版本", confirmLabel: "永久删除", tone: "danger" },
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
    component: art.component,
    package_type: "",
    delivery_mode: "",
    language: art.language,
    route_from: "",
    route_to: "",
    decompressed_size: art.decompressed_size,
    manifestJson: "",
    sourceJson: "",
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
    file_created_at_override: editableDraft.value.file_created_at_override || "",
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

function syncArtifactsJsonForActiveDraft(): void {
  if (isCreateMode.value) {
    createDraft.value.artifactsJson = JSON.stringify(buildCreateArtifactsPayload(), null, 2);
    return;
  }
  syncArtifactsToJson();
}

function handleActiveArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
  applyArtifactFilenameFromUrl(art, newUrl);
  syncArtifactsJsonForActiveDraft();
}

function forceExtractActiveArtifactName(art: EditableArtifactDraft): void {
  const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
  if (applyArtifactFilenameFromUrl(art, firstUrl, true)) syncArtifactsJsonForActiveDraft();
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
    return {
      kind: art.kind,
      name: art.name.trim(),
      part: art.part,
      size: Number(art.size) || 0,
      checksum_type: art.checksum_type.trim() || undefined,
      checksum_value: art.checksum_value.trim().toLowerCase() || undefined,
      attributes: buildVisualArtifactAttributes(art),
      urls: normalizeArtifactUrls(art.urls, true, false, (value) => Number(value) || 0),
    };
  });
}

async function addVersion(): Promise<void> {
  if (!selectedDomainSupportsManualVersion.value) {
    error.value = "当前手工录入只支持单 APK 的 Android 版本；PC 版本请通过官方采集流程维护。";
    return;
  }
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
  if (createDraft.value.file_created_at_override?.trim()) {
    attributes.file_created_at = createDraft.value.file_created_at_override.trim();
  }

  const confirmed = await askConfirm(
    `确定要为【${selectedDomainGameName.value || selectedDomainId.value}】录入新版本【${ver}】吗？`,
    { title: "录入新版本", confirmLabel: "录入" },
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

      success.value = manualVersionSavedMessage(ver, result.probe_error);
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
  const confirmed = await askConfirm(
    `确定要向官方源发起对版本【${ver}】的实时探活并持久化保存吗？表单中未保存的修改不会被一并提交。`,
    { title: "实时探活", confirmLabel: "开始探活" },
  );
  if (!confirmed) return;

  await withLoading(async (signal) => {
    try {
      await adminApi.probeVersion(selectedDomainId.value, ver, token.value, signal);
      notifyAvailabilityInvalidated(nextVersionProbeInvalidationId(selectedDomainId.value, ver));
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
});
</script>

<template>
  <div class="admin-app" :class="{ 'is-unauthenticated': !authenticated }">
    <AdminRail
      v-if="authenticated"
      :active-tab="tab"
      @select="openTab"
      @logout="logout"
    />

    <!-- 主工作区 Main Dashboard -->
    <main class="admin-main">
      <AdminLoginView
        v-if="!authenticated"
        v-model="token"
        :error="error"
        :loading="loading"
        @submit="login"
        @back="router.push('/')"
      />

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
        <AdminGameCatalog
          v-if="tab === 'games'"
          :games="catalog.games"
          :selected-game-id="selectedGameId"
          :new-game="newGame"
          :game-draft="gameDraft"
          :game-domains-count="currentGameDomainCount"
          :loading="loading"
          :catalog-mutations="adminUiCapabilities.catalogMutations"
          :search-query="gameSearchQuery"
          :resolve-game-icon="resolveGameIcon"
          :use-fallback-icon="useFallbackIcon"
          @select-game="selectGame"
          @start-game="startGame"
          @cancel-create="cancelCreateGame"
          @save-game="saveGame"
          @remove-game="removeGame"
          @revert-game="revertGameDraft"
          @adjust-sort="adjustGameSort"
          @set-platform="setGamePlatform"
          @set-icon-preset="setGameIconPreset"
          @open-domains="openDomainsForGame"
          @copy-text="copyText"
          @update:game-draft="gameDraft = $event"
          @update:search-query="gameSearchQuery = $event"
        />

        <!-- 模块 2：数据模块管理 (Domains Master-Detail) -->
        <AdminDomainCatalog
          v-if="tab === 'domains'"
          :domains="catalog.domains"
          :games="catalog.games"
          :selected-domain-id="selectedDomainId"
          :new-domain="newDomain"
          :domain-draft="domainDraft"
          :loading="loading"
          :catalog-mutations="adminUiCapabilities.catalogMutations"
          :search-query="domainSearchQuery"
          :game-filter="domainGameFilter"
          :resolve-game-icon="resolveGameIcon"
          :use-fallback-icon="useFallbackIcon"
          @select-domain="selectDomain"
          @start-domain="startDomain"
          @cancel-create="cancelCreateDomain"
          @save-domain="saveDomain"
          @remove-domain="removeDomain"
          @revert-domain="revertDomainDraft"
          @open-content="openContent"
          @copy-text="copyText"
          @set-kind="setDomainKind"
          @set-platform="setDomainPlatform"
          @set-adapter="setDomainAdapter"
          @adjust-sort="adjustDomainSort"
          @update:domain-draft="domainDraft = $event"
          @update:search-query="domainSearchQuery = $event"
          @update:game-filter="domainGameFilter = $event"
        />
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
                    <div v-else class="game-dropdown-icon fallback-icon"><AdminIcon name="game" /></div>
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
                        <div v-else class="option-game-icon fallback-icon"><AdminIcon name="game" /></div>
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
                              :class="versionHealthClass(entry.item)"
                              :title="versionHealthTitle(entry.item)"
                            ></span>
                            <strong class="version-item-title">{{ entry.item.version }}</strong>
                          </div>
                          <span v-if="!entry.item.is_visible" class="status-pill hidden">已隐藏</span>
                          <span v-else-if="isVersionUnknown(entry.item)" class="status-pill unknown">尚未探活</span>
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
                                  :class="versionHealthClass(subItem)"
                                  :title="versionHealthTitle(subItem)"
                                ></span>
                                <strong class="version-item-title">{{ subItem.version }}</strong>
                              </div>
                              <span v-if="!subItem.is_visible" class="status-pill hidden">已隐藏</span>
                              <span v-else-if="isVersionUnknown(subItem)" class="status-pill unknown">尚未探活</span>
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
            <div v-if="selectedDomainSupportsManualVersion" class="content-work-card">
              <!-- 子功能切换 Tab -->
              <div class="content-sub-tabs">
                <button
                  class="sub-tab-btn"
                  :class="{ active: contentSubTab === 'edit' }"
                  type="button"
                  @click="contentSubTab = 'edit'"
                >
                  <span>编辑版本</span>
                </button>
                <button
                  v-if="selectedDomainSupportsCreateVersion"
                  class="sub-tab-btn"
                  :class="{ active: contentSubTab === 'create' }"
                  type="button"
                  @click="contentSubTab = 'create'"
                >
                  <span>新建版本</span>
                </button>
              </div>

              <!-- 版本工作台：编辑与新建共用同一套字段与资源编辑器 -->
              <form
                class="version-edit-form"
                :class="{ 'version-create-form': isCreateMode }"
                novalidate
                @keydown.enter="preventEnterSubmit"
                @submit.prevent="submitVersionForm"
              >
                <!-- 顶部版本状态栏 -->
                <div class="version-status-topbar">
                  <div class="version-header-meta">
                    <div class="version-title-row">
                      <template v-if="isCreateMode">
                        <h2>新建版本 · {{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }}</h2>
                        <span class="status-pill success">新建模式</span>
                      </template>
                      <template v-else>
                        <h2>{{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }} <span class="divider">/</span> {{ selectedVersion || '未选择版本' }}</h2>
                        <span v-if="!editableDraft.is_visible" class="status-pill hidden">已隐藏</span>
                      </template>
                    </div>
                  </div>

                  <div class="version-header-actions">
                    <template v-if="isCreateMode">
                      <button
                        v-if="selectedVersion && editableLoaded"
                        class="admin-btn secondary"
                        type="button"
                        @click="copyCurrentVersionToCreateDraft"
                      >
                        <span>复制当前 ({{ selectedVersion }}) 为模板</span>
                      </button>
                      <button
                        class="admin-btn secondary"
                        type="button"
                        @click="resetCreateDraft"
                      >
                        <span>重置</span>
                      </button>
                    </template>
                    <template v-else>
                      <button
                        type="button"
                        class="admin-btn secondary"
                        :disabled="editableLoading || loading || !selectedVersion"
                        title="向官方源发起实时探活并持久化探活结果，不会保存当前表单草稿"
                        @click="probeCurrentVersion()"
                      >
                        <span>实时探活</span>
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
                              <span>{{ editableDraft.is_visible ? '隐藏此版本' : '恢复公开' }}</span>
                            </button>
                            <button
                              v-if="selectedDomainSupportsCreateVersion"
                              type="button"
                              class="more-dropdown-item"
                              @click="copyCurrentVersionToCreateDraft(); moreActionsOpen = false"
                            >
                              <span>复制为新版本模板</span>
                            </button>
                            <hr class="more-divider" />
                            <button
                              type="button"
                              class="more-dropdown-item danger"
                              @click="deleteCurrentVersion(); moreActionsOpen = false"
                            >
                              <span>删除此版本</span>
                            </button>
                          </div>
                        </transition>
                      </div>
                    </template>
                  </div>
                </div>

                <div v-if="!isCreateMode && !selectedVersion" class="admin-empty-state">
                  请先在左侧列表中选择一个目标版本。
                </div>

                <template v-else>
                  <!-- 链接健康条 (Health Banner - 紧凑低饱和)：仅编辑已有版本时展示 -->
                  <div
                    v-if="!isCreateMode"
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
                        重新探活
                      </button>
                    </div>
                  </div>
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
                          v-model="versionDraft.version"
                          class="admin-input"
                          placeholder="例如: 7.1.0"
                          required
                        />
                      </label>

                      <label class="admin-field">
                        <span class="field-label">渠道</span>
                        <input
                          v-model="versionDraft.channel"
                          class="admin-input"
                          placeholder="official / bilibili"
                          required
                        />
                      </label>

                      <label class="admin-field">
                        <span class="field-label">版本代码</span>
                        <input
                          v-model.number="versionDraft.version_code"
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
                            v-if="versionDraft.file_created_at_override"
                            class="field-mini-btn"
                            type="button"
                            title="清空后将由后端自动识别 URL 或 Last-Modified 时间"
                            @click="clearActiveFileTime"
                          >
                            清空
                          </button>
                        </div>
                        <input
                          class="admin-input"
                          type="datetime-local"
                          :value="fileTimeInputValue"
                          @input="onFileTimeInput"
                        />
                        <small v-if="fileTimeUnparsable" class="field-tip field-tip-warning">
                          无法识别当前值（{{ fileTimeRaw }}），请重新选择或清空。
                        </small>
                        <small v-else class="field-tip">
                          {{ fileTimeLabel ? `当前 ${fileTimeLabel}，按 UTC 保存` : '留空时按 URL / Last-Modified 自动识别' }}
                          · 来源：{{ getFileTimeSourceDescription(versionDraft.file_created_at_override, versionDraft.artifacts[0]?.urls[0]?.url) }}
                        </small>
                      </div>
                    </div>
                  </div>

                  <!-- APK 文件平铺卡片 -->
                  <div v-if="showApkFileCard" class="form-section-card apk-file-card">
                    <div class="section-card-title">APK 文件</div>

                    <div class="admin-field-grid">
                      <div class="admin-field">
                        <div class="field-header-row">
                          <span class="field-label">文件名</span>
                          <button
                            v-if="versionDraft.artifacts[0].urls[0]?.url"
                            class="field-mini-btn"
                            type="button"
                            title="根据当前 URL 自动解析并填入文件名"
                            @click="forceExtractActiveArtifactName(versionDraft.artifacts[0])"
                          >
                            根据 URL 填写文件名
                          </button>
                        </div>
                        <input
                          v-model="versionDraft.artifacts[0].name"
                          class="admin-input"
                          placeholder="例如: yuanshen_7.1.0.apk"
                          required
                          @input="syncArtifactsJsonForActiveDraft"
                        />
                      </div>

                      <label class="admin-field">
                        <span class="field-label">文件大小</span>
                        <input
                          v-model.number="versionDraft.artifacts[0].size"
                          class="admin-input"
                          type="number"
                          min="0"
                          placeholder="字节数"
                          @input="syncArtifactsJsonForActiveDraft"
                        />
                        <small class="field-tip">
                          当前换算：<strong>{{ formatBytes(versionDraft.artifacts[0].size) }}</strong>
                        </small>
                      </label>
                    </div>

                    <!-- URL 独占一行 -->
                    <div class="admin-field full-width url-line-field">
                      <span class="field-label">下载 URL</span>
                      <div class="url-input-action-row">
                        <input
                          v-model="versionDraft.artifacts[0].urls[0].url"
                          class="admin-input text-mono url-long-input"
                          placeholder="https://..."
                          required
                          @input="handleActiveArtifactUrlChange(versionDraft.artifacts[0], versionDraft.artifacts[0].urls[0].url)"
                        />
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="复制下载链接"
                          @click="copyUrl(versionDraft.artifacts[0].urls[0].url)"
                        >
                          复制
                        </button>
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="在新窗口打开"
                          @click="openUrl(versionDraft.artifacts[0].urls[0].url)"
                        >
                          ↗ 打开
                        </button>
                        <button
                          class="url-action-pill-btn"
                          type="button"
                          title="仅检查网络连通性，不修改或保存任何数据"
                          :disabled="urlProbeMap[versionDraft.artifacts[0].urls[0].url]?.loading"
                          @click="probeUrlItem(versionDraft.artifacts[0].urls[0].url)"
                        >
                          {{ urlProbeMap[versionDraft.artifacts[0].urls[0].url]?.loading ? '测试中…' : '测试 URL' }}
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
                        <span v-if="getChecksumSummaryText(versionDraft.checksum_etag, versionDraft.checksum_crc64, versionDraft.checksum_md5)" class="checksum-tag">
                          {{ getChecksumSummaryText(versionDraft.checksum_etag, versionDraft.checksum_crc64, versionDraft.checksum_md5) }}
                        </span>
                        <span v-else class="checksum-tag-empty">未配置</span>
                      </button>

                      <div v-if="checksumsOpen" class="collapse-fields-grid">
                        <label class="admin-field">
                          <span class="field-label">ETag</span>
                          <input
                            v-model="versionDraft.checksum_etag"
                            class="admin-input text-mono"
                            placeholder="例如: &quot;abcd1234...&quot;"
                          />
                        </label>
                        <label class="admin-field">
                          <span class="field-label">CRC64</span>
                          <input
                            v-model="versionDraft.checksum_crc64"
                            class="admin-input text-mono"
                            placeholder="例如: 15852710230531907"
                          />
                        </label>
                        <label class="admin-field">
                          <span class="field-label">MD5</span>
                          <input
                            v-model="versionDraft.checksum_md5"
                            class="admin-input text-mono"
                            placeholder="32位 MD5 字符串"
                          />
                        </label>
                      </div>
                    </div>
                  </div>

                  <div v-if="selectedDomainUsesPcEditor" class="form-section-card pc-artifacts-card">
                    <div class="section-card-header pc-artifacts-head">
                      <div class="card-title-group">
                        <h3>PC 资源文件</h3>
                        <p class="card-subtitle">编辑 package / patch 资源、分卷、路由、manifest/source 与下载 URL。</p>
                      </div>
                      <div class="section-header-tools artifact-mode-tabs">
                        <button
                          class="tool-pill-btn"
                          :class="{ active: editableDraft.artifactsMode === 'visual' }"
                          type="button"
                          @click="switchArtifactsMode('visual')"
                        >
                          列表
                        </button>
                        <button
                          class="tool-pill-btn"
                          :class="{ active: editableDraft.artifactsMode === 'json' }"
                          type="button"
                          @click="switchArtifactsMode('json')"
                        >
                          JSON
                        </button>
                        <button
                          v-if="editableDraft.artifactsMode === 'json'"
                          class="tool-pill-btn"
                          type="button"
                          @click="formatArtifactsJson"
                        >
                          格式化
                        </button>
                        <button
                          v-if="editableDraft.artifactsMode === 'visual'"
                          class="tool-pill-btn highlight"
                          type="button"
                          @click="addArtifactItem"
                        >
                          添加资源
                        </button>
                      </div>
                    </div>

                    <div class="pc-artifacts-overview">
                      <div class="pc-overview-item">
                        <span>资源总数</span>
                        <strong>{{ pcArtifactsOverview.total }}</strong>
                      </div>
                      <div class="pc-overview-item">
                        <span>Package</span>
                        <strong>{{ pcArtifactsOverview.packageCount }}</strong>
                      </div>
                      <div class="pc-overview-item">
                        <span>Patch</span>
                        <strong>{{ pcArtifactsOverview.patchCount }}</strong>
                      </div>
                      <div class="pc-overview-item">
                        <span>总大小</span>
                        <strong>{{ formatBytes(pcArtifactsOverview.totalSize) }}</strong>
                      </div>
                      <div class="pc-overview-item">
                        <span>有效 URL</span>
                        <strong>{{ pcArtifactsOverview.urlCount }}</strong>
                      </div>
                    </div>

                    <div v-if="editableDraft.artifactsMode === 'json'" class="admin-field full-width pc-json-editor">
                      <span class="field-label">Artifacts JSON</span>
                      <div class="code-editor-container">
                        <textarea
                          v-model="editableDraft.artifactsJson"
                          class="admin-code-textarea pc-json-textarea"
                          spellcheck="false"
                        ></textarea>
                      </div>
                      <small class="field-tip">保存时会交给后端按 PC schema 重新校验和生成 artifact_id。</small>
                    </div>

                    <div v-else class="pc-artifact-list">
                      <div
                        v-for="(artifact, artIndex) in editableDraft.artifacts"
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
                            :disabled="editableDraft.artifacts.length <= 1"
                            @click="removeArtifactItem(artIndex)"
                          >
                            删除资源
                          </button>
                        </div>

                        <AdminPcArtifactFields
                          :artifact="artifact"
                          :format-bytes="formatBytes"
                          :force-extract-artifact-name="(value) => forceExtractArtifactName(value as EditableArtifactDraft)"
                          :sync-artifacts-to-json="syncArtifactsToJson"
                        />

                        <div class="pc-artifact-section pc-url-list">
                          <div class="field-header-row">
                            <span class="field-label">下载 URL</span>
                            <button class="tool-pill-btn highlight" type="button" @click="addArtifactUrlItem(artIndex)">添加 URL</button>
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
                              @input="handleArtifactUrlChange(artifact, urlItem.url)"
                            />
                            <input
                              v-model.number="urlItem.priority"
                              class="admin-input pc-priority-input"
                              type="number"
                              min="0"
                              title="priority"
                              @input="syncArtifactsToJson"
                            />
                            <input
                              v-model="urlItem.source_kind"
                              class="admin-input pc-source-kind-input"
                              placeholder="official"
                              title="source_kind"
                              @input="syncArtifactsToJson"
                            />
                            <button class="url-action-pill-btn" type="button" @click="copyUrl(urlItem.url)">复制</button>
                            <button class="url-action-pill-btn" type="button" @click="probeUrlItem(urlItem)">
                              {{ urlProbeMap[urlItem.url]?.loading ? '测试中' : '测试' }}
                            </button>
                            <button
                              class="tool-pill-btn danger"
                              type="button"
                              :disabled="artifact.urls.length <= 1"
                              @click="removeArtifactUrlItem(artIndex, urlIndex)"
                            >
                              删除
                            </button>
                          </div>
                        </div>

                        <div class="pc-artifact-section">
                          <div class="pc-artifact-section-title">元数据</div>
                          <div class="admin-field-grid compact-3col">
                          <label class="admin-field">
                            <span class="field-label">Manifest <small class="field-sublabel">JSON object</small></span>
                            <textarea v-model="artifact.manifestJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                          </label>
                          <label class="admin-field">
                            <span class="field-label">Source <small class="field-sublabel">compact provenance JSON</small></span>
                            <textarea v-model="artifact.sourceJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                          </label>
                          <label class="admin-field">
                            <span class="field-label">附加属性 <small class="field-sublabel">attributes</small></span>
                            <textarea v-model="artifact.attributesJson" class="admin-code-textarea pc-mini-json" spellcheck="false" @input="syncArtifactsToJson"></textarea>
                          </label>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <!-- 底部操作条：新建走提交，编辑走吸附保存 -->
                  <div v-if="isCreateMode" class="form-actions-bar">
                  <div class="actions-left">
                    <button
                      type="button"
                      class="admin-btn secondary"
                      @click="resetCreateDraft"
                    >
                      <span>重置表单</span>
                    </button>
                    <span v-if="!createDraft.version.trim()" class="create-submit-hint">
                      填写版本号后即可提交
                    </span>
                  </div>

                  <div class="actions-right">
                    <button
                      class="admin-btn primary"
                      type="submit"
                      :disabled="loading || !selectedDomainId || !createDraft.version.trim()"
                    >
                      <span>{{ loading ? '录入中…' : '保存并录入新版本' }}</span>
                    </button>
                  </div>
                </div>
                  <!-- 底部吸附保存交互条（唯一保存入口） -->
                  <div v-else class="sticky-save-bar" :class="{ dirty: isEditableDirty }">
                    <div class="bar-left">
                      <span v-if="isEditableDirty" class="save-status-badge dirty">⚠ 有 {{ dirtyChangesCount }} 项未保存修改</span>
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
                        <span>{{ selectedDomainSupportsCreateVersion && isUrlChanged ? '保存并探活' : '保存更改' }}</span>
                      </button>
                    </div>
                  </div>
                </template>
              </form>
            </div>
            <div v-else class="content-work-card">
              <div class="version-status-topbar">
                <div class="version-header-meta">
                  <div class="version-title-row"><h2>PC 版本只读</h2></div>
                </div>
              </div>
              <div class="admin-empty-state">
                <strong>当前单 APK 表单不适用于 PC 资源</strong>
                <span>PC package、patch、voice、file manifest 与 chunk manifest 具有不同身份结构，当前不提供手工新增或编辑。</span>
                <span>请使用已接入的官方采集与探活流程维护记录；左侧版本列表仍可用于只读浏览。</span>
              </div>
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
                <h3>数据采集与版本探活控制台</h3>
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
                    <span class="op-action-title">查找新版本 + 探活全量（discover + probe）</span>
                    <span class="op-action-desc">先扫描官方入口发现新版本并写入索引，再逐条探活所有历史版本链接（推荐）</span>
                  </div>
                </label>

                <label
                  class="op-action-card"
                  :class="{ active: opAction === 'discover' }"
                  @click="opAction = 'discover'"
                >
                  <input v-model="opAction" class="op-radio" type="radio" value="discover" />
                  <div class="op-action-text">
                    <span class="op-action-title">仅查找新版本（discover）</span>
                    <span class="op-action-desc">只扫描官方入口并写入新版本记录，不检查已有链接的可用性</span>
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
                  全量数据 (APK + 已接入的 PC)
                </button>
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opPlatformScope === 'android' }"
                  :disabled="operationControlsLocked"
                  :aria-pressed="opPlatformScope === 'android'"
                  @click="opPlatformScope = 'android'"
                >
                  仅 Android (APK)
                </button>
                <button
                  type="button"
                  class="op-scope-btn"
                  :class="{ active: opPlatformScope === 'pc' }"
                  :disabled="operationControlsLocked"
                  :aria-pressed="opPlatformScope === 'pc'"
                  @click="opPlatformScope = 'pc'"
                >
                  仅 PC 客户端（已接入适配器）
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

              <!-- 执行操作按钮与实时进度 -->
              <AdminOperationProgress
                :loading="loading"
                :running="opRunning"
                :job="opJob"
                :scope-text="operationScopeText"
                :progress-percent="opProgressPercent"
                :current-game-label="opCurrentGameLabel"
                @start="executeAdminOperation"
                @cancel="cancelAdminOperation"
              />
            </div>

            <!-- 卡片 2: 定时调度与策略配置 -->
            <div class="probe-card">
              <div class="card-title-group">
                <h3>定时探活与采集计划</h3>
                <details class="inline-help">
                  <summary>说明</summary>
                  <p>{{ externalScheduleNotice }}</p>
                </details>
              </div>

              <!-- 每日采集计划 -->
              <div class="schedule-toggle-row">
                <label class="admin-toggle-label">
                  <input v-model="syncSchedule.enabled" class="admin-toggle-checkbox" type="checkbox" />
                  <span class="toggle-slider"></span>
                  <span class="toggle-text">{{ syncSchedule.enabled ? '采集计划参数已启用' : '采集计划参数已停用' }}</span>
                </label>
              </div>
              <div class="schedule-inputs-row">
                <label class="admin-field">
                  <span class="field-label">时间点 1（时区由外部任务定义）</span>
                  <input v-model="syncSchedule.times[0]" class="admin-input" type="time" />
                </label>
                <label class="admin-field">
                  <span class="field-label">时间点 2（时区由外部任务定义）</span>
                  <input v-model="syncSchedule.times[1]" class="admin-input" type="time" />
                </label>
              </div>
              <button class="admin-btn secondary full-width" type="button" :disabled="loading" @click="saveSyncSchedule">
                <span>保存采集计划参数</span>
              </button>

              <hr style="border: 0; border-top: 1px solid var(--line-soft); margin: 6px 0;" />

              <!-- 定时探活计划 -->
              <div class="schedule-runtime-status" aria-live="polite">
                <div>
                  内置探活计时器：<strong>{{ !probeSchedulerStatus ? '状态未知' : probeSchedulerStatus.running ? '运行中' : '已停止' }}</strong>
                </div>
                <div v-if="probeSchedulerStatus?.next_run_at">
                  下次任务计划：{{ formatSyncTime(probeSchedulerStatus.next_run_at) || '时间无效' }}
                </div>
                <div v-if="probeSchedulerStatus?.last_started_at">
                  最近任务启动：{{ formatSyncTime(probeSchedulerStatus.last_started_at) || '时间无效' }}
                  <span v-if="probeSchedulerStatus.last_job_id"> · 任务 {{ probeSchedulerStatus.last_job_id }}</span>
                </div>
                <div v-if="probeSchedulerStatus?.error" class="text-danger">错误：{{ probeSchedulerStatus.error }}</div>
              </div>
              <details class="inline-help">
                <summary>说明</summary>
                <p>{{ probeScheduleNotice }}</p>
              </details>
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
                      { label: '普通轮（跳过 20h 内有效证据）', value: 'normal' },
                      { label: '全量轮（新发现及上次可用 URL）', value: 'full' }
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
              <p v-if="opResult.discover.items_truncated" class="text-muted">
                本次采集共 {{ opResult.discover.items_total }} 条结果，下方保留 {{ opResult.discover.items.length }} 条明细；上方统计包含全部结果。
              </p>
              <h4 style="margin: 0 0 10px; font-size: 13.5px; font-weight: 750; color: #7dd3fc;">查找新版本 (Discover) 执行明细</h4>
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
                        <span v-if="item.new" class="op-badge info">全新版本</span>
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
              <p v-if="opResult.probe.items_truncated" class="text-muted">
                本次探活共 {{ opResult.probe.items_total }} 条结果，下方保留 {{ opResult.probe.items.length }} 条明细；筛选仅针对保留的明细，上方统计包含全部结果。
              </p>
              <div class="op-table-head-row">
                <h4 style="margin: 0; font-size: 13.5px; font-weight: 750; color: #34d399;">
                  历史版本探活 (Probe) 执行明细
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
                      <th>探活原因 / 异常信息</th>
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
                        <span
                          :class="!pItem.ok || pItem.available === false ? 'text-rose' : isProbeUnknownItem(pItem) ? 'text-amber' : 'text-emerald'"
                          style="font-size: 11.5px;"
                        >{{ probeResultReason(pItem) }}</span>
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

          <!-- 底部全宽运维日志面板 -->
          <div class="admin-terminal-window">
            <div class="terminal-titlebar">
              <div class="terminal-heading">
                <h3>任务日志</h3>
                <p>实时记录探活与版本发现结果，原始行可展开查看。</p>
              </div>
              <div class="terminal-state" :class="`tone-${terminalLogTone(terminalStatusText)}`">
                <span class="terminal-state-dot"></span>
                <span>{{ terminalStatusText }}</span>
              </div>
              <div class="terminal-actions">
                <button class="terminal-refresh-btn" type="button" @click="opTerminalHidden = true" title="仅隐藏当前页面的日志">
                  <span>清屏</span>
                </button>
                <button class="terminal-refresh-btn" type="button" :disabled="loading || operationPollBusy" @click="refreshTerminalLogs" title="重新获取日志">
                  <span>刷新</span>
                </button>
              </div>
            </div>
            <div class="terminal-summary" aria-label="日志摘要">
              <div class="terminal-summary-item">
                <span>范围</span>
                <strong>{{ operationScopeText }}</strong>
              </div>
              <div class="terminal-summary-item">
                <span>记录</span>
                <strong>{{ terminalLogStats.total }}</strong>
              </div>
              <div class="terminal-summary-item tone-success">
                <span>成功</span>
                <strong>{{ terminalLogStats.success }}</strong>
              </div>
              <div class="terminal-summary-item tone-danger">
                <span>异常</span>
                <strong>{{ terminalLogStats.danger }}</strong>
              </div>
              <div class="terminal-summary-item tone-warning">
                <span>待确认</span>
                <strong>{{ terminalLogStats.warning }}</strong>
              </div>
            </div>
            <div class="terminal-viewport" aria-live="polite">
              <div v-if="opTerminalHidden" class="terminal-empty terminal-empty-muted">
                <strong>日志已清屏</strong>
                <span>仅隐藏当前页面，新日志到达后会继续显示。</span>
              </div>
              <div v-else-if="terminalLogEntries.length" class="terminal-list">
                <article
                  v-for="entry in terminalLogEntries"
                  :key="entry.id"
                  class="terminal-row"
                  :class="`tone-${entry.tone}`"
                >
                  <span class="terminal-row-index">{{ String(entry.id).padStart(3, '0') }}</span>
                  <div class="terminal-row-content">
                    <div class="terminal-row-meta">
                      <span class="terminal-phase">{{ entry.phase }}</span>
                      <strong>{{ entry.target }}</strong>
                      <span class="terminal-outcome">{{ entry.outcome }}</span>
                    </div>
                    <p v-if="entry.detail" class="terminal-row-detail">{{ entry.detail }}</p>
                    <details class="terminal-raw-details">
                      <summary>查看原始记录</summary>
                      <code>{{ entry.raw }}</code>
                    </details>
                  </div>
                </article>
              </div>
              <div v-else class="terminal-empty">
                <strong>暂无运维日志</strong>
                <span>点击上方执行按钮开始任务，或刷新以获取最新记录。</span>
              </div>
            </div>
          </div>
        </section>
      </template>
    </main>

    <AdminConfirmDialog :request="pendingConfirm" @resolve="resolveConfirm" />
  </div>
</template>
