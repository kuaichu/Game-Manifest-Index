import { ref, type Ref } from "vue";
import { api, isAbortError } from "../api";
import { artifactKindForMode } from "../domain-presentation";
import type { ArchiveLead, Artifact, VersionRecord, VersionSummary } from "../types";

export interface ArchiveArtifactLoadContext {
  domainId: string;
  gameId: string;
  selectedVersion: string;
  mode: string;
  domainGameId?: string;
  domainAdapter?: string;
  versionsDomainId: string;
  hasSelectedVersion: boolean;
  query: string;
  availabilityState?: string;
  channelVersions: VersionSummary[];
  searchableMode: boolean;
  usesRemoteTree: boolean;
  usesArtifactTree: boolean;
}

export interface ArchiveArtifactsLoaderOptions {
  getContext: () => ArchiveArtifactLoadContext;
  resetPresentation: () => void;
  loadChunkState: (
    context: ArchiveArtifactLoadContext,
    signal: AbortSignal,
    isCurrent: () => boolean,
  ) => Promise<void>;
  setLeads: (leads: ArchiveLead[]) => void;
}

export interface ArchiveArtifactsLoaderState {
  artifacts: Ref<Artifact[]>;
  nextCursor: Ref<string | null>;
  loadingMore: Ref<boolean>;
  error: Ref<Error | null>;
  loadArtifacts: (append: boolean) => Promise<void>;
  invalidate: () => void;
  dispose: () => void;
}

function versionRecordState(record: VersionRecord): "available" | "unavailable" | "unknown" {
  return record.status.available === true
    ? "available"
    : record.status.available === false
      ? "unavailable"
      : "unknown";
}

function versionRecordArtifact(record: VersionRecord, id: number): Artifact {
  const state = versionRecordState(record);
  const verified = record.status.http_code !== null && record.status.last_checked_at !== null;
  const checksumType = record.checksum.md5 ? "md5" : record.checksum.crc64 ? "crc64" : null;
  const checksumValue = record.checksum.md5 || record.checksum.crc64;
  const current = {
    state,
    reason: record.status.http_code === null ? "无有效探测结果" : `HTTP ${record.status.http_code}`,
    confidence: state === "unknown" ? "low" as const : "high" as const,
    retained: false,
    checked_at: record.status.last_checked_at,
    source_kind: "live_probe",
    source_confidence: verified ? "high" : "low",
    observed_at: record.status.last_checked_at,
    expires_at: null,
    evidence_status: verified ? "verified" as const : "unverified" as const,
  };
  return {
    id,
    kind: "apk",
    name: record.filename,
    part: 1,
    size: record.size,
    checksum_type: checksumType,
    checksum_value: checksumValue,
    attributes: {
      vendor: record.vendor,
      game_id: record.game_id,
      channel: record.channel,
      version_code: record.version_code,
      etag: record.checksum.etag,
      crc64: record.checksum.crc64,
      http_code: record.status.http_code,
    },
    urls: [{
      id,
      url: record.url,
      priority: 0,
      source_kind: "official",
      provider: record.vendor,
      evidence_status: current.evidence_status,
      current,
    }],
  };
}

export function useArchiveArtifactsLoader(options: ArchiveArtifactsLoaderOptions): ArchiveArtifactsLoaderState {
  const artifacts = ref<Artifact[]>([]);
  const nextCursor = ref<string | null>(null);
  const loadingMore = ref(false);
  const error = ref<Error | null>(null);
  let artifactController: AbortController | null = null;
  let artifactRequestId = 0;

  function invalidate(): void {
    artifactController?.abort();
    artifactController = null;
    artifactRequestId += 1;
    loadingMore.value = false;
  }

  async function loadArtifacts(append: boolean): Promise<void> {
    const context = options.getContext();
    if (!context.domainId || !context.selectedVersion) return;
    if (
      context.domainGameId !== context.gameId ||
      context.versionsDomainId !== context.domainId ||
      !context.hasSelectedVersion
    ) {
      return;
    }
    const requestId = ++artifactRequestId;
    artifactController?.abort();
    const request = new AbortController();
    artifactController = request;
    const isCurrent = () => artifactRequestId === requestId && artifactController === request && !request.signal.aborted;
    if (!append) options.resetPresentation();
    error.value = null;
    loadingMore.value = append;
    try {
      if (context.mode === "chunks") {
        artifacts.value = [];
        nextCursor.value = null;
        const [chunkResult, artifactResult] = await Promise.allSettled([
          options.loadChunkState(context, request.signal, isCurrent),
          api.artifacts(
            context.domainId,
            context.selectedVersion,
            { query: context.query, kind: "chunk", limit: 100 },
            request.signal,
          ),
        ]);
        if (!isCurrent()) return;
        if (chunkResult.status === "rejected" && !isAbortError(chunkResult.reason)) {
          // Chunk state owns its own presentation error; keep artifact loading independent.
        }
        if (artifactResult.status === "fulfilled" && artifactResult.value?.items?.length) {
          artifacts.value = artifactResult.value.items;
        }
        return;
      }
      if (context.mode === "files" && context.domainAdapter === "hoyo") {
        artifacts.value = [];
        nextCursor.value = null;
        await options.loadChunkState(context, request.signal, isCurrent);
        return;
      }
      if (context.mode === "legacy") {
        artifacts.value = [];
        nextCursor.value = null;
        const loadedLeads = await api.leads(context.domainId, request.signal);
        if (!isCurrent()) return;
        options.setLeads(loadedLeads);
        return;
      }
      options.setLeads([]);
      if (context.mode === "compare" || context.usesRemoteTree) {
        artifacts.value = [];
        nextCursor.value = null;
        return;
      }
      if (context.usesArtifactTree) {
        const loadedArtifacts = await api.allArtifacts(
          context.domainId,
          context.selectedVersion,
          { kind: "file", query: context.query, state: context.availabilityState },
          request.signal,
        );
        if (!isCurrent()) return;
        artifacts.value = loadedArtifacts;
        nextCursor.value = null;
        return;
      }
      const baseVersion = context.selectedVersion;
      const channelTargets = context.channelVersions.length
        ? [baseVersion, ...context.channelVersions.map((item) => item.version)]
        : [baseVersion];
      if (context.mode === "apk") {
        const loaded: Artifact[] = [];
        const queryText = context.query.toLocaleLowerCase();
        for (const [index, version] of channelTargets.entries()) {
          if (!isCurrent()) return;
          const record = await api.versionRecord(context.domainId, version, request.signal);
          if (!isCurrent()) return;
          if (queryText && !JSON.stringify(record).toLocaleLowerCase().includes(queryText)) continue;
          if (context.availabilityState && versionRecordState(record) !== context.availabilityState) continue;
          loaded.push(versionRecordArtifact(record, index + 1));
        }
        if (!isCurrent()) return;
        artifacts.value = loaded;
        nextCursor.value = null;
        return;
      }
      if (channelTargets.length > 1) {
        const loaded: Artifact[] = [];
        for (const version of channelTargets) {
          if (!isCurrent()) return;
          const page = await api.artifacts(
            context.domainId,
            version,
            {
              query: context.searchableMode ? context.query : "",
              state: context.availabilityState,
              kind: artifactKindForMode(context.mode),
              limit: 500,
            },
            request.signal,
          );
          if (!isCurrent()) return;
          loaded.push(...page.items);
        }
        const seenArtifacts = new Set<string>();
        artifacts.value = loaded.filter((item) => {
          const key = String(item.name);
          if (seenArtifacts.has(key)) return false;
          seenArtifacts.add(key);
          return true;
        });
        nextCursor.value = null;
        return;
      }
      const page = await api.artifacts(
        context.domainId,
        context.selectedVersion,
        {
          cursor: append ? nextCursor.value : null,
          query: context.searchableMode ? context.query : "",
          state: context.availabilityState,
          kind: artifactKindForMode(context.mode),
          limit: 50,
        },
        request.signal,
      );
      if (!isCurrent()) return;
      artifacts.value = append ? [...artifacts.value, ...page.items] : page.items;
      nextCursor.value = page.next_cursor;
    } catch (reason) {
      if (!isCurrent() || isAbortError(reason)) return;
      error.value = reason instanceof Error ? reason : new Error(String(reason));
    } finally {
      if (requestId === artifactRequestId) loadingMore.value = false;
    }
  }

  return { artifacts, nextCursor, loadingMore, error, loadArtifacts, invalidate, dispose: invalidate };
}
