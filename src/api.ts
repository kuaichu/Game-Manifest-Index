import type {
  AdminCatalog,
  AdminDomain,
  AdminEditableVersion,
  AdminEditableVersionPayload,
  AdminEditableVersionResult,
  AdminGame,
  AdminImportResult,
  AdminOperationJob,
  AdminOperationPayload,
  AdminSyncStatus,
  SyncRunStatus,
  SyncSchedule,
  ArchiveDomain,
  ArchiveLead,
  ArtifactPage,
  ArtifactTreePage,
  ComparePage,
  Game,
  ManualArtifactPayload,
  ManualVersionPayload,
  ProbeSchedule,
  ProbeStatus,
  ProbeUrlResult,
  VersionRecord,
  VersionSummary,
  ChunkManifestSummaryItem,
  ChunkManifestDetail,
  ChunkFilesPage,
  ChunkFileDetail,
  RetentionConfig,
  RetentionRunResult,
  RetentionStatus,
} from "./types";

const DEFAULT_API_BASE = "/api/v1";

/**
 * The API origin is a public build-time value.  Keep the same-origin default
 * so the existing FastAPI-served build and Vite proxy continue to work.
 */
export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  const base = configured || DEFAULT_API_BASE;
  return base.replace(/\/+$/, "") || DEFAULT_API_BASE;
}

export function apiUrl(path: string): string {
  return `${apiBase()}/${path.replace(/^\/+/, "")}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly url: string,
    public readonly code = "request_failed",
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorEnvelope = { error?: { code?: string; message?: string; details?: unknown } };

export function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null
    && "name" in error && (error as { name?: unknown }).name === "AbortError";
}

export async function requestJson<T>(path: string, signal?: AbortSignal, init: RequestInit = {}): Promise<T> {
  const url = apiUrl(path);
  let response: Response;
  try {
    response = await fetch(url, {
      cache: "no-cache",
      ...init,
      signal,
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        ...init.headers,
      },
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError("无法连接归档 API", 0, url, "network_error");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string; details?: unknown }; detail?: string | { code?: string; message?: string }; message?: string }
      | null;
    const errorMsg =
      payload?.error?.message ||
      (typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message) ||
      payload?.message ||
      `API 请求失败：HTTP ${response.status} ${response.statusText || ""}`.trim();
    const errorCode =
      payload?.error?.code ||
      (typeof payload?.detail === "object" ? payload.detail?.code : undefined) ||
      "http_error";
    throw new ApiError(
      errorMsg,
      response.status,
      url,
      errorCode,
      payload?.error?.details || payload?.detail,
    );
  }
  if (response.status === 204 || response.status === 205) {
    return undefined as unknown as T;
  }
  const text = await response.text();
  if (!text) {
    return undefined as unknown as T;
  }
  return JSON.parse(text) as T;
}

export function chunkContentUrl(domainId: string, version: string, identity: string, name: string): string {
  const search = new URLSearchParams({ identity, name });
  return apiUrl(`/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/chunk-content?${search.toString()}`);
}

type VersionIndexItem = {
  version: string;
  updated_at: string | null;
  available: boolean | null;
  size: number | null;
};

function versionIndexSummary(item: VersionIndexItem, index: number): VersionSummary {
  const state = item.available === true ? "available" : item.available === false ? "unavailable" : "unknown";
  const size = Number(item.size || 0);
  const updatedAt = item.updated_at;
  return {
    version: item.version,
    current_revision_id: index + 1,
    revision_count: 1,
    observed_at: updatedAt,
    source_released_at: updatedAt,
    packed_size: size,
    unpacked_size: 0,
    artifact_count: 1,
    artifact_kinds: { apk: { count: 1, size, availability_states: { [state]: 1 } } },
    availability_states: { available: Number(state === "available"), unavailable: Number(state === "unavailable"), unknown: Number(state === "unknown") },
    attributes: {},
    provenance: { source: "index_json" },
    is_visible: true,
  };
}

export const api = {
  games: (signal?: AbortSignal) => requestJson<Game[]>("/games", signal),
  domains: (gameId: string, signal?: AbortSignal) =>
    requestJson<ArchiveDomain[]>(`/games/${encodeURIComponent(gameId)}/domains`, signal),
  versions: async (domainId: string, signal?: AbortSignal) => {
    const response = await requestJson<{
      versions?: VersionIndexItem[];
      items?: VersionSummary[];
    }>(`/domains/${encodeURIComponent(domainId)}/versions`, signal);
    return response.versions?.map(versionIndexSummary) || response.items || [];
  },
  versionRecord: (domainId: string, version: string, signal?: AbortSignal) =>
    requestJson<VersionRecord>(`/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}`, signal),
  leads: async (domainId: string, signal?: AbortSignal) => {
    const response = await requestJson<{ items: ArchiveLead[] }>(`/domains/${encodeURIComponent(domainId)}/leads`, signal);
    return response.items;
  },
  artifacts: (
    domainId: string,
    version: string,
    options: { cursor?: string | null; query?: string; state?: string; kind?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const parameters = new URLSearchParams({ limit: String(options.limit || 100) });
    if (options.cursor) parameters.set("cursor", options.cursor);
    if (options.query) parameters.set("q", options.query);
    if (options.state) parameters.set("availability_state", options.state);
    if (options.kind) parameters.set("kind", options.kind);
    return requestJson<ArtifactPage>(`/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/artifacts?${parameters}`, signal);
  },
  allArtifacts: async (
    domainId: string,
    version: string,
    options: { query?: string; state?: string; kind?: string } = {},
    signal?: AbortSignal,
  ) => {
    const items: ArtifactPage["items"] = [];
    let cursor: string | null = null;
    do {
      const page = await api.artifacts(domainId, version, { ...options, cursor, limit: 500 }, signal);
      items.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor);
    return items;
  },
  artifactTree: (
    domainId: string,
    version: string,
    options: { kind: string; prefix?: string; cursor?: string | null; limit?: number; state?: string },
    signal?: AbortSignal,
  ) => {
    const parameters = new URLSearchParams({
      kind: options.kind,
      prefix: options.prefix || "",
      limit: String(options.limit || 100),
    });
    if (options.cursor) parameters.set("cursor", options.cursor);
    if (options.state) parameters.set("availability_state", options.state);
    return requestJson<ArtifactTreePage>(`/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/artifact-tree?${parameters}`, signal);
  },
  compare: (
    domainId: string,
    options: {
      fromVersion: string;
      toVersion: string;
      kind?: string;
      change?: "all" | "added" | "removed" | "changed";
      limit?: number;
      cursor?: string | null;
    },
    signal?: AbortSignal,
  ) => {
    const parameters = new URLSearchParams({
      from_version: options.fromVersion,
      to_version: options.toVersion,
      change: options.change || "all",
      limit: String(options.limit || 100),
    });
    if (options.kind) parameters.set("kind", options.kind);
    if (options.cursor) parameters.set("cursor", options.cursor);
    return requestJson<ComparePage>(`/domains/${encodeURIComponent(domainId)}/compare?${parameters}`, signal);
  },
  chunkManifestCollection: (domainId: string, signal?: AbortSignal) =>
    requestJson<{ items: ChunkManifestSummaryItem[] }>(`/domains/${encodeURIComponent(domainId)}/chunk-manifests`, signal),
  chunkManifests: (domainId: string, version: string, signal?: AbortSignal) =>
    requestJson<ChunkManifestDetail>(`/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/chunk-manifests`, signal),
  versionFiles: (
    domainId: string,
    version: string,
    params?: {
      source?: "package" | "chunk" | "auto" | string;
      identity?: string;
      path?: string;
      q?: string;
      limit?: number;
      cursor?: string | null;
    },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params?.source) search.set("source", params.source);
    if (params?.identity) search.set("identity", params.identity);
    if (params?.path !== undefined && params.path !== null && params.path !== "") search.set("path", params.path);
    if (params?.q) search.set("q", params.q);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const qs = search.toString();
    return requestJson<ChunkFilesPage>(
      `/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/files${qs ? `?${qs}` : ""}`,
      signal,
    );
  },
  versionFileDetail: (
    domainId: string,
    version: string,
    params: {
      source?: "package" | "chunk" | "auto" | string;
      identity?: string;
      path: string;
    },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params.source) search.set("source", params.source);
    if (params.identity) search.set("identity", params.identity);
    search.set("path", params.path);
    return requestJson<ChunkFileDetail>(
      `/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/file?${search.toString()}`,
      signal,
    );
  },
  chunkFiles: (
    domainId: string,
    version: string,
    identity: string,
    params?: { path?: string; q?: string; limit?: number; cursor?: string | null },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params?.path !== undefined && params.path !== null && params.path !== "") search.set("path", params.path);
    if (params?.q) search.set("q", params.q);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const qs = search.toString();
    return requestJson<ChunkFilesPage>(
      `/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/chunk-manifests/${encodeURIComponent(identity)}/files${qs ? `?${qs}` : ""}`,
      signal,
    );
  },
  chunkFileDetail: (
    domainId: string,
    version: string,
    identity: string,
    path: string,
    signal?: AbortSignal,
  ) =>
    requestJson<ChunkFileDetail>(
      `/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/chunk-manifests/${encodeURIComponent(identity)}/file?path=${encodeURIComponent(path)}`,
      signal,
    ),
};

export const adminApi = {
  auth: (token: string) => ({ Authorization: `Bearer ${token}` }),
  catalog: (token: string, signal?: AbortSignal) =>
    requestJson<AdminCatalog>("/admin/catalog", signal, { headers: adminApi.auth(token) }),
  versions: (domainId: string, token: string, signal?: AbortSignal) =>
    requestJson<{ items: VersionSummary[] }>(`/admin/domains/${encodeURIComponent(domainId)}/versions`, signal, { headers: adminApi.auth(token) }),
  createGame: (payload: Partial<AdminGame>, token: string, signal?: AbortSignal) =>
    requestJson<AdminGame>("/admin/games", signal, { method: "POST", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  updateGame: (gameId: string, payload: Partial<AdminGame>, token: string, signal?: AbortSignal) =>
    requestJson<AdminGame>(`/admin/games/${encodeURIComponent(gameId)}`, signal, { method: "PATCH", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  deleteGame: (gameId: string, token: string, signal?: AbortSignal) =>
    requestJson<void>(`/admin/games/${encodeURIComponent(gameId)}`, signal, { method: "DELETE", headers: adminApi.auth(token) }),
  createDomain: (payload: Partial<AdminDomain>, token: string, signal?: AbortSignal) =>
    requestJson<AdminDomain>("/admin/domains", signal, { method: "POST", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  updateDomain: (domainId: string, payload: Partial<AdminDomain>, token: string, signal?: AbortSignal) =>
    requestJson<AdminDomain>(`/admin/domains/${encodeURIComponent(domainId)}`, signal, { method: "PATCH", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  deleteDomain: (domainId: string, token: string, signal?: AbortSignal) =>
    requestJson<void>(`/admin/domains/${encodeURIComponent(domainId)}`, signal, { method: "DELETE", headers: adminApi.auth(token) }),
  setVersionVisibility: (domainId: string, version: string, isVisible: boolean, token: string, signal?: AbortSignal) =>
    requestJson<{ is_visible: boolean }>(`/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}`, signal, { method: "PATCH", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify({ is_visible: isVisible }) }),
  editableVersion: (domainId: string, version: string, token: string, signal?: AbortSignal) =>
    requestJson<AdminEditableVersion>(`/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/editable`, signal, { headers: adminApi.auth(token) }),
  updateEditableVersion: (
    domainId: string,
    version: string,
    payload: AdminEditableVersionPayload,
    token: string,
    signal?: AbortSignal,
  ) =>
    requestJson<AdminEditableVersionResult>(
      `/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/editable`,
      signal,
      {
        method: "PATCH",
        headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  deleteVersion: (domainId: string, version: string, token: string, signal?: AbortSignal) =>
    requestJson<void>(
      `/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}`,
      signal,
      {
        method: "DELETE",
        headers: adminApi.auth(token),
      },
    ),
  editArtifact: (domainId: string, version: string, payload: { action: "upsert" | "delete"; part: number; artifact?: ManualArtifactPayload | null }, token: string, signal?: AbortSignal) =>
    requestJson<AdminImportResult>(`/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/artifacts/edit`, signal, { method: "POST", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  addVersion: (domainId: string, payload: ManualVersionPayload, token: string, signal?: AbortSignal) =>
    requestJson<AdminImportResult>(`/admin/domains/${encodeURIComponent(domainId)}/versions`, signal, { method: "POST", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  syncStatus: (token: string, signal?: AbortSignal) =>
    requestJson<AdminSyncStatus>("/admin/sync-status", signal, { headers: adminApi.auth(token) }),
  syncRunStatus: (token: string, signal?: AbortSignal) =>
    requestJson<SyncRunStatus>("/admin/sync/status", signal, { headers: adminApi.auth(token) }),
  syncSchedule: (token: string, signal?: AbortSignal) =>
    requestJson<SyncSchedule>("/admin/sync/schedule", signal, { headers: adminApi.auth(token) }),
  saveSyncSchedule: (schedule: SyncSchedule, token: string, signal?: AbortSignal) =>
    requestJson<SyncSchedule>("/admin/sync/schedule", signal, {
      method: "PUT",
      headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    }),
  probeStatus: (token: string, signal?: AbortSignal) =>
    requestJson<ProbeStatus>("/admin/probe/status", signal, { headers: adminApi.auth(token) }),
  probeSchedule: (token: string, signal?: AbortSignal) =>
    requestJson<ProbeSchedule>("/admin/probe/schedule", signal, { headers: adminApi.auth(token) }),
  saveProbeSchedule: (payload: ProbeSchedule, token: string, signal?: AbortSignal) =>
    requestJson<ProbeSchedule>("/admin/probe/schedule", signal, { method: "PUT", headers: { ...adminApi.auth(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  probeUrl: (url: string, token: string, timeout = 10, artifactUrlId?: number, signal?: AbortSignal) =>
    requestJson<ProbeUrlResult>("/admin/probe/url", signal, {
      method: "POST",
      headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
      body: JSON.stringify({ url, timeout, ...(artifactUrlId ? { artifact_url_id: artifactUrlId } : {}) }),
    }),
  updateRetentionConfig: (payload: RetentionConfig, token: string, signal?: AbortSignal) =>
    requestJson<RetentionConfig>("/admin/retention/config", signal, {
      method: "PUT",
      headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getRetentionConfig: (token: string, signal?: AbortSignal) =>
    requestJson<RetentionConfig>("/admin/retention/config", signal, { headers: adminApi.auth(token) }),
  runRetention: (token: string, signal?: AbortSignal) =>
    requestJson<RetentionStatus>("/admin/retention/run", signal, {
      method: "POST",
      headers: adminApi.auth(token),
    }),
  getRetentionStatus: (token: string, signal?: AbortSignal) =>
    requestJson<RetentionStatus>("/admin/retention/status", signal, { headers: adminApi.auth(token) }),
  probeUrls: (urls: string[], token: string, timeout = 10, artifactUrlIds: number[] = [], signal?: AbortSignal) =>
    requestJson<{ items: ProbeUrlResult[] }>("/admin/probe/urls", signal, {
      method: "POST",
      headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
      body: JSON.stringify({ urls, timeout, ...(artifactUrlIds.length ? { artifact_url_ids: artifactUrlIds } : {}) }),
    }),
  probeVersion: (domainId: string, version: string, token: string, signal?: AbortSignal) =>
    requestJson<{ domain_id: string; version: string; summary: unknown }>(
      `/admin/domains/${encodeURIComponent(domainId)}/versions/${encodeURIComponent(version)}/probe`,
      signal,
      {
        method: "POST",
        headers: adminApi.auth(token),
      },
    ),
  startOperation: (payload: AdminOperationPayload, token: string, signal?: AbortSignal) =>
    requestJson<AdminOperationJob>("/admin/operations/start", signal, {
      method: "POST",
      headers: { ...adminApi.auth(token), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  operationStatus: (jobId: string, token: string, signal?: AbortSignal, after?: number) =>
    requestJson<AdminOperationJob>(`/admin/operations/${encodeURIComponent(jobId)}${after !== undefined ? `?after=${after}` : ""}`, signal, {
      headers: adminApi.auth(token),
    }),
  latestOperation: (token: string, signal?: AbortSignal) =>
    requestJson<AdminOperationJob>("/admin/operations/latest", signal, {
      headers: adminApi.auth(token),
    }),
  cancelOperation: (jobId: string, token: string, signal?: AbortSignal) =>
    requestJson<AdminOperationJob>(`/admin/operations/${encodeURIComponent(jobId)}/cancel`, signal, {
      method: "POST",
      headers: adminApi.auth(token),
    }),
};
