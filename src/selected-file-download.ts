import SparkMD5 from "spark-md5";
import { api, chunkContentUrl, fileContentUrl } from "./api";
import { writeChunkFile, type ChunkWritableSink } from "./chunk-download";
import { createFreshDirectory, createParentDirectories, planFileConflicts, safePath, type ChunkDirectoryHandle, type DirectoryDownloadProgress, type PlannedFile } from "./chunk-directory-download";
import type { ChunkFileDetail } from "./types";

export interface SelectedFileContext {
  domainId: string;
  version: string;
  source: "package" | "chunk";
  identity: string;
  paths: string[];
  signal: AbortSignal;
  recipe?: ChunkFileDetail["chunk_download"];
}

function check(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
}

async function abortable<T>(signal: AbortSignal, action: () => Promise<T>): Promise<T> {
  check(signal);
  let onAbort!: () => void;
  const aborted = new Promise<never>((_, reject) => { onAbort = () => reject(new DOMException("Aborted", "AbortError")); });
  signal.addEventListener("abort", onAbort, { once: true });
  try { return await Promise.race([action(), aborted]); }
  finally { signal.removeEventListener("abort", onAbort); }
}

/** Resolve precisely the selected paths, never the whole manifest or unseen pages. */
export async function selectedFilePlan(context: SelectedFileContext): Promise<PlannedFile[]> {
  const files: PlannedFile[] = [];
  for (const path of [...new Set(context.paths)]) {
    check(context.signal);
    safePath(path);
    const detail = await api.versionFileDetail(context.domainId, context.version, {
      source: context.source, identity: context.identity, path,
    }, context.signal);
    check(context.signal);
    if (detail.path !== path) throw new Error(`文件详情路径与选择不一致：${path}`);
    const normalized = context.source === "chunk" && !detail.chunk_download
      ? { ...detail, chunk_download: context.recipe } : detail;
    if (context.source === "chunk" && !normalized.chunk_download) throw new Error(`文件缺少 Chunk 合成规则：${path}`);
    if (context.source === "package" && !detail.download_url) throw new Error(`文件没有官方直链：${path}`);
    files.push({ identity: detail.identity, detail: normalized, path, size: detail.size, md5: "" });
  }
  return planFileConflicts(files, context.signal);
}

/** Raw file bytes only; Chunk synthesis has its own writer. Memory is bounded by stream chunks. */
export async function writeDirectFile(detail: ChunkFileDetail, url: string, writable: ChunkWritableSink, signal: AbortSignal, onProgress: (bytes: number) => void = () => undefined): Promise<void> {
  const md5 = new SparkMD5.ArrayBuffer();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const cancel = () => { void reader?.cancel().catch(() => undefined); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    check(signal);
    if (!Number.isSafeInteger(detail.size) || detail.size < 0) throw new Error("文件大小无效");
    const expected = detail.md5 || detail.hash;
    if (!expected || !/^[a-f0-9]{32}$/i.test(expected) || (detail.md5 && detail.hash && detail.md5.toLowerCase() !== detail.hash.toLowerCase())) throw new Error("缺少有效或一致的完整文件 MD5");
    const response = await fetch(url, { signal });
    reader = response.body?.getReader();
    if (!response.ok) throw new Error(`文件下载失败：HTTP ${response.status}`);
    const length = response.headers.get("content-length");
    if (length !== null && Number(length) !== detail.size) throw new Error("完整文件大小校验失败");
    if (!response.body) throw new Error("文件下载没有可读取的数据流");
    let received = 0;
    while (true) {
      const { value, done } = await abortable(signal, () => reader!.read());
      check(signal);
      if (done) break;
      received += value.byteLength;
      if (received > detail.size) throw new Error("完整文件大小校验失败");
      const buffer = value.slice().buffer as ArrayBuffer;
      await abortable(signal, () => writable.write(buffer));
      check(signal);
      md5.append(buffer);
      onProgress(received);
    }
    if (received !== detail.size) throw new Error("完整文件大小校验失败");
    if (md5.end() !== expected.toLowerCase()) throw new Error("完整文件 MD5 校验失败");
    await abortable(signal, () => writable.close());
  } catch (error) {
    try { await writable.abort(error); } catch { /* Keep the original failure. */ }
    throw error;
  } finally {
    signal.removeEventListener("abort", cancel);
    try { await reader?.cancel(); } catch { /* The upstream may have disconnected. */ }
    reader?.releaseLock();
    md5.destroy();
  }
}

export function selectedFileExport(context: Pick<SelectedFileContext, "domainId" | "version" | "source" | "identity">, files: PlannedFile[]): { text: string; extension: string; mime: string } {
  if (context.source === "package") {
    return { text: files.map((file) => file.detail.download_url).join("\n"), extension: "txt", mime: "text/plain;charset=utf-8" };
  }
  return {
    text: JSON.stringify({ type: "chunk-synthesis-plan", domain_id: context.domainId, version: context.version,
      identity: context.identity, files: files.map((file) => ({ path: file.path, size: file.size, md5: file.md5,
        identity: file.identity, chunk_download: file.detail.chunk_download, chunks: file.detail.chunks || [] })) }, null, 2),
    extension: "json", mime: "application/json;charset=utf-8",
  };
}

export async function downloadSelectedFiles(context: SelectedFileContext & { root: ChunkDirectoryHandle; baseName: string; onProgress?: (progress: DirectoryDownloadProgress) => void }): Promise<{ directoryName: string; files: number; bytes: number }> {
  const report = context.onProgress || (() => undefined);
  report({ stage: "preparing", completedFiles: 0, totalFiles: context.paths.length, completedBytes: 0, totalBytes: 0, currentPath: null });
  const files = await selectedFilePlan(context);
  if (!files.length) throw new Error("请先选择文件");
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  if (!Number.isSafeInteger(totalBytes)) throw new Error("文件总大小超出安全整数范围");
  const { directory, name } = await createFreshDirectory(context.root, context.baseName, context.signal);
  let completedFiles = 0; let completedBytes = 0;
  const notify = (currentPath: string | null, bytes = 0, total = 0) => report({ stage: "downloading", completedFiles, totalFiles: files.length,
    completedBytes, totalBytes, currentPath, ...(currentPath ? { chunkProgress: { completed: 0, total: 0, receivedBytes: bytes, totalBytes: total } } : {}) });
  for (const file of files) {
    check(context.signal);
    const { segments } = safePath(file.path);
    const parent = await createParentDirectories(directory, segments.slice(0, -1), context.signal);
    const leaf = segments[segments.length - 1];
    try { await parent.getFileHandle(leaf); throw new Error(`目标目录中已存在文件，拒绝覆盖：${file.path}`); }
    catch (error) { if (!(error instanceof DOMException) || error.name !== "NotFoundError") throw error; }
    check(context.signal);
    const handle = await parent.getFileHandle(leaf, { create: true });
    check(context.signal);
    const writable = await handle.createWritable();
    if (context.source === "chunk") {
      await writeChunkFile(file.detail, writable, context.signal, (progress) => notify(file.path, progress.receivedBytes, progress.totalBytes),
        (chunk) => chunkContentUrl(context.domainId, context.version, file.identity, chunk.name));
    } else {
      await writeDirectFile(file.detail, fileContentUrl(context.domainId, context.version, context.identity, file.path), writable, context.signal,
        (bytes) => notify(file.path, bytes, file.size));
    }
    check(context.signal);
    completedFiles++; completedBytes += file.size;
    notify(null);
  }
  return { directoryName: name, files: completedFiles, bytes: completedBytes };
}
