import { afterEach, describe, expect, it, vi } from "vitest";
import { chunkUrl, MAX_BROWSER_SYNTHESIS_SIZE, saveBlob, synthesizeChunkFile, writeChunkFile, type ChunkWritableSink } from "./chunk-download";
import type { ChunkFileDetail } from "./types";

const recipe = { url_prefix: "https://cdn.example/chunks", url_suffix: "?v=1", compression: 0, encryption: 0 };
const md5 = (bytes: Uint8Array) => import("spark-md5").then(({ default: SparkMD5 }) => SparkMD5.ArrayBuffer.hash(bytes.slice().buffer as ArrayBuffer));
const detail = async (raw = false): Promise<ChunkFileDetail> => {
  const first = new TextEncoder().encode("hello"); const second = new TextEncoder().encode("world");
  return { identity: "game", name: "x", path: "x", size: 10, hash: await md5(new Uint8Array([...first, ...second])), chunk_download: { ...recipe, compression: raw ? 0 : 1 }, chunks: [
    { name: "chunk-A", hash: await md5(first), offset: 0, size: raw ? 5 : 14, size_decompressed: 5 },
    { name: "chunk-B", hash: await md5(second), offset: 5, size: raw ? 5 : 14, size_decompressed: 5 },
  ] };
};
const response = (data: Uint8Array) => new Response(data.buffer as ArrayBuffer, { status: 200, headers: { "content-length": String(data.byteLength) } });
const writable = (): ChunkWritableSink => ({ write: vi.fn(async () => undefined), close: vi.fn(async () => undefined), abort: vi.fn(async () => undefined) });

afterEach(() => vi.restoreAllMocks());

describe("chunk-download", () => {
  it("uses chunk name and preserves suffix, rejecting unsafe prefixes", () => {
    expect(chunkUrl(recipe, "chunk-A")).toBe("https://cdn.example/chunks/chunk-A?v=1");
    expect(() => chunkUrl({ ...recipe, url_prefix: "https://cdn.example/x?bad=1" }, "a")).toThrow();
    expect(() => chunkUrl({ ...recipe, url_prefix: "https://u:p@cdn.example/x" }, "a")).toThrow();
    expect(() => chunkUrl({ ...recipe, url_prefix: "http://cdn.example/x" }, "a")).toThrow();
  });

  it("assembles raw chunks by offset and never exceeds four workers", async () => {
    const d = await detail(true); const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push(url); return response(url.includes("A") ? new TextEncoder().encode("hello") : new TextEncoder().encode("world")); }));
    const blob = await synthesizeChunkFile(d, new AbortController().signal);
    expect(blob.size).toBe(10); expect(calls[0]).toContain("chunk-A?v=1");
  });

  it("allows the UI to inject the same-origin chunk proxy", async () => {
    const d = await detail(true); const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => { urls.push(url); return response(new TextEncoder().encode(url.includes("chunk-A") ? "hello" : "world")); }));
    await synthesizeChunkFile(d, new AbortController().signal, undefined, (chunk) => `/api/v1/domains/hk4e-pc/versions/7.0.0/chunk-content?name=${encodeURIComponent(chunk.name)}`);
    expect(urls.every((url) => url.startsWith("/api/v1/"))).toBe(true);
    expect(urls.some((url) => url.includes("chunk-A"))).toBe(true);
  });

  it("supports zstd fixture and validates chunk/full hashes", async () => {
    const d = await detail(); const a = Uint8Array.from(atob("KLUv/SAFKQAAaGVsbG8="), (c) => c.charCodeAt(0)); const b = Uint8Array.from(atob("KLUv/SAFKQAAd29ybGQ="), (c) => c.charCodeAt(0));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.includes("A") ? a : b)));
    expect((await synthesizeChunkFile(d, new AbortController().signal)).size).toBe(10);
    const bad = { ...d, chunks: d.chunks!.map((c) => ({ ...c, hash: "0".repeat(32) })) };
    await expect(synthesizeChunkFile(bad, new AbortController().signal)).rejects.toThrow("MD5");
    const undersized = { ...d, chunks: d.chunks!.map((c) => ({ ...c, size_decompressed: 4 })) };
    await expect(synthesizeChunkFile(undersized, new AbortController().signal)).rejects.toThrow();
  });

  it("rejects layout, HTTP, abort, and oversized metadata before unsafe work", async () => {
    const d = await detail(true); const fetchMock = vi.fn(async () => response(new Uint8Array(5))); vi.stubGlobal("fetch", fetchMock);
    await expect(synthesizeChunkFile({ ...d, size: 11 }, new AbortController().signal)).rejects.toThrow("未覆盖"); expect(fetchMock).not.toHaveBeenCalled();
    await expect(synthesizeChunkFile({ ...d, size: MAX_BROWSER_SYNTHESIS_SIZE + 1 }, new AbortController().signal)).rejects.toThrow("512 MiB");
    const httpFetch = vi.fn(async () => new Response("no", { status: 404 })); vi.stubGlobal("fetch", httpFetch);
    await expect(synthesizeChunkFile(d, new AbortController().signal)).rejects.toThrow("HTTP 404");
    const controller = new AbortController(); controller.abort(); httpFetch.mockClear(); await expect(synthesizeChunkFile(d, controller.signal)).rejects.toThrow(); expect(httpFetch).not.toHaveBeenCalled();
    const noBody = { ok: true, status: 200, headers: new Headers({ "content-length": "5" }), body: null, arrayBuffer: async () => new TextEncoder().encode("hello").buffer } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn(async () => noBody));
    expect((await synthesizeChunkFile({ ...d, chunks: d.chunks!.slice(0, 1), size: 5, hash: d.chunks![0].hash }, new AbortController().signal)).size).toBe(5);
    const zstd = await detail(); const compressedHello = Uint8Array.from(atob("KLUv/SAFKQAAaGVsbG8="), (c) => c.charCodeAt(0));
    vi.stubGlobal("fetch", vi.fn(async () => response(compressedHello)));
    await expect(synthesizeChunkFile({ ...zstd, chunks: [{ ...zstd.chunks![0], size_decompressed: 4 }, { ...zstd.chunks![1], offset: 4, size_decompressed: 6 }], size: 10 }, new AbortController().signal)).rejects.toThrow();
  });

  it("supports an empty file and delayed object URL release", async () => {
    const empty: ChunkFileDetail = { identity: "game", name: "empty", path: "empty", size: 0, chunk_download: recipe, chunks: [] };
    expect((await synthesizeChunkFile(empty, new AbortController().signal)).size).toBe(0);
    await expect(synthesizeChunkFile({ ...empty, hash: "0".repeat(32) }, new AbortController().signal)).rejects.toThrow("完整文件 MD5");
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true }); Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:test"), configurable: true }); const revoke = vi.spyOn(URL, "revokeObjectURL"); vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test"); const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); vi.useFakeTimers();
    saveBlob(new Blob(["x"]), "x", 50); expect(click).toHaveBeenCalled(); expect(revoke).not.toHaveBeenCalled(); vi.advanceTimersByTime(50); expect(revoke).toHaveBeenCalledWith("blob:test"); vi.useRealTimers();
  });

  it("aborts active workers on one failure and does not start the queued fifth chunk", async () => {
    const chunks = await Promise.all(Array.from({ length: 5 }, async (_, index) => {
      const byte = new Uint8Array([65 + index]);
      return { name: `chunk-${index}`, hash: await md5(byte), offset: index, size: 1, size_decompressed: 1 };
    }));
    const d: ChunkFileDetail = { identity: "game", name: "five.bin", path: "five.bin", size: 5, hash: await md5(new Uint8Array([65, 66, 67, 68, 69])), chunk_download: recipe, chunks };
    const started: string[] = []; const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const name = url.split("/").pop() || ""; started.push(name); const signal = init?.signal as AbortSignal; signals.push(signal);
      if (name.startsWith("chunk-1")) return Promise.resolve(new Response("bad", { status: 503 }));
      return new Promise<Response>((_, reject) => {
        const fail = () => reject(new DOMException("Aborted", "AbortError"));
        if (signal.aborted) fail(); else signal.addEventListener("abort", fail, { once: true });
      });
    }));
    await expect(synthesizeChunkFile(d, new AbortController().signal)).rejects.toThrow("HTTP 503");
    expect(started.map((name) => name.split("?")[0])).toEqual(expect.arrayContaining(["chunk-0", "chunk-1", "chunk-2", "chunk-3"]));
    expect(started.map((name) => name.split("?")[0])).not.toContain("chunk-4");
    expect(signals.filter((signal) => signal.aborted)).toHaveLength(4);
  });
});

describe("writeChunkFile", () => {
  it("writes sorted chunks sequentially and hashes only successful writes before closing", async () => {
    const d = await detail(true); d.chunks!.reverse();
    const { default: SparkMD5 } = await import("spark-md5");
    const append = vi.spyOn(SparkMD5.ArrayBuffer.prototype, "append");
    const sink = writable(); const writes: string[] = []; const events: string[] = [];
    let finishFirstWrite!: () => void;
    const firstWrite = new Promise<void>((resolve) => { finishFirstWrite = resolve; });
    vi.mocked(sink.write).mockImplementation(async (data) => {
      writes.push(new TextDecoder().decode(data)); events.push(`write:${writes.length}`);
      if (writes.length === 1) await firstWrite;
    });
    vi.mocked(sink.close).mockImplementation(async () => { events.push("close"); });
    const fetchMock = vi.fn(async (url: string) => response(new TextEncoder().encode(url.includes("chunk-A") ? "hello" : "world")));
    vi.stubGlobal("fetch", fetchMock); const progress = vi.fn();
    const download = writeChunkFile(d, sink, new AbortController().signal, progress, (chunk) => `/chunk-proxy?name=${chunk.name}`);
    await vi.waitFor(() => expect(sink.write).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(append).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled();
    finishFirstWrite(); await download;
    expect(writes).toEqual(["hello", "world"]); expect(events).toEqual(["write:1", "write:2", "close"]);
    expect(append).toHaveBeenCalledTimes(2); expect(d.chunks!.map((chunk) => chunk.name)).toEqual(["chunk-B", "chunk-A"]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/chunk-proxy?name=chunk-A", "/chunk-proxy?name=chunk-B"]);
    expect(progress).toHaveBeenLastCalledWith({ completed: 2, total: 2, receivedBytes: 10, totalBytes: 10 });
    expect(sink.abort).not.toHaveBeenCalled();
  });

  it("accepts a file over 512 MiB without allocating the whole file before fetch", async () => {
    const d = await detail(true);
    const large: ChunkFileDetail = { ...d, size: MAX_BROWSER_SYNTHESIS_SIZE + 1, chunks: [
      { ...d.chunks![0], size: MAX_BROWSER_SYNTHESIS_SIZE, size_decompressed: MAX_BROWSER_SYNTHESIS_SIZE },
      { ...d.chunks![1], offset: MAX_BROWSER_SYNTHESIS_SIZE, size: 1, size_decompressed: 1 },
    ] };
    const fetchMock = vi.fn(async () => new Response("unavailable", { status: 503 })); vi.stubGlobal("fetch", fetchMock);
    const sink = writable(); const signal = new AbortController().signal;
    await expect(writeChunkFile(large, sink, signal)).rejects.toThrow("HTTP 503");
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("chunk-A"), { signal });
    expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
  });

  it("rejects invalid coverage and chunk metadata before fetch, aborting the sink", async () => {
    const d = await detail(true); const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const invalid: ChunkFileDetail[] = [
      { ...d, size: 11 },
      { ...d, size: 11, chunks: [d.chunks![0], { ...d.chunks![1], offset: 6 }] },
      { ...d, chunks: [d.chunks![0], { ...d.chunks![1], offset: 4 }] },
      { ...d, chunks: [{ ...d.chunks![0], size: 1.5 }, d.chunks![1]] },
      { ...d, size: MAX_BROWSER_SYNTHESIS_SIZE + 1, chunks: [{ ...d.chunks![0], size_decompressed: MAX_BROWSER_SYNTHESIS_SIZE + 1 }] },
    ];
    for (const item of invalid) {
      const sink = writable();
      await expect(writeChunkFile(item, sink, new AbortController().signal)).rejects.toThrow();
      expect(sink.abort).toHaveBeenCalledTimes(1); expect(sink.close).not.toHaveBeenCalled(); expect(sink.write).not.toHaveBeenCalled();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("decodes zstd chunks and verifies the complete file", async () => {
    const d = await detail();
    const a = Uint8Array.from(atob("KLUv/SAFKQAAaGVsbG8="), (c) => c.charCodeAt(0)); const b = Uint8Array.from(atob("KLUv/SAFKQAAd29ybGQ="), (c) => c.charCodeAt(0));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.includes("chunk-A") ? a : b)));
    const sink = writable(); await writeChunkFile(d, sink, new AbortController().signal);
    expect(vi.mocked(sink.write).mock.calls.map(([bytes]) => new TextDecoder().decode(bytes))).toEqual(["hello", "world"]);
    expect(sink.close).toHaveBeenCalledTimes(1); expect(sink.abort).not.toHaveBeenCalled();
  });

  it("aborts on chunk, decompressed-size, and full-file verification failures", async () => {
    const d = await detail(true);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(new TextEncoder().encode(url.includes("chunk-A") ? "hello" : "world"))));
    const chunkSink = writable();
    await expect(writeChunkFile({ ...d, chunks: [{ ...d.chunks![0], hash: "0".repeat(32) }, d.chunks![1]] }, chunkSink, new AbortController().signal)).rejects.toThrow("Chunk chunk-A MD5");
    expect(chunkSink.write).not.toHaveBeenCalled(); expect(chunkSink.close).not.toHaveBeenCalled(); expect(chunkSink.abort).toHaveBeenCalledTimes(1);
    const sizeSink = writable();
    await expect(writeChunkFile({ ...d, chunks: [{ ...d.chunks![0], size_decompressed: 4 }, { ...d.chunks![1], offset: 4, size_decompressed: 6 }] }, sizeSink, new AbortController().signal)).rejects.toThrow("解压大小");
    expect(sizeSink.write).not.toHaveBeenCalled(); expect(sizeSink.close).not.toHaveBeenCalled(); expect(sizeSink.abort).toHaveBeenCalledTimes(1);
    const fileSink = writable();
    await expect(writeChunkFile({ ...d, hash: "0".repeat(32) }, fileSink, new AbortController().signal)).rejects.toThrow("完整文件 MD5");
    expect(fileSink.write).toHaveBeenCalledTimes(2); expect(fileSink.close).not.toHaveBeenCalled(); expect(fileSink.abort).toHaveBeenCalledTimes(1);
  });

  it("requires a file hash and validates the MD5 of a zero-byte file", async () => {
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const empty: ChunkFileDetail = { identity: "game", name: "empty", path: "empty", size: 0, chunk_download: recipe, chunks: [] };
    for (const hash of [undefined, "invalid", "0".repeat(32)]) {
      const sink = writable();
      await expect(writeChunkFile({ ...empty, hash }, sink, new AbortController().signal)).rejects.toThrow("MD5");
      expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
    }
    const sink = writable(); await writeChunkFile({ ...empty, md5: await md5(new Uint8Array(0)) }, sink, new AbortController().signal);
    expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).toHaveBeenCalledTimes(1); expect(sink.abort).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a password rule even when encryption is zero", async () => {
    const d = await detail(true); const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    for (const password of ["protected", ""]) {
      const protectedDetail = { ...d, chunk_download: { ...recipe, password } }; const sink = writable();
      await expect(writeChunkFile(protectedDetail, sink, new AbortController().signal)).rejects.toThrow("密码");
      expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
      await expect(synthesizeChunkFile(protectedDetail, new AbortController().signal)).rejects.toThrow("密码");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects conflicting file hashes before fetching but accepts case differences", async () => {
    const d = await detail(true); const fetchMock = vi.fn(async (url: string) => response(new TextEncoder().encode(url.includes("chunk-A") ? "hello" : "world")));
    vi.stubGlobal("fetch", fetchMock); const conflictingSink = writable();
    await expect(writeChunkFile({ ...d, md5: "0".repeat(32) }, conflictingSink, new AbortController().signal)).rejects.toThrow("MD5 字段冲突");
    expect(fetchMock).not.toHaveBeenCalled(); expect(conflictingSink.write).not.toHaveBeenCalled(); expect(conflictingSink.close).not.toHaveBeenCalled(); expect(conflictingSink.abort).toHaveBeenCalledTimes(1);
    const sink = writable(); await writeChunkFile({ ...d, md5: d.hash!.toUpperCase() }, sink, new AbortController().signal);
    expect(sink.write).toHaveBeenCalledTimes(2); expect(sink.close).toHaveBeenCalledTimes(1); expect(sink.abort).not.toHaveBeenCalled();
  });

  it("aborts an already cancelled download before fetching", async () => {
    const d = await detail(true); const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const sink = writable(); const controller = new AbortController(); controller.abort();
    await expect(writeChunkFile(d, sink, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled(); expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
  });

  it("passes cancellation to fetch and stops without waiting on an unresponsive request", async () => {
    const d = await detail(true); const controller = new AbortController(); const sink = writable();
    const fetchMock = vi.fn(() => new Promise<Response>(() => undefined)); vi.stubGlobal("fetch", fetchMock);
    const download = writeChunkFile(d, sink, controller.signal); const rejected = expect(download).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1)); controller.abort(); await rejected;
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), { signal: controller.signal });
    expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
  });

  it("cancels a pending body read without waiting for reader cancellation", async () => {
    const d = await detail(true); const controller = new AbortController(); const sink = writable();
    const read = vi.fn(() => new Promise<ReadableStreamReadResult<Uint8Array>>(() => undefined)); const cancel = vi.fn(() => new Promise<void>(() => undefined));
    const pendingResponse = { ok: true, status: 200, headers: new Headers(), body: { getReader: () => ({ read, cancel }) } } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn(async () => pendingResponse));
    const download = writeChunkFile(d, sink, controller.signal); const rejected = expect(download).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(read).toHaveBeenCalledTimes(1)); controller.abort(); await rejected;
    expect(cancel).toHaveBeenCalled(); expect(sink.write).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
  });

  it("aborts a pending write and never hashes or closes it", async () => {
    const d = await detail(true); const controller = new AbortController(); const sink = writable();
    const { default: SparkMD5 } = await import("spark-md5"); const append = vi.spyOn(SparkMD5.ArrayBuffer.prototype, "append");
    vi.stubGlobal("fetch", vi.fn(async () => response(new TextEncoder().encode("hello"))));
    vi.mocked(sink.write).mockImplementation(() => new Promise<void>(() => undefined));
    const download = writeChunkFile(d, sink, controller.signal); const rejected = expect(download).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(sink.write).toHaveBeenCalledTimes(1)); controller.abort(); await rejected;
    expect(append).not.toHaveBeenCalled(); expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledTimes(1);
  });

  it("preserves a write failure even when aborting the sink fails", async () => {
    const d = await detail(true); const sink = writable(); const failure = new Error("disk full");
    vi.stubGlobal("fetch", vi.fn(async () => response(new TextEncoder().encode("hello"))));
    vi.mocked(sink.write).mockRejectedValue(failure); vi.mocked(sink.abort).mockRejectedValue(new Error("abort failed"));
    await expect(writeChunkFile(d, sink, new AbortController().signal)).rejects.toBe(failure);
    expect(sink.close).not.toHaveBeenCalled(); expect(sink.abort).toHaveBeenCalledWith(failure);
  });
});
