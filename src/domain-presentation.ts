import type { ArchiveDomain, Artifact, ArtifactUrl, AvailabilityCurrent, AvailabilityState, VersionSummary } from "./types";

const defaults: Record<string, string> = {
  apk: "Android APK",
  archive: "归档信息",
  chunks: "Chunk 信息",
  files: "文件清单",
  manifest: "清单文件",
  legacy: "候选线索",
  packages: "完整包",
  patches: "更新补丁",
  compare: "版本对比",
  resources: "运行时资源",
};

export function archiveSourceLabel(adapter: string | undefined, sourceKind?: unknown): string {
  if (sourceKind === "legacy_migration") return "历史迁移/社区归档资源";
  if (sourceKind === "official_launcher") {
    if (adapter === "wuwa") return "鸣潮官方启动器索引";
    if (adapter === "arknights") return "鹰角 PC 官方 API";
  }
  if (adapter === "arknights") return "鹰角 PC 官方 API";
  if (adapter === "endfield") return "终末地资源接口 / 社区归档";
  if (adapter === "wuwa") return "官方启动器";
  if (adapter === "hoyo") return "HoYo 官方版本清单";
  if (adapter === "patchersdk") return "PatcherSDK ResList";
  if (adapter === "perfectworld_patcher") return "完美世界官方 PatcherSDK";
  if (adapter === "nte") return "幻塔官方 ResList";
  if (adapter === "android") return "官方安装包直链";
  if (adapter === "resources") return "官方资源清单";
  return "官方 CDN 清单";
}

export function deliveryLabel(artifact: Artifact): string {
  const mode = artifact.attributes?.delivery_mode;
  if (mode === "file_manifest") return artifact.kind === "patch" ? "更新资源清单" : "官方资源清单";
  return artifact.kind === "patch" ? "更新补丁" : "完整包";
}

export function domainModeLabel(domain: ArchiveDomain | null | undefined, capability: string): string {
  if (domain?.adapter === "wuwa") {
    if (capability === "packages") return "资源清单";
    if (capability === "files") return "文件列表";
  }
  if (capability === "files" && domain?.adapter === "hoyo") {
    return "文件列表";
  }
  return defaults[capability] || capability;
}

export interface ArchiveModePresentation {
  domain: ArchiveDomain;
  capability: string;
}

export interface ArchiveMetric {
  label: string;
  value: string;
}

export interface ArchiveOverviewPresentation {
  overviewMetrics: ArchiveMetric[];
  moduleDetails: ArchiveMetric[];
  artifactKind: string;
}

export interface SyncStatusPresentation {
  primaryLabel: string;
  primaryLatest: string;
  primaryDomain: ArchiveDomain | null;
  androidSecondary: string | null;
}

export interface FileTimestampEvidence {
  value: string | null;
  source: "created" | "uploaded" | "extracted" | "archived" | "released" | "unknown";
}

export interface VersionBadgePresentation {
  label: string;
  tone: "blue" | "amber" | "violet" | "green" | "red" | "slate";
}

const creationTimeKeys = ["file_created_at", "created_at", "creation_time"];
const officialPathKeys = ["decompressed_path", "last_modified_url", "official_url", "source_url", "file_path", "path"];
const uploadTimeKeys = ["server_uploaded_at", "uploaded_at", "last_modified"];
const archiveTimeKeys = ["archived_at", "archive_time"];
const releaseTimeKeys = ["source_released_at", "release_date", "released_at", "release_time"];

export function domainFieldSupport(
  domain: ArchiveDomain | null | undefined,
  group: "version_fields" | "artifact_fields",
  field: string,
): "supported" | "unsupported" {
  const contract = domain?.capability_contract || {};
  const declared = contract[group] || {};
  if (!Object.keys(declared).length) return "supported";
  return declared[field] || "unsupported";
}

export function domainFeatureSupport(domain: ArchiveDomain | null | undefined, feature: string): boolean {
  const features = domain?.capability_contract?.features || {};
  return features[feature] === "supported";
}

export function domainActionSupport(domain: ArchiveDomain | null | undefined, action: string): boolean {
  const actions = domain?.capability_contract?.actions || {};
  return actions[action] === "conditional";
}

function validDateParts(year: number, month: number, day: number, hour = 0, minute = 0, second = 0): boolean {
  const candidate = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  return candidate.getUTCFullYear() === year && candidate.getUTCMonth() === month - 1 && candidate.getUTCDate() === day
    && candidate.getUTCHours() === hour && candidate.getUTCMinutes() === minute && candidate.getUTCSeconds() === second;
}

function extractedTimestamp(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const precise = value.match(/(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)/);
  if (precise) {
    const [, year, month, day, hour, minute, second] = precise.map(Number);
    if (validDateParts(year, month, day, hour, minute, second)) return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}T${hour.toString().padStart(2, "0")}:${minute.toString().padStart(2, "0")}:${second.toString().padStart(2, "0")}+08:00`;
  }
  const dateOnly = value.match(/(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)/);
  if (!dateOnly) return null;
  const [, year, month, day] = dateOnly.map(Number);
  return validDateParts(year, month, day) ? `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}T00:00:00+08:00` : null;
}

function parsedTimestamp(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? null : new Date(timestamp).toISOString();
}

export function fileTimestampEvidence(summary: VersionSummary): FileTimestampEvidence {
  const attributes = summary.attributes || {};
  if (summary.source_released_at) {
    const value = parsedTimestamp(summary.source_released_at);
    if (value) return { value, source: "released" };
  }
  if (summary.source_updated_at) {
    const value = parsedTimestamp(summary.source_updated_at);
    if (value) return { value, source: "uploaded" };
  }
  if (summary.archived_at) {
    const value = parsedTimestamp(summary.archived_at);
    if (value) return { value, source: "archived" };
  }
  if (attributes.time_kind === "archive") {
    for (const key of archiveTimeKeys) {
      const value = parsedTimestamp(attributes[key]);
      if (value) return { value, source: "archived" };
    }
  }
  for (const key of creationTimeKeys) {
    const value = attributes[key];
    if (typeof value === "string" && parsedTimestamp(value)) return { value, source: "created" };
  }
  for (const key of officialPathKeys) {
    const value = extractedTimestamp(attributes[key]);
    if (value) return { value, source: "created" };
  }
  for (const key of uploadTimeKeys) {
    const value = parsedTimestamp(attributes[key]);
    if (value) return { value, source: "uploaded" };
  }
  for (const key of releaseTimeKeys) {
    const rawValue = attributes[key];
    if (typeof rawValue === "string" && /^\d{4}-\d{2}-\d{2}$/.test(rawValue)) return { value: rawValue, source: "released" };
    const value = parsedTimestamp(rawValue);
    if (value) return { value, source: "released" };
  }
  for (const key of archiveTimeKeys) {
    const value = parsedTimestamp(attributes[key]);
    if (value) return { value, source: "archived" };
  }
  const excluded = new Set([...creationTimeKeys, ...officialPathKeys, ...uploadTimeKeys, ...archiveTimeKeys, ...releaseTimeKeys]);
  for (const [key, rawValue] of Object.entries(attributes)) {
    if (excluded.has(key)) continue;
    const value = extractedTimestamp(rawValue);
    if (value) return { value, source: "extracted" };
  }
  return { value: null, source: "unknown" };
}

const modePriority: Record<string, number> = { resources: -1, files: 0, packages: 0, patches: 1, manifest: 2, chunks: 3, archive: 7, compare: 8, legacy: 8.5, apk: 9 };
const artifactKinds: Record<string, string> = { apk: "apk", chunks: "chunk", files: "file", manifest: "manifest", packages: "package", patches: "patch", resources: "resource" };

export function availableArchiveModes(domains: ArchiveDomain[]): ArchiveModePresentation[] {
  return domains.flatMap((domain) => {
    let capabilities = [...domain.capabilities].filter((capability) => capability !== "archive");
    if (domain.adapter === "wuwa") {
      capabilities = capabilities.filter((capability) => capability !== "packages");
    }
    return [...new Set(capabilities)].map((capability) => ({ domain, capability }));
  }).sort((left, right) => {
    const leftPriority = left.domain.game_id === "endfield" && left.capability === "resources" ? -1 : modePriority[left.capability] ?? 5;
    const rightPriority = right.domain.game_id === "endfield" && right.capability === "resources" ? -1 : modePriority[right.capability] ?? 5;
    return leftPriority - rightPriority || Number(left.domain.sort_order || 0) - Number(right.domain.sort_order || 0) || left.domain.id.localeCompare(right.domain.id);
  });
}

export function artifactKindForMode(mode: string): string {
  return artifactKinds[mode] || "";
}

export function isAvailabilityActionable(current: AvailabilityCurrent | null, url: string, now = Date.now()): boolean {
  if (!current || current.evidence_status !== "verified" || current.state !== "available" || !current.source_kind || !current.source_confidence || !current.observed_at) return false;
  if (["not_probed", "expired"].includes(current.reason)) return false;
  if (current.expires_at && Date.parse(current.expires_at) <= now) return false;
  if (url.includes("auth_key=") && !current.expires_at) return false;
  return true;
}

export function preferredArtifactAction(artifact: Artifact, now = Date.now()): ArtifactUrl | null {
  const actionable = artifact.urls.filter((candidate) => isAvailabilityActionable(candidate.current, candidate.url, now));
  return actionable.find((candidate) => candidate.source_kind === "official")
    || actionable.find((candidate) => candidate.source_kind === "mirror")
    || actionable[0]
    || null;
}

function allowsMetadataOnlyActions(domain: ArchiveDomain | null | undefined): boolean {
  const contract = domain?.capability_contract;
  const sourceKinds = contract?.availability_source_kinds || [];
  return contract?.live_probe === false
    && sourceKinds.length > 0
    && sourceKinds.every((value) => value === "metadata_inference");
}

function metadataUrlIsUsable(candidate: ArtifactUrl, now: number): boolean {
  try {
    const parsed = new URL(candidate.url);
    if (!["http:", "https:"].includes(parsed.protocol)) return false;
  } catch {
    return false;
  }
  const current = candidate.current;
  if (current?.state === "unavailable" || current?.reason === "expired" || current?.evidence_status === "expired") return false;
  if (current?.expires_at && Date.parse(current.expires_at) <= now) return false;
  if (candidate.url.includes("auth_key=")) return isAvailabilityActionable(current, candidate.url, now);
  return true;
}

function preferredMetadataArtifactAction(artifact: Artifact, now: number): ArtifactUrl | null {
  const usable = artifact.urls.filter((candidate) => metadataUrlIsUsable(candidate, now));
  return usable.find((candidate) => candidate.source_kind === "official")
    || usable.find((candidate) => candidate.source_kind === "mirror")
    || usable[0]
    || null;
}

export function preferredDomainArtifactAction(
  domain: ArchiveDomain | null | undefined,
  artifact: Artifact,
  action: "open" | "copy" | "download",
  now = Date.now(),
): ArtifactUrl | null {
  if (!domainActionSupport(domain, action)) return null;
  return preferredArtifactAction(artifact, now)
    || (allowsMetadataOnlyActions(domain) ? preferredMetadataArtifactAction(artifact, now) : null);
}

export function artifactActionLabel(artifact: Artifact, now = Date.now()): string {
  const preferred = preferredArtifactAction(artifact, now);
  if (preferred?.source_kind === "mirror") return "镜像可用";
  if (preferred) return "可用";
  if (artifact.urls.some((candidate) => candidate.current?.reason === "expired" || (candidate.current?.expires_at && Date.parse(candidate.current.expires_at) <= now))) return "链接已过期";
  if (artifact.urls.some((candidate) => candidate.current?.state === "unavailable")) return "不可用";
  if (artifact.urls.some((candidate) => candidate.current?.source_kind === "live_probe" && candidate.current.reason === "probe_failed")) return "探测失败";
  if (artifact.urls.some((candidate) => candidate.current?.source_kind === "live_probe" && candidate.current.state === "unknown")) return "探测未判定";
  return "未验证";
}

export function formatObservedDate(value?: string | null): string {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replaceAll("-", ".");
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "—";
  const date = new Date(timestamp);
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((result, part) => {
      if (part.type !== "literal") result[part.type] = part.value;
      return result;
    }, {});
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}

export function hoyoLanguageLabel(value: unknown): string {
  const norm = String(value || "").toLowerCase();
  const map: Record<string, string> = {
    "zh-cn": "中文",
    "zh": "中文",
    "chinese": "中文",
    "en-us": "英语",
    "en": "英语",
    "english": "英语",
    "ko-kr": "韩语",
    "ko": "韩语",
    "korean": "韩语",
    "ja-jp": "日语",
    "ja": "日语",
    "japanese": "日语",
  };
  return map[norm] || String(value || "语言未知");
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = "B";
  for (const next of units) {
    amount /= 1024;
    unit = next;
    if (amount < 1024 || next === "TB") break;
  }
  return `${amount.toFixed(2)} ${unit}`;
}

export function hoyoArtifactCardPresentation(
  artifact: Artifact,
  selectedVersion: string,
  index = 0,
  total = 0,
): { label: string; subtitle: string } {
  const component = String(artifact.attributes.component || "game");
  const packageType = String(artifact.attributes.package_type || "");
  const availability = artifactActionLabel(artifact);
  if (artifact.kind === "patch") {
    const from = String(artifact.attributes.route_from || "未知版本");
    const to = String(artifact.attributes.route_to || selectedVersion || "未知版本");
    const route = `${from} -> ${to}`;
    const voice = component === "voice";
    const lang = voice && artifact.attributes.language ? hoyoLanguageLabel(artifact.attributes.language) : "";
    return {
      label: voice ? (lang ? `${lang}语音更新` : "语音包更新") : "游戏包更新",
      subtitle: `${voice ? `${lang} ` : ""}${route} / ${formatBytes(artifact.size)} / ${availability}`,
    };
  }
  if (component === "voice") {
    const lang = artifact.attributes.language ? hoyoLanguageLabel(artifact.attributes.language) : "";
    return {
      label: lang ? `${lang}语音` : "语音包",
      subtitle: `${lang ? `${lang} / ` : ""}${formatBytes(artifact.size)} / ${availability}`,
    };
  }
  const position = Number(artifact.attributes.route_part || artifact.part || index + 1);
  if (packageType === "full") return { label: "游戏完整包", subtitle: `完整包 / ${formatBytes(artifact.size)} / ${availability}` };
  return { label: "游戏包分卷", subtitle: `${position}/${total || position} / ${formatBytes(artifact.size)} / ${availability}` };
}

export function availabilityLabel(states: Record<string, number> = {}): string {
  const available = states.available || 0;
  const unavailable = states.unavailable || 0;
  const unknown = states.unknown || 0;
  if (available && !unavailable && !unknown) return "可用";
  if (unavailable && !available && !unknown) return "链接失效";
  if (available && (unavailable || unknown)) return "部分可达";
  return "未判定";
}

interface WuWaFilesAvailability {
  states: Record<string, number>;
  count: number;
  archivedOnly: boolean;
}

/** Aggregate WuWa file-manifest status without treating local manifests as probed URLs. */
function wuwaFilesAvailability(summary: VersionSummary): WuWaFilesAvailability {
  const states: Record<string, number> = {};
  let count = 0;
  let archivedCount = 0;
  const attrs = summary.attributes || {};
  const manifestUrls = Array.isArray(attrs.manifest_urls) ? attrs.manifest_urls.filter(Boolean) : [];
  const localManifest = typeof attrs.local_manifest === "string" ? attrs.local_manifest.trim() : "";
  const localOnlyPackage = (attrs.delivery_mode === "file_manifest" && Boolean(localManifest) && manifestUrls.length === 0)
    // The compact version summary may omit the per-artifact local_manifest but
    // retains the empty remote candidate list for historical local packages.
    || (Object.prototype.hasOwnProperty.call(attrs, "manifest_urls") && manifestUrls.length === 0
      && Number(summary.artifact_kinds?.package?.availability_states?.unknown || 0) > 0);

  for (const kind of ["package", "patch"]) {
    const kindSummary = summary.artifact_kinds?.[kind];
    if (!kindSummary) continue;
    const kindCount = Number(kindSummary.count || 0);
    const kindStates = kindSummary.availability_states || {};
    if (kind === "package" && localOnlyPackage) {
      archivedCount += kindCount;
      continue;
    }
    count += kindCount;
    for (const [state, value] of Object.entries(kindStates)) states[state] = (states[state] || 0) + Number(value || 0);
  }
  return { states, count, archivedOnly: archivedCount > 0 && count === 0 };
}

export function availabilityStatesForMode(summary: VersionSummary | null, mode: string, adapter?: string): Record<string, number> {
  if (!summary) return {};
  if (mode === "files" && adapter === "wuwa") {
    return wuwaFilesAvailability(summary).states;
  }
  if (mode === "files" && adapter === "perfectworld_patcher") {
    return summary.artifact_kinds?.package?.availability_states || {};
  }
  const kind = artifactKindForMode(mode);
  return kind ? summary.artifact_kinds?.[kind]?.availability_states || {} : summary.availability_states;
}

export function artifactCountForMode(summary: VersionSummary | null, mode: string, adapter?: string): number {
  if (!summary) return 0;
  if (mode === "files" && adapter === "wuwa") {
    return wuwaFilesAvailability(summary).count;
  }
  if (mode === "files" && adapter === "perfectworld_patcher") {
    const packageAttrs = summary.attributes || {};
    return Number(packageAttrs.decoded_file_count || summary.artifact_kinds?.package?.count || 0);
  }
  const kind = artifactKindForMode(mode);
  return kind ? Number(summary.artifact_kinds?.[kind]?.count || 0) : Number(summary.artifact_count || 0);
}

export function artifactUrlStateCounts(artifact: Artifact): Record<AvailabilityState, number> {
  const counts: Record<AvailabilityState, number> = { available: 0, unavailable: 0, unknown: 0 };
  for (const candidate of artifact.urls) {
    const verified = candidate.evidence_status === "verified" && candidate.current?.evidence_status === "verified";
    counts[verified ? candidate.current?.state || "unknown" : "unknown"] += 1;
  }
  return counts;
}

function platformLabel(platform: string): string {
  if (platform === "windows") return "Windows";
  if (platform === "android") return "Android";
  return platform || "未知平台";
}

function syncPlatformLabel(platform: string): string {
  if (platform === "windows") return "PC";
  if (platform === "android") return "Android";
  return platformLabel(platform);
}

function normalizedPlatform(domain: ArchiveDomain | null | undefined): string {
  return String(domain?.platform || "").toLowerCase();
}

function isAndroidArchiveDomain(domain: ArchiveDomain | null | undefined): boolean {
  const platform = normalizedPlatform(domain);
  if (platform) return platform === "android";
  return domain?.adapter === "android" || domain?.kind === "apk" || Boolean(domain?.capabilities.includes("apk"));
}

function isPcArchiveDomain(domain: ArchiveDomain | null | undefined): boolean {
  const platform = normalizedPlatform(domain);
  return platform === "windows" || platform === "pc";
}

function syncStatusLabel(domain: ArchiveDomain | null): string {
  const platform = normalizedPlatform(domain) || (isAndroidArchiveDomain(domain) ? "android" : "");
  return `最新 ${syncPlatformLabel(platform)} 版本`;
}

export function buildSyncStatusPresentation(input: {
  domains: ArchiveDomain[];
  currentDomain: ArchiveDomain | null;
  currentLatest: VersionSummary | null;
}): SyncStatusPresentation {
  const pcDomain = input.domains.find(isPcArchiveDomain) || null;
  const androidDomain = input.domains.find(isAndroidArchiveDomain) || null;
  const primaryDomain = pcDomain || input.currentDomain || input.domains[0] || null;
  const primaryLatest = primaryDomain?.latest_version
    || (primaryDomain?.id === input.currentDomain?.id ? input.currentLatest?.version : null)
    || "—";
  const androidSecondary = androidDomain && androidDomain.id !== primaryDomain?.id
    ? androidDomain.latest_version || "—"
    : null;
  return {
    primaryLabel: syncStatusLabel(primaryDomain),
    primaryLatest,
    primaryDomain,
    androidSecondary,
  };
}

export function distributionProfile(summary: VersionSummary): string {
  const count = (kind: string) => summary.artifact_kinds?.[kind]?.count || 0;
  const hasChunk = count("chunk") > 0 || Boolean(summary.attributes.has_chunk);
  const hasPackage = count("package") > 0;
  const directPath = String(summary.attributes.decompressed_path || "");
  const hasDirect = Boolean(directPath);
  if (hasChunk && hasPackage && hasDirect) return "完整包 + 直链 + Chunk";
  if (hasChunk && !hasPackage && !hasDirect) return "Chunk";
  if (hasChunk && hasDirect) return "直链 + Chunk";
  if (hasChunk && hasPackage) return "完整包 + Chunk";
  if (hasPackage && hasDirect) return "完整包 + 直链";
  if (hasDirect) return "直链文件";
  if (hasPackage) return "完整包";
  return "索引记录";
}

export function displayVersionLabel(
  version: string,
  attributes?: Record<string, unknown> | null,
): string {
  // The picker and headers show only the plain version number; channel
  // details live on the artifact cards in the download area.
  const raw = String((attributes && attributes.display_version) || version);
  return raw.split("@")[0] || raw;
}


export function buildVersionBadges(
  domain: ArchiveDomain | null,
  item: VersionSummary,
  formatDate: (value: string) => string,
  includeAvailability = true,
  mode?: string,
): VersionBadgePresentation[] {
  if (!domain) return [];
  const count = (kind: string) => item.artifact_kinds?.[kind]?.count || 0;
  const result: VersionBadgePresentation[] = [];
  const timestamp = fileTimestampEvidence(item);
  if (timestamp.value) result.push({ label: formatDate(timestamp.value), tone: "slate" });

  if (domain.adapter === "patchersdk") {
    result.push({ label: "完整文件", tone: "blue" });
    if (count("patch")) result.push({ label: "含更新补丁", tone: "amber" });
  } else if (domain.adapter === "perfectworld_patcher") {
    result.push({ label: mode === "files" ? "文件清单" : "完整文件", tone: "blue" });
  } else if (domain.capabilities.includes("resources")) {
    result.push({ label: "运行时资源", tone: "green" });
  } else if (
    (domainFeatureSupport(domain, "split_versions") && domainFeatureSupport(domain, "package_file_list"))
    || domain.adapter === "wuwa"
  ) {
    result.push({ label: "文件清单", tone: "blue" });
  } else if (domain.adapter === "hoyo") {
    result.push({ label: distributionProfile(item), tone: count("chunk") ? "violet" : "blue" });
    if (count("patch")) result.push({ label: "含更新包", tone: "amber" });
  } else if (domain.capabilities.includes("files")) {
    result.push({ label: "文件清单", tone: "blue" });
    if (domain.capabilities.includes("patches") && count("patch")) result.push({ label: "含更新补丁", tone: "amber" });
  } else if (domain.capabilities.includes("packages")) {
    result.push({ label: "完整包", tone: "blue" });
    if (domain.capabilities.includes("patches") && count("patch")) result.push({ label: "含更新补丁", tone: "amber" });
  }

  if (includeAvailability) {
    const wuwaFiles = domain.adapter === "wuwa" && mode === "files";
    const manifestFiles = (domain.adapter === "wuwa" || domain.adapter === "perfectworld_patcher") && mode === "files";
    const states = manifestFiles ? availabilityStatesForMode(item, "files", domain.adapter) : item.availability_states;
    const total = manifestFiles ? artifactCountForMode(item, "files", domain.adapter) : Number(item.artifact_count || 0);
    if (wuwaFiles && wuwaFilesAvailability(item).archivedOnly) {
      result.push({ label: "已归档", tone: "slate" });
      return result;
    }
    const unavailable = Number(states?.unavailable || 0);
    const unknown = Number(states?.unknown || 0);
    if (unavailable > 0 && total > 0 && unavailable >= total) {
      result.push({ label: domain.adapter === "android" ? "不可用" : "链接失效", tone: "red" });
    } else if (unavailable > 0 && domain.adapter !== "android") {
      result.push({ label: `含失效 ${unavailable}`, tone: "amber" });
    }
  }
  return result;
}

export function buildArchiveOverview(input: {
  domain: ArchiveDomain | null;
  summary: VersionSummary | null;
  mode: string;
  version: string;
  displayVersion?: string;
  channelSummaries?: VersionSummary[];
  formatBytes: (value: number) => string;
  formatDate: (value?: string | null) => string;
}): ArchiveOverviewPresentation {
  const { domain, summary, mode, version, formatBytes, formatDate } = input;
  const kind = artifactKindForMode(mode);
  const kindSummary = summary?.artifact_kinds?.[kind];
  const count = kind ? kindSummary?.count || 0 : summary?.artifact_count || 0;
  const size = kind ? kindSummary?.size || 0 : summary?.packed_size || 0;
  const currentVersion = input.displayVersion || version || "—";
  const timestamp = summary ? fileTimestampEvidence(summary) : { value: null, source: "unknown" as const };
  const overviewMetrics: ArchiveMetric[] = [
    { label: "当前版本", value: currentVersion },
    { label: "数据模块", value: domain ? mode === "apk" ? "Android APK" : `${platformLabel(domain.platform)} · ${domainModeLabel(domain, mode)}` : "—" },
    {
      label: timestamp.source === "archived" ? "归档时间" : timestamp.source === "released" ? "发布时间" : "文件时间",
      value: domainFieldSupport(domain, "version_fields", timestamp.source === "released" ? "source_released_at" : timestamp.source === "archived" ? "archived_at" : "observed_at") === "unsupported"
        ? "不支持"
        : formatDate(timestamp.value),
    },
    { label: "条目数", value: `${count.toLocaleString()} 个` },
    { label: "总大小", value: domainFieldSupport(domain, "artifact_fields", "size") === "unsupported" ? "不支持" : formatBytes(size) },
    { label: "可用性", value: mode === "files" ? "不适用" : domainFieldSupport(domain, "artifact_fields", "availability") === "unsupported" ? "不支持" : availabilityLabel(availabilityStatesForMode(summary, mode)) },
  ];
  if (!domain || !summary) return { overviewMetrics, moduleDetails: [], artifactKind: kind };

  const countOf = (name: string) => summary.artifact_kinds?.[name]?.count || 0;
  const sizeOf = (name: string) => summary.artifact_kinds?.[name]?.size || 0;
  const attrs = summary.attributes || {};
  let moduleDetails: ArchiveMetric[] = [];
  if (domain.adapter === "android") {
    const channelGroups = [summary, ...(input.channelSummaries || [])].filter((item): item is VersionSummary => Boolean(item));
    const channels = new Set<string>();
    const availability = { available: 0, unavailable: 0, unknown: 0 };
    for (const group of channelGroups) {
      const groupAttrs = group.attributes || {};
      if (typeof groupAttrs.channel === "string" && groupAttrs.channel) channels.add(groupAttrs.channel);
      if (typeof groupAttrs.channel_ids === "string") {
        for (const channel of groupAttrs.channel_ids.split("/").map((part) => part.trim()).filter(Boolean)) channels.add(channel);
      }
      availability.available += Number(group.availability_states?.available || 0);
      availability.unavailable += Number(group.availability_states?.unavailable || 0);
      availability.unknown += Number(group.availability_states?.unknown || 0);
    }
    moduleDetails = [
      { label: "渠道标识", value: channels.size ? [...channels].join(" / ") : String(attrs.channel_ids || "—") },
      { label: "链接状态", value: availabilityLabel(availability) },
    ];
  } else if (domain.capabilities.includes("resources")) {
    moduleDetails = [
      { label: "资源快照", value: String(attrs.resource_version || currentVersion) },
      { label: "主 / 初始", value: `${Number(attrs.main_file_count || 0).toLocaleString()} / ${Number(attrs.initial_file_count || 0).toLocaleString()}` },
      { label: "素材 / 语音", value: `${Number(attrs.asset_count || 0).toLocaleString()} / ${Number(attrs.voice_count || 0).toLocaleString()}` },
      { label: "Unity", value: String(attrs.unity_version || "—") },
    ];
  } else if (domain.adapter === "perfectworld_patcher") {
    const decodedFiles = Number(attrs.decoded_file_count || 0);
    const patchObjects = Number(attrs.patch_object_count || 0);
    const reslistSize = Number(attrs.reslist_size || 0);
    const configResSize = Number(attrs.config_res_size || 0);
    moduleDetails = [
      { label: "版本族", value: version.split(".").slice(0, 2).join(".") },
      { label: "完整文件", value: `${decodedFiles.toLocaleString()} 个 / ${formatBytes(summary.packed_size)}` },
      { label: "ResList ZIP", value: formatBytes(reslistSize) },
      { label: "配置资源", value: formatBytes(configResSize) },
    ];
  } else if (
    domain.adapter === "patchersdk"
    || (domain.capabilities.includes("files") && domainFeatureSupport(domain, "artifact_list"))
  ) {
    const releaseType = attrs.release_type === "major" ? " · 系列首个存档" : attrs.release_type === "patch" ? " · 后续存档" : "";
    moduleDetails = [
      { label: "版本族", value: `${version.split(".").slice(0, 2).join(".")}${releaseType}` },
      { label: "完整文件", value: `${countOf("file").toLocaleString()} 个 / ${formatBytes(sizeOf("file"))}` },
      { label: "补丁文件", value: `${countOf("patch").toLocaleString()} 个 / ${formatBytes(sizeOf("patch"))}` },
      { label: "清单", value: `${countOf("manifest").toLocaleString()} 个` },
    ];
  } else if (domain.adapter === "arknights") {
    moduleDetails = [
      { label: "接口体积", value: formatBytes(summary.unpacked_size) },
      { label: "文件校验", value: "game_files_md5" },
      { label: "完整分卷", value: `${countOf("package").toLocaleString()} 个` },
      { label: "Revision", value: `${summary.revision_count.toLocaleString()} 次` },
    ];
  } else if (domain.adapter === "hoyo") {
    const languageLabels: Record<string, string> = { "zh-cn": "中文", "en-us": "英语", "ja-jp": "日语", "ko-kr": "韩语" };
    const languages = Array.isArray(attrs.voice_languages)
      ? attrs.voice_languages.map((value) => languageLabels[String(value)] || String(value))
      : [];
    moduleDetails = [
      { label: "分发架构", value: distributionProfile(summary) },
      { label: "压缩包", value: `${countOf("package").toLocaleString()} 个` },
      ...(domainFeatureSupport(domain, "voice_language")
        ? [{ label: "语音语言", value: languages.length ? languages.join(" / ") : "不支持" }]
        : []),
      { label: "Chunk", value: `${countOf("chunk").toLocaleString()} 个` },
    ];
  } else if (domain.capabilities.includes("packages") && domain.capabilities.includes("patches")) {
    moduleDetails = [
      { label: "解压大小", value: formatBytes(summary.unpacked_size) },
      { label: "更新路径", value: `${Number(attrs.patch_route_count || 0).toLocaleString()} 条` },
      { label: "完整包", value: `${countOf("package").toLocaleString()} 个` },
      { label: "更新补丁", value: `${countOf("patch").toLocaleString()} 个` },
    ];
  } else if (
    (domainFeatureSupport(domain, "multi_cdn") && domainFeatureSupport(domain, "package_file_list"))
    || domain.adapter === "wuwa"
  ) {
    moduleDetails = [
      { label: "区服", value: `${String(attrs.region || "—").toUpperCase()} · ${String(attrs.channel || "—")}` },
      ...(mode === "files" ? [] : [{ label: "CDN 候选", value: `${Number(attrs.cdn_count || 0).toLocaleString()} 个` }]),
      { label: "文件清单", value: `${countOf("file").toLocaleString()} 个` },
      { label: "更新路线", value: `${Number(attrs.patch_route_count || countOf("patch")).toLocaleString()} 条` },
    ];
  }
  return { overviewMetrics, moduleDetails: moduleDetails.slice(0, 4), artifactKind: kind };
}
