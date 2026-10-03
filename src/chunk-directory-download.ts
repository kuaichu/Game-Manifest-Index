import { api, chunkContentUrl } from "./api";
import { writeChunkFile, type ChunkDownloadProgress, type ChunkWritableSink } from "./chunk-download";
import type { ChunkDownloadPlanPage, ChunkFileDetail } from "./types";

const PLAN_PAGE_SIZE = 500;
const MAX_DIRECTORY_NAME_ATTEMPTS = 100;

export interface ChunkDirectoryFileHandle {
  createWritable(): Promise<ChunkWritableSink>;
}

/** The narrow part of the File System Access API needed by the downloader. */
export interface ChunkDirectoryHandle {
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<ChunkDirectoryHandle>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<ChunkDirectoryFileHandle>;
}

export interface DirectoryDownloadProgress {
  stage: "preparing" | "downloading";
  completedFiles: number;
  totalFiles: number;
  completedBytes: number;
  totalBytes: number;
  currentPath: string | null;
  chunkProgress?: ChunkDownloadProgress;
}

export interface ChunkDirectoryDownloadOptions {
  domainId: string;
  version: string;
  identities: string[];
  root: ChunkDirectoryHandle;
  baseName: string;
  signal: AbortSignal;
  onProgress?: (progress: DirectoryDownloadProgress) => void;
}

export interface ChunkDirectoryDownloadResult {
  directoryName: string;
  files: number;
  bytes: number;
}

export interface PlannedFile {
  identity: string;
  detail: ChunkFileDetail;
  path: string;
  size: number;
  md5: string;
}

export class ChunkDirectoryDownloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChunkDirectoryDownloadError";
  }
}

function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw abortError();
}

function hasErrorName(error: unknown, name: string): boolean {
  return typeof error === "object" && error !== null && "name" in error
    && (error as { name?: unknown }).name === name;
}

function isMissingEntry(error: unknown): boolean {
  return hasErrorName(error, "NotFoundError");
}

export function safePath(path: string): { path: string; key: string; segments: string[]; keys: string[] } {
  if (!path || path.startsWith("/") || path.includes("\\") || path.includes("\0")) {
    throw new ChunkDirectoryDownloadError(`不安全的文件路径：${path || "(empty)"}`);
  }

  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    throw new ChunkDirectoryDownloadError(`不安全的文件路径：${path}`);
  }

  for (const segment of segments) {
    if (/[<>:"|?*\u0000-\u001f]/.test(segment) || /[. ]$/.test(segment)) {
      throw new ChunkDirectoryDownloadError(`文件名不适用于 Windows：${path}`);
    }
    const deviceStem = segment.split(".", 1)[0];
    if (/^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$/i.test(deviceStem)) {
      throw new ChunkDirectoryDownloadError(`文件名使用了 Windows 保留设备名：${path}`);
    }
    if (segment.length > 255) {
      throw new ChunkDirectoryDownloadError(`文件名超过 255 个字符：${path}`);
    }
  }

  const keys = segments.map((segment) => segment.toLowerCase());
  return { path: segments.join("/"), key: keys.join("/"), segments, keys };
}

function requiredMd5(detail: ChunkFileDetail): string {
  const hash = detail.hash?.trim().toLowerCase();
  const md5 = detail.md5?.trim().toLowerCase();
  if (hash && md5 && hash !== md5) {
    throw new ChunkDirectoryDownloadError(`文件 ${detail.path} 的 hash 与 MD5 不一致`);
  }
  const value = hash || md5;
  if (!value || !/^[a-f0-9]{32}$/.test(value)) {
    throw new ChunkDirectoryDownloadError(`文件 ${detail.path} 缺少有效的完整文件 MD5`);
  }
  return value;
}

export function planFileConflicts(files: PlannedFile[], signal: AbortSignal): PlannedFile[] {
  const byPath = new Map<string, PlannedFile>();
  const directories = new Set<string>();

  for (const file of files) {
    throwIfAborted(signal);
    const parsed = safePath(file.detail.path);
    const size = file.detail.size;
    if (!Number.isSafeInteger(size) || size < 0) {
      throw new ChunkDirectoryDownloadError(`文件 ${parsed.path} 的大小无效`);
    }
    const md5 = requiredMd5(file.detail);
    const normalizedDetail: ChunkFileDetail = { ...file.detail, path: parsed.path, hash: md5, md5 };
    const normalized: PlannedFile = { ...file, detail: normalizedDetail, path: parsed.path, size, md5 };
    const previous = byPath.get(parsed.key);
    if (previous) {
      if (previous.size !== size || previous.md5 !== md5) {
        throw new ChunkDirectoryDownloadError(`组件文件路径冲突且内容不同：${parsed.path}`);
      }
      continue;
    }

    for (let depth = 1; depth < parsed.keys.length; depth++) {
      const ancestor = parsed.keys.slice(0, depth).join("/");
      if (byPath.has(ancestor)) {
        throw new ChunkDirectoryDownloadError(`文件与目录路径冲突：${parsed.path}`);
      }
    }
    if (directories.has(parsed.key)) {
      throw new ChunkDirectoryDownloadError(`文件与目录路径冲突：${parsed.path}`);
    }
    byPath.set(parsed.key, normalized);
    for (let depth = 1; depth < parsed.keys.length; depth++) {
      directories.add(parsed.keys.slice(0, depth).join("/"));
    }
  }

  return [...byPath.values()];
}

async function collectIdentity(
  domainId: string,
  version: string,
  identity: string,
  signal: AbortSignal,
): Promise<PlannedFile[]> {
  const files: PlannedFile[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let expectedTotal: number | null = null;
  let expectedSize: number | null = null;
  let associatedIdentity: string | null = null;

  while (true) {
    throwIfAborted(signal);
    const page: ChunkDownloadPlanPage = await api.chunkDownloadPlan(
      domainId,
      version,
      identity,
      { limit: PLAN_PAGE_SIZE, cursor },
      signal,
    );
    throwIfAborted(signal);
    if (!page || typeof page.identity !== "string" || !page.identity || !Array.isArray(page.items)) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 返回了无效的目录计划`);
    }
    if (!Number.isSafeInteger(page.total) || page.total < 0
      || !Number.isSafeInteger(page.total_size) || page.total_size < 0
      || (page.next_cursor !== null && (typeof page.next_cursor !== "string" || !page.next_cursor))) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 返回了无效的目录计划分页信息`);
    }
    if (associatedIdentity !== null && associatedIdentity !== page.identity) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划身份在分页期间发生变化`);
    }
    associatedIdentity = page.identity;
    if (expectedTotal !== null && (expectedTotal !== page.total || expectedSize !== page.total_size)) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划在分页期间发生变化`);
    }
    expectedTotal = page.total;
    expectedSize = page.total_size;

    for (const detail of page.items) {
      if (!detail || typeof detail.path !== "string" || detail.identity !== page.identity) {
        throw new ChunkDirectoryDownloadError(`身份 ${identity} 返回了无效的文件详情`);
      }
      files.push({ identity: page.identity, detail, path: detail.path, size: detail.size, md5: "" });
    }
    if (files.length > page.total) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 返回的文件数超过计划总数`);
    }
    if (page.next_cursor === null) {
      if (files.length !== page.total) {
        throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划未返回完整文件清单`);
      }
      const actualSize = files.reduce((sum, file) => {
        const next = sum + file.detail.size;
        if (!Number.isSafeInteger(next)) throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划总大小超出安全整数范围`);
        return next;
      }, 0);
      if (actualSize !== page.total_size) {
        throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划总大小与文件清单不一致`);
      }
      return files;
    }
    if (seenCursors.has(page.next_cursor)) {
      throw new ChunkDirectoryDownloadError(`身份 ${identity} 的目录计划游标重复`);
    }
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }
}

export async function createFreshDirectory(
  root: ChunkDirectoryHandle,
  baseName: string,
  signal: AbortSignal,
): Promise<{ directory: ChunkDirectoryHandle; name: string }> {
  const parsedBase = safePath(baseName);
  if (parsedBase.segments.length !== 1) {
    throw new ChunkDirectoryDownloadError("目录名称必须是单个安全文件名");
  }

  for (let attempt = 1; attempt <= MAX_DIRECTORY_NAME_ATTEMPTS; attempt++) {
    throwIfAborted(signal);
    const name = attempt === 1 ? parsedBase.path : `${parsedBase.path}-${attempt}`;
    try {
      await root.getDirectoryHandle(name);
      continue;
    } catch (error) {
      if (!isMissingEntry(error)) {
        // A file with this name also occupies the candidate, so try the next suffix.
        if (hasErrorName(error, "TypeMismatchError")) continue;
        throw error;
      }
    }
    try {
      const directory = await root.getDirectoryHandle(name, { create: true });
      return { directory, name };
    } catch (error) {
      // If the candidate changes type while being created, try its next suffix.
      if (hasErrorName(error, "TypeMismatchError") || isMissingEntry(error)) continue;
      throw error;
    }
  }
  throw new ChunkDirectoryDownloadError(`无法创建新的下载目录（已尝试 ${MAX_DIRECTORY_NAME_ATTEMPTS} 个名称）`);
}

export async function createParentDirectories(
  root: ChunkDirectoryHandle,
  segments: string[],
  signal: AbortSignal,
): Promise<ChunkDirectoryHandle> {
  let directory = root;
  for (const segment of segments) {
    throwIfAborted(signal);
    directory = await directory.getDirectoryHandle(segment, { create: true });
  }
  return directory;
}

export async function downloadChunkDirectory(
  options: ChunkDirectoryDownloadOptions,
): Promise<ChunkDirectoryDownloadResult> {
  const { domainId, version, identities, root, baseName, signal } = options;
  const report = options.onProgress || (() => undefined);
  throwIfAborted(signal);
  if (!domainId || !version || !Array.isArray(identities) || identities.some((identity) => !identity)) {
    throw new ChunkDirectoryDownloadError("目录下载参数无效");
  }

  report({ stage: "preparing", completedFiles: 0, totalFiles: 0, completedBytes: 0, totalBytes: 0, currentPath: null });
  const planned: PlannedFile[] = [];
  for (const identity of [...new Set(identities)]) {
    planned.push(...await collectIdentity(domainId, version, identity, signal));
  }
  const files = planFileConflicts(planned, signal);
  const totalBytes = files.reduce((sum, file) => {
    const next = sum + file.size;
    if (!Number.isSafeInteger(next)) throw new ChunkDirectoryDownloadError("目录总大小超过安全整数范围");
    return next;
  }, 0);
  throwIfAborted(signal);

  // All manifest pages, MD5s, paths, and cross-component collisions are validated
  // before the selected root is changed.
  const { directory, name: directoryName } = await createFreshDirectory(root, baseName, signal);
  throwIfAborted(signal);
  let completedFiles = 0;
  let completedBytes = 0;
  const notify = (currentPath: string | null, chunkProgress?: ChunkDownloadProgress): void => {
    report({
      stage: "downloading",
      completedFiles,
      totalFiles: files.length,
      completedBytes,
      totalBytes,
      currentPath,
      ...(chunkProgress ? { chunkProgress } : {}),
    });
  };
  notify(null);

  for (const file of files) {
    throwIfAborted(signal);
    const parsed = safePath(file.path);
    const parent = await createParentDirectories(directory, parsed.segments.slice(0, -1), signal);
    throwIfAborted(signal);

    const leaf = parsed.segments[parsed.segments.length - 1];
    try {
      await parent.getFileHandle(leaf);
      throw new ChunkDirectoryDownloadError(`目标目录中已存在文件，拒绝覆盖：${file.path}`);
    } catch (error) {
      if (error instanceof ChunkDirectoryDownloadError) throw error;
      if (!isMissingEntry(error)) throw error;
    }
    const handle = await parent.getFileHandle(leaf, { create: true });
    throwIfAborted(signal);
    const writable = await handle.createWritable();
    try {
      await writeChunkFile(
        file.detail,
        writable,
        signal,
        (progress) => notify(file.path, progress),
        (chunk) => chunkContentUrl(domainId, version, file.identity, chunk.name),
      );
    } catch (error) {
      if (signal.aborted) throw abortError();
      throw error;
    }
    throwIfAborted(signal);
    completedFiles++;
    completedBytes += file.size;
    notify(file.path);
  }

  return { directoryName, files: completedFiles, bytes: completedBytes };
}
