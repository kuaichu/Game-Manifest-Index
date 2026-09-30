import { Decompress as ZstdDecompress } from "fzstd";
import SparkMD5 from "spark-md5";
import type { ChunkFileDetail, ChunkFileChunkItem } from "./types";

export const MAX_BROWSER_SYNTHESIS_SIZE = 512 * 1024 * 1024;
const MAX_CONCURRENCY = 4;
export interface ChunkDownloadProgress { completed: number; total: number; receivedBytes: number; totalBytes: number; }
export interface ChunkWritableSink { write(data: ArrayBuffer): Promise<void>; close(): Promise<void>; abort(reason?: unknown): Promise<void>; }
export class ChunkDownloadError extends Error { constructor(message: string) { super(message); this.name = "ChunkDownloadError"; } }
function abortError(): DOMException { return new DOMException("Aborted", "AbortError"); }
function digest(value: Uint8Array): string { return SparkMD5.ArrayBuffer.hash(value.slice().buffer as ArrayBuffer); }

async function abortable<T>(signal: AbortSignal, action: () => Promise<T>): Promise<T> {
  if (signal.aborted) throw abortError();
  let rejectAbort!: (reason: DOMException) => void;
  const aborted = new Promise<never>((_, reject) => { rejectAbort = reject; });
  const onAbort = () => rejectAbort(abortError());
  signal.addEventListener("abort", onAbort, { once: true });
  try { return await Promise.race([action(), aborted]); }
  finally { signal.removeEventListener("abort", onAbort); }
}

function decompressZstd(input: Uint8Array, expected: number): Uint8Array {
  const output = new Uint8Array(expected);
  let written = 0;
  const decoder = new ZstdDecompress((part) => {
    if (written + part.byteLength > expected || written + part.byteLength > MAX_BROWSER_SYNTHESIS_SIZE) {
      throw new ChunkDownloadError("Chunk 解压输出超过声明大小");
    }
    output.set(part, written);
    written += part.byteLength;
  });
  decoder.push(input, true);
  if (written !== expected) throw new ChunkDownloadError("Chunk 解压大小校验失败");
  return output;
}

export function chunkUrl(recipe: NonNullable<ChunkFileDetail["chunk_download"]>, name: string): string {
  if (!name || /[\u0000-\u0020\u007f]/.test(name)) throw new ChunkDownloadError("Chunk 名称无效");
  if (typeof recipe.url_prefix !== "string" || typeof recipe.url_suffix !== "string") throw new ChunkDownloadError("Chunk 下载规则无效");
  const parsed = new URL(recipe.url_prefix);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) throw new ChunkDownloadError("Chunk 下载规则必须是无查询参数的 HTTPS 地址");
  if (/[\u0000-\u0020\u007f]/.test(recipe.url_suffix) || !/^(?:|[/?#])/.test(recipe.url_suffix)) throw new ChunkDownloadError("Chunk URL 后缀无效");
  const url = new URL(`${recipe.url_prefix.replace(/\/+$/, "")}/${encodeURIComponent(name)}${recipe.url_suffix}`);
  if (url.protocol !== "https:" || url.username || url.password) throw new ChunkDownloadError("Chunk 下载地址不安全");
  return url.toString();
}

function validateDetail(detail: ChunkFileDetail, maxFileSize = MAX_BROWSER_SYNTHESIS_SIZE): ChunkFileChunkItem[] {
  if (!Number.isSafeInteger(detail.size) || detail.size < 0 || detail.size > maxFileSize) throw new ChunkDownloadError(detail.size > maxFileSize ? "文件超过 512 MiB，暂不支持浏览器合成" : "文件大小无效");
  for (const chunk of detail.chunks || []) {
    if (![chunk.offset, chunk.size, chunk.size_decompressed].every((v) => Number.isSafeInteger(v) && v >= 0)) throw new ChunkDownloadError("Chunk 元数据无效");
    if (!Number.isSafeInteger(chunk.offset + chunk.size_decompressed) || chunk.offset + chunk.size_decompressed > detail.size) throw new ChunkDownloadError("Chunk 超出文件范围");
    if (chunk.size > MAX_BROWSER_SYNTHESIS_SIZE || chunk.size_decompressed > MAX_BROWSER_SYNTHESIS_SIZE) throw new ChunkDownloadError("Chunk 超过浏览器合成限制");
  }
  const chunks = [...(detail.chunks || [])].sort((a, b) => a.offset - b.offset);
  let cursor = 0;
  for (const chunk of chunks) { if (chunk.offset !== cursor) throw new ChunkDownloadError(chunk.offset < cursor ? "Chunk 存在重叠" : "Chunk 存在缺口"); cursor = chunk.offset + chunk.size_decompressed; }
  if (cursor !== detail.size) throw new ChunkDownloadError("Chunk 未覆盖完整文件");
  return chunks;
}

function validateRecipe(detail: ChunkFileDetail): NonNullable<ChunkFileDetail["chunk_download"]> {
  const recipe = detail.chunk_download;
  if (!recipe) throw new ChunkDownloadError("缺少 Chunk 下载规则");
  if ((recipe.encryption !== undefined && recipe.encryption !== 0) || recipe.password !== undefined) throw new ChunkDownloadError("该 Chunk 使用加密或密码，暂不支持浏览器合成");
  if (recipe.compression !== undefined && recipe.compression !== 0 && recipe.compression !== 1) throw new ChunkDownloadError(`不支持的 Chunk 压缩方式：${recipe.compression}`);
  return recipe;
}

function compressedTotal(chunks: ChunkFileChunkItem[], max = Number.MAX_SAFE_INTEGER): number {
  const total = chunks.reduce((sum, chunk) => sum + chunk.size, 0);
  if (!Number.isSafeInteger(total) || total > max) throw new ChunkDownloadError(max === MAX_BROWSER_SYNTHESIS_SIZE ? "Chunk 总压缩体积超过浏览器限制" : "Chunk 总压缩体积无效");
  return total;
}

async function readResponse(response: Response, expected: number, signal: AbortSignal, onBytes: (n: number) => void): Promise<Uint8Array> {
  if (!response.ok) throw new ChunkDownloadError(`Chunk 请求失败（HTTP ${response.status}）`);
  const length = response.headers.get("content-length"); const declared = length === null ? NaN : Number(length);
  if (Number.isFinite(declared) && declared > expected) throw new ChunkDownloadError("Chunk 超过声明大小");
  if (!response.body) { if (!Number.isFinite(declared)) throw new ChunkDownloadError("Chunk 缺少长度声明"); const bytes = new Uint8Array(await abortable(signal, () => response.arrayBuffer())); if (bytes.byteLength > expected) throw new ChunkDownloadError("Chunk 超过声明大小"); onBytes(bytes.byteLength); if (bytes.byteLength !== expected) throw new ChunkDownloadError("Chunk 压缩大小校验失败"); return bytes; }
  const reader = response.body.getReader(); const result = new Uint8Array(expected); let total = 0;
  let rejectAbort!: (reason: DOMException) => void;
  const aborted = new Promise<never>((_, reject) => { rejectAbort = reject; });
  const onAbort = () => { rejectAbort(abortError()); void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", onAbort, { once: true });
  try { while (true) { if (signal.aborted) throw abortError(); const item = await Promise.race([reader.read(), aborted]); if (item.done) break; if (item.value) { if (total + item.value.byteLength > expected) throw new ChunkDownloadError("Chunk 超过声明大小"); result.set(item.value, total); total += item.value.byteLength; onBytes(item.value.byteLength); } } }
  finally { signal.removeEventListener("abort", onAbort); void reader.cancel().catch(() => undefined); }
  if (total !== expected) throw new ChunkDownloadError("Chunk 压缩大小校验失败");
  return result;
}

async function downloadChunk(chunk: ChunkFileChunkItem, recipe: NonNullable<ChunkFileDetail["chunk_download"]>, signal: AbortSignal, onBytes: (n: number) => void, urlForChunk: (chunk: ChunkFileChunkItem) => string): Promise<Uint8Array> {
  const response = await abortable(signal, () => fetch(urlForChunk(chunk), { signal }));
  const compressed = await readResponse(response, chunk.size, signal, onBytes);
  let decompressed: Uint8Array;
  try { decompressed = recipe.compression === 1 ? decompressZstd(compressed, chunk.size_decompressed) : compressed; }
  catch (error) { if (error instanceof ChunkDownloadError) throw error; throw new ChunkDownloadError(`Chunk ${chunk.name} 解压失败`); }
  if (decompressed.byteLength !== chunk.size_decompressed) throw new ChunkDownloadError(`Chunk ${chunk.name} 解压大小校验失败`);
  if (typeof chunk.hash !== "string" || digest(decompressed) !== chunk.hash.toLowerCase()) throw new ChunkDownloadError(`Chunk ${chunk.name} MD5 校验失败`);
  return decompressed;
}

export async function writeChunkFile(detail: ChunkFileDetail, writable: ChunkWritableSink, signal: AbortSignal, onProgress: (p: ChunkDownloadProgress) => void = () => undefined, urlForChunk: (chunk: ChunkFileChunkItem) => string = (chunk) => chunkUrl(detail.chunk_download!, chunk.name)): Promise<void> {
  let md5: SparkMD5.ArrayBuffer | undefined;
  try {
    if (signal.aborted) throw abortError();
    const chunks = validateDetail(detail, Number.MAX_SAFE_INTEGER);
    const recipe = validateRecipe(detail);
    if (detail.hash !== undefined && detail.md5 !== undefined && (typeof detail.hash !== "string" || typeof detail.md5 !== "string" || detail.hash.toLowerCase() !== detail.md5.toLowerCase())) throw new ChunkDownloadError("完整文件 MD5 字段冲突");
    const expectedHash = detail.hash || detail.md5;
    if (typeof expectedHash !== "string" || !/^[a-f0-9]{32}$/i.test(expectedHash)) throw new ChunkDownloadError("缺少有效的完整文件 MD5");
    const totalBytes = compressedTotal(chunks);
    md5 = new SparkMD5.ArrayBuffer(); let completed = 0; let receivedBytes = 0;
    for (const chunk of chunks) {
      if (signal.aborted) throw abortError();
      const bytes = await downloadChunk(chunk, recipe, signal, (n) => { receivedBytes += n; onProgress({ completed, total: chunks.length, receivedBytes, totalBytes }); }, urlForChunk);
      if (signal.aborted) throw abortError();
      const buffer = bytes.buffer as ArrayBuffer;
      await abortable(signal, () => writable.write(buffer));
      if (signal.aborted) throw abortError();
      md5.append(buffer);
      completed++;
      onProgress({ completed, total: chunks.length, receivedBytes, totalBytes });
    }
    if (signal.aborted) throw abortError();
    if (md5.end() !== expectedHash.toLowerCase()) throw new ChunkDownloadError("完整文件 MD5 校验失败");
    await abortable(signal, () => writable.close());
  } catch (error) {
    try { await writable.abort(error); } catch { /* Preserve the download failure. */ }
    throw error;
  } finally { md5?.destroy(); }
}

export async function synthesizeChunkFile(detail: ChunkFileDetail, signal: AbortSignal, onProgress: (p: ChunkDownloadProgress) => void = () => undefined, urlForChunk: (chunk: ChunkFileChunkItem) => string = (chunk) => chunkUrl(detail.chunk_download!, chunk.name)): Promise<Blob> {
  if (signal.aborted) throw abortError();
  validateDetail(detail); const recipe = validateRecipe(detail);
  const chunks = detail.chunks || []; if (!chunks.length) { const empty = new Uint8Array(0); if (detail.hash && digest(empty) !== detail.hash.toLowerCase()) throw new ChunkDownloadError("完整文件 MD5 校验失败"); return new Blob([empty], { type: "application/octet-stream" }); }
  const totalBytes = compressedTotal(chunks, MAX_BROWSER_SYNTHESIS_SIZE);
  const output = new Uint8Array(detail.size); const internal = new AbortController(); const relay = () => internal.abort(); signal.addEventListener("abort", relay, { once: true });
  let receivedBytes = 0; let completed = 0; let next = 0; let failure: unknown;
  const worker = async (): Promise<void> => { while (true) { if (internal.signal.aborted) throw abortError(); const index = next++; if (index >= chunks.length) return; const chunk: ChunkFileChunkItem = chunks[index]; try {
    const decompressed = await downloadChunk(chunk, recipe, internal.signal, (n) => { receivedBytes += n; onProgress({ completed, total: chunks.length, receivedBytes, totalBytes }); }, urlForChunk);
    output.set(decompressed, chunk.offset); completed++; onProgress({ completed, total: chunks.length, receivedBytes, totalBytes });
  } catch (error) { if (!failure) failure = error; internal.abort(); throw error; } } };
  try { await Promise.all(Array.from({ length: Math.min(MAX_CONCURRENCY, chunks.length) }, () => worker())); if (failure) throw failure; if (detail.hash && digest(output) !== detail.hash.toLowerCase()) throw new ChunkDownloadError("完整文件 MD5 校验失败"); return new Blob([output], { type: "application/octet-stream" }); }
  finally { signal.removeEventListener("abort", relay); }
}

export function saveBlob(blob: Blob, filename: string, releaseDelay = 1000): void { const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename || "download.bin"; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), releaseDelay); }
