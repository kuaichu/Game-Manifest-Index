import { Decompress as ZstdDecompress } from "fzstd";
import SparkMD5 from "spark-md5";
import type { ChunkFileDetail, ChunkFileChunkItem } from "./types";

export const MAX_BROWSER_SYNTHESIS_SIZE = 512 * 1024 * 1024;
const MAX_CONCURRENCY = 4;
export interface ChunkDownloadProgress { completed: number; total: number; receivedBytes: number; totalBytes: number; }
export class ChunkDownloadError extends Error { constructor(message: string) { super(message); this.name = "ChunkDownloadError"; } }
function abortError(): DOMException { return new DOMException("Aborted", "AbortError"); }
function digest(value: Uint8Array): string { return SparkMD5.ArrayBuffer.hash(value.slice().buffer as ArrayBuffer); }

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

function validateDetail(detail: ChunkFileDetail): void {
  if (!Number.isSafeInteger(detail.size) || detail.size < 0 || detail.size > MAX_BROWSER_SYNTHESIS_SIZE) throw new ChunkDownloadError(detail.size > MAX_BROWSER_SYNTHESIS_SIZE ? "文件超过 512 MiB，暂不支持浏览器合成" : "文件大小无效");
  for (const chunk of detail.chunks || []) {
    if (![chunk.offset, chunk.size, chunk.size_decompressed].every((v) => Number.isSafeInteger(v) && v >= 0)) throw new ChunkDownloadError("Chunk 元数据无效");
    if (chunk.offset + chunk.size_decompressed > detail.size) throw new ChunkDownloadError("Chunk 超出文件范围");
    if (chunk.size > MAX_BROWSER_SYNTHESIS_SIZE || chunk.size_decompressed > MAX_BROWSER_SYNTHESIS_SIZE) throw new ChunkDownloadError("Chunk 超过浏览器合成限制");
  }
  const ranges = (detail.chunks || []).map((c) => [c.offset, c.offset + c.size_decompressed] as const).sort((a, b) => a[0] - b[0]);
  let cursor = 0;
  for (const [start, end] of ranges) { if (start !== cursor) throw new ChunkDownloadError(start < cursor ? "Chunk 存在重叠" : "Chunk 存在缺口"); cursor = end; }
  if (cursor !== detail.size) throw new ChunkDownloadError("Chunk 未覆盖完整文件");
}

async function readResponse(response: Response, expected: number, signal: AbortSignal, onBytes: (n: number) => void): Promise<Uint8Array> {
  if (!response.ok) throw new ChunkDownloadError(`Chunk 请求失败（HTTP ${response.status}）`);
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > expected) throw new ChunkDownloadError("Chunk 超过声明大小");
  if (!response.body) { if (!Number.isFinite(declared)) throw new ChunkDownloadError("Chunk 缺少长度声明"); const bytes = new Uint8Array(await response.arrayBuffer()); if (bytes.byteLength > expected) throw new ChunkDownloadError("Chunk 超过声明大小"); onBytes(bytes.byteLength); if (bytes.byteLength !== expected) throw new ChunkDownloadError("Chunk 压缩大小校验失败"); return bytes; }
  const reader = response.body.getReader(); const parts: Uint8Array[] = []; let total = 0;
  try { while (true) { if (signal.aborted) throw abortError(); const item = await reader.read(); if (item.done) break; if (item.value) { total += item.value.byteLength; if (total > expected) throw new ChunkDownloadError("Chunk 超过声明大小"); parts.push(item.value); onBytes(item.value.byteLength); } } }
  finally { await reader.cancel().catch(() => undefined); }
  if (total !== expected) throw new ChunkDownloadError("Chunk 压缩大小校验失败");
  const result = new Uint8Array(total); let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.byteLength; } return result;
}

export async function synthesizeChunkFile(detail: ChunkFileDetail, signal: AbortSignal, onProgress: (p: ChunkDownloadProgress) => void = () => undefined, urlForChunk: (chunk: ChunkFileChunkItem) => string = (chunk) => chunkUrl(detail.chunk_download!, chunk.name)): Promise<Blob> {
  if (signal.aborted) throw abortError();
  validateDetail(detail); const recipe = detail.chunk_download;
  if (!recipe) throw new ChunkDownloadError("缺少 Chunk 下载规则");
  if (recipe.encryption !== undefined && recipe.encryption !== 0) throw new ChunkDownloadError("该 Chunk 使用加密，暂不支持浏览器合成");
  if (recipe.compression !== undefined && recipe.compression !== 0 && recipe.compression !== 1) throw new ChunkDownloadError(`不支持的 Chunk 压缩方式：${recipe.compression}`);
  const chunks = detail.chunks || []; if (!chunks.length) { const empty = new Uint8Array(0); if (detail.hash && digest(empty) !== detail.hash.toLowerCase()) throw new ChunkDownloadError("完整文件 MD5 校验失败"); return new Blob([empty], { type: "application/octet-stream" }); }
  const totalBytes = chunks.reduce((sum, c) => sum + c.size, 0); if (!Number.isSafeInteger(totalBytes) || totalBytes > MAX_BROWSER_SYNTHESIS_SIZE) throw new ChunkDownloadError("Chunk 总压缩体积超过浏览器限制");
  const output = new Uint8Array(detail.size); const internal = new AbortController(); const relay = () => internal.abort(); signal.addEventListener("abort", relay, { once: true });
  let receivedBytes = 0; let completed = 0; let next = 0; let failure: unknown;
  const worker = async (): Promise<void> => { while (true) { if (internal.signal.aborted) throw abortError(); const index = next++; if (index >= chunks.length) return; const chunk: ChunkFileChunkItem = chunks[index]; try {
    const response = await fetch(urlForChunk(chunk), { signal: internal.signal }); const compressed = await readResponse(response, chunk.size, internal.signal, (n) => { receivedBytes += n; onProgress({ completed, total: chunks.length, receivedBytes, totalBytes }); });
    let decompressed: Uint8Array; try { decompressed = recipe.compression === 1 ? decompressZstd(compressed, chunk.size_decompressed) : compressed; } catch (error) { if (error instanceof ChunkDownloadError) throw error; throw new ChunkDownloadError(`Chunk ${chunk.name} 解压失败`); }
    if (decompressed.byteLength !== chunk.size_decompressed) throw new ChunkDownloadError(`Chunk ${chunk.name} 解压大小校验失败`); if (digest(decompressed) !== chunk.hash.toLowerCase()) throw new ChunkDownloadError(`Chunk ${chunk.name} MD5 校验失败`); output.set(decompressed, chunk.offset); completed++; onProgress({ completed, total: chunks.length, receivedBytes, totalBytes });
  } catch (error) { if (!failure) failure = error; internal.abort(); throw error; } } };
  try { await Promise.all(Array.from({ length: Math.min(MAX_CONCURRENCY, chunks.length) }, () => worker())); if (failure) throw failure; if (detail.hash && digest(output) !== detail.hash.toLowerCase()) throw new ChunkDownloadError("完整文件 MD5 校验失败"); return new Blob([output], { type: "application/octet-stream" }); }
  finally { signal.removeEventListener("abort", relay); }
}

export function saveBlob(blob: Blob, filename: string, releaseDelay = 1000): void { const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename || "download.bin"; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), releaseDelay); }
