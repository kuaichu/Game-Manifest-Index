import type { OperationPlatformScope } from "./operation-scope";

export type AvailabilityState = "available" | "unavailable" | "unknown";
export type Confidence = "high" | "medium" | "low";
export type EvidenceStatus = "verified" | "stale" | "expired" | "unverified" | "no_evidence";

export interface Game {
  id: string;
  name: string;
  sub_name: string;
  platform: string;
  icon_source: string;
  version_count: number;
  latest_version: string | null;
  is_enabled?: boolean;
  sort_order?: number;
}

export interface ArchiveDomain {
  id: string;
  game_id: string;
  kind: string;
  platform: string;
  capabilities: string[];
  capability_contract?: {
    version_fields?: Record<string, "supported" | "unsupported">;
    artifact_fields?: Record<string, "supported" | "unsupported">;
    url_source_kinds?: string[];
    checksum_algorithms?: string[];
    availability_source_kinds?: string[];
    url_providers?: string[];
    features?: Record<string, "supported" | "unsupported">;
    actions?: Record<string, "conditional" | "unsupported">;
    live_probe?: boolean;
  };
  adapter: string;
  version_count: number;
  latest_version: string | null;
  source_current_version?: string | null;
  catalog_version_count?: number | null;
  is_enabled?: boolean;
  sort_order?: number;
}

export interface VersionSummary {
  version: string;
  current_revision_id: number;
  revision_count: number;
  observed_at: string | null;
  source_released_at?: string | null;
  source_updated_at?: string | null;
  archived_at?: string | null;
  imported_at?: string | null;
  packed_size: number;
  unpacked_size: number;
  artifact_count: number;
  artifact_kinds: Record<string, { count: number; size: number; availability_states?: Record<string, number> }>;
  availability_states: Record<string, number>;
  attributes: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  is_visible?: boolean;
}

export interface VersionRecord {
  vendor: string;
  game_id: string;
  platform: string;
  channel: string;
  version: string;
  version_code: number | null;
  filename: string;
  url: string;
  size: number;
  checksum: {
    etag: string | null;
    crc64: string | null;
    md5: string | null;
  };
  file_time: string | null;
  status: {
    http_code: number | null;
    available: boolean | null;
    last_checked_at: string | null;
  };
}

export interface AvailabilityCurrent {
  state: AvailabilityState;
  reason: string;
  confidence: Confidence;
  retained: boolean;
  checked_at: string | null;
  source_kind: string;
  source_confidence: string;
  observed_at: string | null;
  expires_at: string | null;
  as_of?: string | null;
  age_hours?: number | null;
  evidence_status: EvidenceStatus;
}

export interface ArtifactUrl {
  id: number;
  url: string;
  priority: number;
  source_kind: string;
  provider?: string;
  evidence_status: EvidenceStatus;
  current: AvailabilityCurrent | null;
}

export interface Artifact {
  id: number;
  kind: string;
  name: string;
  part: number;
  size: number;
  checksum_type: string | null;
  checksum_value: string | null;
  attributes: Record<string, string | number | boolean | null>;
  urls: ArtifactUrl[];
}

export interface ArtifactPage {
  items: Artifact[];
  next_cursor: string | null;
}

export interface ArtifactTreePage {
  prefix: string;
  folders: Array<{ name: string; path: string; artifact_count: number; total_size: number }>;
  items: Artifact[];
  next_cursor: string | null;
  manifest_url?: string | null;
  manifest_urls?: string[];
  base_url?: string | null;
  base_urls?: string[];
}

export interface CompareArtifact {
  name: string;
  part: number;
  kind: string;
  size: number;
  checksum_type: string | null;
  checksum_value: string | null;
  attributes: Record<string, string | number | boolean | null>;
}

export interface CompareItem {
  change: "added" | "removed" | "changed";
  identity: Record<string, string | number | boolean | null>;
  before: CompareArtifact | null;
  after: CompareArtifact | null;
}

export interface ComparePage {
  from_version: string;
  to_version: string;
  summary: { added: number; removed: number; changed: number; size_delta: number };
  items: CompareItem[];
  next_cursor: string | null;
}

export interface ArchiveLead {
  id: number;
  external_id: string;
  domain_id: string;
  platform: string;
  version: string | null;
  inferred_context: string | null;
  filename: string;
  generated_at: string | null;
  source_note: string | null;
  notes: string | null;
  capture_event_id: number | null;
  urls: Array<{
    id: number;
    url: string;
    source_kind: string;
    current_facts: Record<string, unknown>;
    archive_facts: Record<string, unknown>;
  }>;
}

// --- Administration types ---

export interface AdminGame extends Game {
  is_enabled: boolean;
}

export interface AdminDomain extends ArchiveDomain {
  is_enabled: boolean;
}

export interface AdminCatalog {
  games: AdminGame[];
  domains: AdminDomain[];
}

export interface AdminEditableArtifact {
  kind: string;
  name: string;
  part: number;
  size: number;
  checksum_type: string | null;
  checksum_value: string | null;
  attributes: Record<string, string | number | boolean | null>;
  urls: Array<{ id?: number; url: string; priority: number; source_kind: string }>;
}

export interface AdminEditableVersion {
  version: string;
  client_version: string;
  observed_at: string | null;
  file_created_at_override: string | null;
  file_path: string;
  unpacked_size: number;
  files_checksum_type: string | null;
  files_checksum_value: string | null;
  attributes: Record<string, unknown>;
  is_visible: boolean;
  artifacts: AdminEditableArtifact[];
}

export interface AdminEditableVersionPayload {
  client_version?: string;
  observed_at?: string | null;
  file_created_at_override?: string | null;
  file_path?: string;
  unpacked_size?: number | null;
  files_checksum_type?: string | null;
  files_checksum_value?: string | null;
  attributes?: Record<string, unknown>;
  source_note?: string | null;
  artifacts?: ManualArtifactPayload[];
}

export interface AdminEditableVersionResult extends AdminImportResult {
  changed?: boolean;
  revision_created?: boolean;
  revision_id?: number | null;
}

export interface ManualArtifactPayload {
  kind: string;
  name: string;
  part: number;
  size: number;
  checksum_type?: string | null;
  checksum_value?: string | null;
  attributes?: Record<string, unknown>;
  urls: Array<{ url: string; priority: number; source_kind: string }>;
}

export interface ManualVersionPayload {
  version: string;
  client_version?: string;
  observed_at?: string;
  file_path?: string;
  unpacked_size?: number | null;
  files_checksum_type?: string | null;
  files_checksum_value?: string | null;
  source_note?: string | null;
  attributes?: Record<string, unknown>;
  artifacts: ManualArtifactPayload[];
}

export interface AdminImportResult {
  domain_id: string;
  version: string;
  revisions_created: number;
  revisions_reused: number;
  capture_event_id: number;
  changed?: boolean;
  revision_created?: boolean;
  revision_id?: number | null;
  probe_error?: string | null;
}

export interface SyncSchedule {
  enabled: boolean;
  times: string[];
}

export interface SyncRunResponse {
  status: string;
  log_path?: string;
}

export interface ProbeUrlResult {
  artifact_url_id?: number | null;
  url: string;
  ok: boolean;
  status?: number | null;
  error?: string | null;
  reason?: string | null;
  content_type?: string | null;
  size?: number | null;
  etag?: string | null;
  last_modified?: string | null;
  checked_at?: string;
  persisted?: boolean;
  adapter?: string | null;
}
export interface SyncRunStatus {
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  log_path?: string;
  running: boolean;
  result?: {
    ok: boolean;
    log_tail?: string;
    updates_text?: string;
  } | null;
}

export interface AdminSyncStatus {
  approved_snapshots: string[];
  latest_snapshot: string | null;
  latest_refresh: {
    status?: string;
    started_at?: string;
    completed_at?: string;
    families?: Record<string, { status?: string }>;
    failures?: Record<string, unknown>;
    exit_code?: number;
  } | null;
}

export interface ProbeSchedule {
  enabled: boolean;
  interval_hours: number;
  mode: "normal" | "full";
}

export interface RetentionConfig {
  cache_days: number;
  observation_days: number;
  interval_hours: number;
}

export interface RetentionRunResult {
  cache_deleted: number;
  temp_deleted: number;
  operation_deleted: number;
  observations_deleted: number;
  errors: number;
  skipped: number;
}

export interface RetentionStatus {
  started_at: string | null;
  finished_at: string | null;
  source: "startup" | "scheduled" | "manual" | string;
  result: RetentionRunResult | null;
  error: string | null;
}

export interface ProbeStatus {
  status: "idle" | "running" | "finished";
  mode: string;
  started_at?: string | null;
  finished_at?: string | null;
  family: string;
  log_path?: string;
  log: string[];
}

export interface AdminOperationPayload {
  actions: ("discover" | "probe")[];
  game_ids?: string[];
  all_games?: boolean;
  timeout?: number;
  workers?: number;
  scope?: OperationPlatformScope;
}

export interface DiscoverResultItem {
  game_id: string;
  ok: boolean;
  version: string | null;
  new: boolean;
  available: boolean | null;
  path: string | null;
  error: string | null;
  platform?: string | null;
  scope?: string | null;
  status?: string | null;
  skipped?: boolean;
  supported?: boolean;
  unsupported?: boolean;
}

export interface DiscoverResultSummary {
  selected: number;
  succeeded: number;
  failed: number;
  new_versions: number;
  cancelled?: boolean;
  skipped?: number;
  unsupported?: number;
  items: DiscoverResultItem[];
}

export interface ProbeResultItem {
  game_id: string;
  version: string;
  ok: boolean;
  available: boolean | null;
  adapter: string | null;
  error: string | null;
  platform?: string | null;
  kind?: string | null;
  url?: string | null;
  artifact_index?: number | null;
  url_index?: number | null;
}

export interface ProbeResultSummary {
  checked: number;
  selected?: number;
  available: number;
  available_urls?: number;
  unavailable: number;
  unknown: number;
  failed: number;
  cancelled?: boolean;
  checked_urls?: number;
  items: ProbeResultItem[];
}

export interface AdminOperationResult {
  actions: ("discover" | "probe")[];
  game_ids: string[];
  scope?: OperationPlatformScope | null;
  discover: DiscoverResultSummary | null;
  probe: ProbeResultSummary | null;
}

export interface AdminOperationJob {
  job_id: string;
  status: "running" | "cancelling" | "cancelled" | "finished" | "failed";
  phase: "discover" | "probe" | null;
  actions: ("discover" | "probe")[];
  game_ids: string[];
  scope?: OperationPlatformScope | null;
  log_total?: number;
  completed: number;
  total: number;
  phase_completed: number;
  phase_total: number;
  succeeded: number;
  failed: number;
  current: { action: string; game_id: string | null; version: string | null } | null;
  started_at: string;
  finished_at: string | null;
  result: AdminOperationResult | null;
  error: string | null;
  logs: string[];
}

export interface ChunkManifestSummaryItem {
  version: string;
  path: string;
  build_id: string;
  manifest_count: number;
  file_count: number;
  chunk_count: number;
  compressed_size: number;
  uncompressed_size: number;
  components: string[];
  languages: string[];
  imported_at: string;
  manifest_modified_at?: string;
}

export interface ChunkManifestEntry {
  category?: {
    id: number;
    name: string;
  };
  manifest_id: string;
  source_record_id?: number;
  manifest: {
    id: string;
    checksum: string;
    compressed_size: number;
    uncompressed_size: number;
  };
  component: string;
  language: string | null;
  matching_field: string;
  stats: {
    compressed_size: number;
    uncompressed_size: number;
    file_count: number;
    chunk_count: number;
  };
  deduplicated_stats?: {
    compressed_size: number;
    uncompressed_size: number;
    file_count: number;
    chunk_count: number;
  };
  manifest_download?: {
    url_prefix: string;
    url_suffix: string;
    compression?: number;
    encryption?: number;
    password?: string;
  };
  chunk_download?: {
    url_prefix: string;
    url_suffix: string;
    compression?: number;
    encryption?: number;
    password?: string;
  };
  last_modified_at?: string;
}

export interface ChunkManifestDetail {
  schema_version?: number;
  vendor: string;
  game_id: string;
  platform: string;
  domain_id: string;
  version: string;
  build_id: string;
  tag?: string;
  diff_tags?: string[];
  manifests: ChunkManifestEntry[];
  provenance?: {
    source_kind?: string;
    source_name?: string;
    source_url?: string;
    imported_at?: string;
  };
}

export interface ChunkFileItem {
  type?: "file" | "directory";
  name: string;
  path: string;
  size?: number;
  hash?: string;
  md5?: string;
  chunk_count?: number | null;
  file_count?: number;
  download_url?: string;
}

export interface ChunkFilesTotals {
  files: number;
  directories: number;
  size: number;
}

export interface ChunkFilesPage {
  source?: string;
  fetch_mode?: string;
  identity: string;
  path: string;
  q: string | null;
  items: ChunkFileItem[];
  total: number;
  next_cursor: string | null;
  totals?: ChunkFilesTotals;
  network_bytes?: number;
  range_bytes?: number;
}

export interface ChunkFileChunkItem {
  name: string;
  hash: string;
  offset: number;
  size: number;
  size_decompressed: number;
}

export interface ChunkFileDetail {
  source?: string;
  fetch_mode?: string;
  identity: string;
  name: string;
  path: string;
  size: number;
  hash?: string;
  md5?: string;
  download_url?: string;
  chunk_count?: number | null;
  chunks?: ChunkFileChunkItem[];
  network_bytes?: number;
  range_bytes?: number;
  chunk_download?: {
    url_prefix: string;
    url_suffix: string;
    compression?: number;
    encryption?: number;
    password?: string;
  };
}
