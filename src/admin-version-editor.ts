import { formatBytes } from "./admin-format";
import type { AdminDomain, ManualArtifactPayload, VersionSummary } from "./types";

export interface EditableArtifactDraft {
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

export function supportsPcVersionEditor(domain: AdminDomain | null | undefined): boolean {
  const normalized = (domain?.platform || "").trim().toLowerCase();
  if (normalized !== "windows" && normalized !== "pc") return false;
  const capabilities = new Set((domain?.capabilities || []).map((item) => item.trim().toLowerCase()));
  const kind = (domain?.kind || "").trim().toLowerCase();
  return capabilities.has("packages") || capabilities.has("patches") || kind === "packages" || kind === "patches";
}

export function isVersionAvailable(item: VersionSummary): boolean {
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  if (unavailableCount > 0 && availableCount === 0 && canonicalCount === 0) {
    return false;
  }
  return true;
}

export function getChecksumSummaryText(etag: string, crc64: string, md5: string): string {
  const parts: string[] = [];
  if (etag?.trim()) parts.push("ETag");
  if (crc64?.trim()) parts.push("CRC64");
  if (md5?.trim()) parts.push("MD5");
  if (!parts.length) return "";
  return parts.join(" · ");
}

export function normalizeJsonStr(jsonStr: string): string {
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

export function getNormalizedUnpackedSize(size: number | null | undefined): number | null {
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

export function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function jsonValueToText(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function parseOptionalJsonOrString(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

export function compactArtifactAttributes(attributes: Record<string, unknown>): string {
  const extra = { ...attributes };
  for (const key of ARTIFACT_ATTRIBUTE_KEYS) {
    delete extra[key];
  }
  return JSON.stringify(extra, null, 2);
}

type ArtifactUrlInput = { id?: number; url?: unknown; priority?: unknown; source_kind?: unknown };

export function normalizeArtifactUrls(
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

export function artifactDraftFromPayload(item: any, idx: number): EditableArtifactDraft {
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

export function buildVisualArtifactAttributes(art: EditableArtifactDraft): Record<string, unknown> {
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

export function normalizeArtifactPayloadFromJson(item: any, idx: number): ManualArtifactPayload {
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

export function parseArtifactsJsonPayload(jsonText: string): ManualArtifactPayload[] {
  const parsed = JSON.parse(jsonText || "[]");
  if (!Array.isArray(parsed)) {
    throw new Error("Artifacts JSON 顶层必须是数组");
  }
  return parsed.map(normalizeArtifactPayloadFromJson);
}

const PC_COMPONENTS = new Set(["game", "voice", "launcher", "other"]);
const PC_PACKAGE_TYPES = new Set(["full", "segment", "optional", "differential"]);
const PC_DELIVERY_MODES = new Set(["direct", "archive", "file_manifest"]);
const COMPACT_SOURCE_KEYS = new Set(["source_kind", "source_name", "source_url", "source_repo", "source_commit"]);
const COMPACT_SOURCE_KINDS = new Set(["official_sync", "third_party_history", "legacy_migration", "manual"]);

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validatePcArtifacts(artifacts: ManualArtifactPayload[]): void {
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

export function normalizeArtifactsForComparison(artifacts: ManualArtifactPayload[]): string {
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

export function extractFilenameFromUrl(rawUrl: string): string {
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

export function applyArtifactFilenameFromUrl(art: EditableArtifactDraft, rawUrl: string, force = false): boolean {
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

export interface VersionDraft {
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

export function defaultCreateDraft(): VersionDraft {
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

export function getDomainFriendlyName(d: AdminDomain | null): string {
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

export function isVersionUnavailable(item: VersionSummary): boolean {
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  return unavailableCount > 0 && availableCount === 0 && canonicalCount === 0;
}

export function isVersionUnknown(item: VersionSummary): boolean {
  const availability = versionAvailabilityCounts(item);
  const availableCount = availability.available;
  const canonicalCount = availability.canonical;
  const unavailableCount = availability.unavailable;
  return availableCount === 0 && canonicalCount === 0 && unavailableCount === 0;
}

export function versionAvailabilityCounts(item: VersionSummary): {
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

export function versionHealthClass(item: VersionSummary): "available" | "unavailable" | "unknown" {
  if (isVersionUnavailable(item)) return "unavailable";
  if (isVersionUnknown(item)) return "unknown";
  return "available";
}

export function versionHealthTitle(item: VersionSummary): string {
  if (isVersionUnavailable(item)) return "链接不可用";
  if (isVersionUnknown(item)) return "尚未探活";
  return "链接可用";
}

// 版本分组数据结构定义
export interface VersionMinorGroup {
  minorKey: string;
  items: VersionSummary[];
}

export interface VersionGroupEntry {
  type: "single" | "minorGroup";
  item?: VersionSummary;
  group?: VersionMinorGroup;
}

export interface VersionMajorGroup {
  majorKey: string;
  totalCount: number;
  unavailableCount: number;
  entries: VersionGroupEntry[];
  allItems: VersionSummary[];
}

// 解析版本号主分类、次分类与排序数字权重
export function parseVersionKey(versionStr: string): { majorKey: string; minorKey: string; sortWeights: number[] } {
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
export function compareVersionsDesc(a: VersionSummary, b: VersionSummary): number {
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

export function pcArtifactTitle(artifact: EditableArtifactDraft, index: number): string {
  return artifact.name.trim() || `未命名资源 #${index + 1}`;
}

export function pcArtifactSummaryTags(artifact: EditableArtifactDraft): string[] {
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
