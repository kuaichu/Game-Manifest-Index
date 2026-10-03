import { afterEach, describe, expect, it, vi } from "vitest";
import SparkMD5 from "spark-md5";
import { api } from "./api";
import { downloadSelectedFiles, selectedFileExport, selectedFilePlan, writeDirectFile } from "./selected-file-download";
import type { ChunkDirectoryHandle } from "./chunk-directory-download";
import type { ChunkFileDetail } from "./types";

const bytes = new TextEncoder().encode("hello");
const md5 = SparkMD5.ArrayBuffer.hash(bytes.buffer as ArrayBuffer);
const recipe = { url_prefix: "https://autopatchcn.yuanshen.com/chunks", url_suffix: "", compression: 0, encryption: 0 };
function detail(path: string, chunk = false): ChunkFileDetail {
  return { path, name: path.split("/").pop()!, identity: "game", size: bytes.length, md5,
    ...(chunk ? { chunk_download: recipe, chunks: [{ name: "chunk-A", hash: md5, offset: 0, size: 5, size_decompressed: 5 }] }
      : { download_url: `https://syncstation.manjuu.com/files/${path}` }) };
}
class Directory implements ChunkDirectoryHandle {
  entries = new Map<string, Directory | ReturnType<typeof sink>>();
  async getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<Directory> {
    const entry = this.entries.get(name);
    if (entry instanceof Directory) return entry;
    if (entry) throw new DOMException("file", "TypeMismatchError");
    if (!options?.create) throw new DOMException("missing", "NotFoundError");
    const result = new Directory(); this.entries.set(name, result); return result;
  }
  async getFileHandle(name: string, options?: { create?: boolean }) {
    const entry = this.entries.get(name);
    if (entry instanceof Directory) throw new DOMException("directory", "TypeMismatchError");
    if (entry) return { createWritable: async () => entry };
    if (!options?.create) throw new DOMException("missing", "NotFoundError");
    const result = sink(); this.entries.set(name, result); return { createWritable: async () => result };
  }
}
function sink() {
  const result = { bytes: [] as number[], write: vi.fn(async (buffer: ArrayBuffer) => { result.bytes.push(...new Uint8Array(buffer)); }),
    close: vi.fn(async () => undefined), abort: vi.fn(async () => undefined) };
  return result;
}
const context = (source: "package" | "chunk" = "package", paths = ["folder/a.bin"]) => ({ source, paths, domainId: "azur-promilia-pc", version: "0.3.0.6", identity: "game", signal: new AbortController().signal });
function response(raw = bytes, length?: number) {
  return new Response(raw.buffer as ArrayBuffer, { headers: length === undefined ? {} : { "Content-Length": String(length) } });
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("selected files", () => {
  it.each(["package", "chunk"] as const)("downloads only selected %s files with real bytes and preserves full paths", async (source) => {
    const resolver = vi.spyOn(api, "versionFileDetail").mockImplementation(async (_d, _v, params) => detail(params.path, source === "chunk"));
    const fetcher = vi.fn(async (_url: string) => response(bytes, 5)); vi.stubGlobal("fetch", fetcher);
    const root = new Directory(); await root.getDirectoryHandle("selected", { create: true });
    const result = await downloadSelectedFiles({ ...context(source), root, baseName: "selected" });
    expect(result).toEqual({ directoryName: "selected-2", files: 1, bytes: 5 });
    expect(resolver).toHaveBeenCalledTimes(1);
    expect(resolver.mock.calls[0][2]).toEqual({ source, identity: "game", path: "folder/a.bin" });
    const saved = ((root.entries.get("selected-2") as Directory).entries.get("folder") as Directory).entries.get("a.bin") as ReturnType<typeof sink>;
    expect(saved.bytes).toEqual([...bytes]); expect(saved.close).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toContain(source === "chunk" ? "chunk-content" : "file-content");
  });

  it.each(["../x", "folder\\x", "CON.txt", "a?x"])("rejects unsafe path %s before creating anything", async (path) => {
    const root = new Directory(); const resolver = vi.spyOn(api, "versionFileDetail");
    await expect(downloadSelectedFiles({ ...context("package", [path]), root, baseName: "selected" })).rejects.toThrow();
    expect(root.entries.size).toBe(0); expect(resolver).not.toHaveBeenCalled();
  });
  it.each([{ paths: ["x", "X"] }, { paths: ["x", "x/y"] }])("rejects incompatible case and file/directory collisions $paths before writes", async ({ paths }) => {
    vi.spyOn(api, "versionFileDetail").mockImplementation(async (_d, _v, params) => ({ ...detail(params.path), size: params.path === "x" ? 5 : 6 }));
    const root = new Directory();
    await expect(downloadSelectedFiles({ ...context("package", paths), root, baseName: "selected" })).rejects.toThrow(/路径冲突/);
    expect(root.entries.size).toBe(0);
  });
  it("keeps completed files and stops before later files on a direct file failure", async () => {
    vi.spyOn(api, "versionFileDetail").mockImplementation(async (_d, _v, params) => detail(params.path));
    const fetcher = vi.fn().mockResolvedValueOnce(response()).mockResolvedValueOnce(response(new TextEncoder().encode("wrong")));
    vi.stubGlobal("fetch", fetcher); const root = new Directory();
    await expect(downloadSelectedFiles({ ...context("package", ["a", "b", "c"]), root, baseName: "selected" })).rejects.toThrow(/MD5/);
    const output = root.entries.get("selected") as Directory;
    expect((output.entries.get("a") as ReturnType<typeof sink>).close).toHaveBeenCalledOnce();
    expect((output.entries.get("b") as ReturnType<typeof sink>).abort).toHaveBeenCalledOnce();
    expect(output.entries.has("c")).toBe(false); expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("exports official URLs for direct files and an explicit synthesis JSON for Chunk files", async () => {
    vi.spyOn(api, "versionFileDetail").mockImplementation(async (_d, _v, params) => detail(params.path, params.source === "chunk"));
    const direct = context(); const chunk = context("chunk");
    expect(selectedFileExport(direct, await selectedFilePlan(direct)).text).toBe(detail("folder/a.bin").download_url);
    const output = selectedFileExport(chunk, await selectedFilePlan(chunk));
    expect(output.extension).toBe("json");
    expect(JSON.parse(output.text)).toMatchObject({ type: "chunk-synthesis-plan", files: [{ path: "folder/a.bin", size: 5, md5, chunk_download: recipe }] });
    expect(output.text).not.toContain("download_url");
  });
});

describe("raw file streaming", () => {
  it.each([{ raw: bytes, length: 6 }, { raw: new Uint8Array(4) }, { raw: new Uint8Array(6) }, { raw: new TextEncoder().encode("wrong") }])("rejects wrong length or MD5 without committing", async ({ raw, length }) => {
    vi.stubGlobal("fetch", vi.fn(async () => response(raw, length))); const writable = sink();
    await expect(writeDirectFile(detail("a"), "/file-content", writable, new AbortController().signal)).rejects.toThrow(/校验/);
    expect(writable.close).not.toHaveBeenCalled(); expect(writable.abort).toHaveBeenCalledOnce();
  });
  it("cancels a pending reader immediately and aborts its file", async () => {
    const canceled = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream<Uint8Array>({ cancel: canceled }))));
    const controller = new AbortController(); const writable = sink();
    const work = writeDirectFile(detail("a"), "/file-content", writable, controller.signal);
    await new Promise((resolve) => setTimeout(resolve, 0)); controller.abort();
    await expect(work).rejects.toMatchObject({ name: "AbortError" });
    expect(canceled).toHaveBeenCalledOnce(); expect(writable.abort).toHaveBeenCalledOnce(); expect(writable.close).not.toHaveBeenCalled();
  });
  it("aborts on a disconnected stream", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes.slice(0, 2)); controller.error(new Error("disconnected")); } }))));
    const writable = sink();
    await expect(writeDirectFile(detail("a"), "/file-content", writable, new AbortController().signal)).rejects.toThrow("disconnected");
    expect(writable.abort).toHaveBeenCalledOnce(); expect(writable.close).not.toHaveBeenCalled();
  });
});
