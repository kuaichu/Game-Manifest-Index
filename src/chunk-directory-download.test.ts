import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChunkWritableSink } from "./chunk-download";
import type { ChunkDownloadPlanPage, ChunkFileDetail } from "./types";

const mocks = vi.hoisted(() => ({
  chunkDownloadPlan: vi.fn(),
  chunkContentUrl: vi.fn((domainId: string, version: string, identity: string, name: string) =>
    `chunk:${domainId}:${version}:${identity}:${name}`),
  writeChunkFile: vi.fn(),
}));

vi.mock("./api", () => ({
  api: { chunkDownloadPlan: mocks.chunkDownloadPlan },
  chunkContentUrl: mocks.chunkContentUrl,
}));

vi.mock("./chunk-download", () => ({ writeChunkFile: mocks.writeChunkFile }));

import { downloadChunkDirectory, type ChunkDirectoryHandle, type ChunkDirectoryFileHandle } from "./chunk-directory-download";

type Entry = TestDirectory | TestFile;

class TestFile implements ChunkDirectoryFileHandle {
  readonly bytes: number[] = [];
  closed = false;
  aborted: unknown;

  async createWritable(): Promise<ChunkWritableSink> {
    const sink = {
      write: async (data: ArrayBuffer) => { this.bytes.push(...new Uint8Array(data)); },
      close: async () => { this.closed = true; },
      abort: async (reason?: unknown) => { this.aborted = reason; },
    };
    return sink;
  }
}

class TestDirectory implements ChunkDirectoryHandle {
  readonly entries = new Map<string, Entry>();

  async getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<ChunkDirectoryHandle> {
    const existing = this.entries.get(name);
    if (existing instanceof TestDirectory) return existing;
    if (existing) throw new DOMException("Entry is a file", "TypeMismatchError");
    if (!options?.create) throw new DOMException("Entry not found", "NotFoundError");
    const directory = new TestDirectory();
    this.entries.set(name, directory);
    return directory;
  }

  async getFileHandle(name: string, options?: { create?: boolean }): Promise<ChunkDirectoryFileHandle> {
    const existing = this.entries.get(name);
    if (existing instanceof TestFile) return existing;
    if (existing) throw new DOMException("Entry is a directory", "TypeMismatchError");
    if (!options?.create) throw new DOMException("Entry not found", "NotFoundError");
    const file = new TestFile();
    this.entries.set(name, file);
    return file;
  }
}

const md5A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const md5B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function detail(path: string, options: { size?: number; hash?: string; download?: string } = {}): ChunkFileDetail {
  const name = path.split("/").pop() || path;
  return {
    identity: "component",
    name,
    path,
    size: options.size ?? 2,
    hash: options.hash ?? md5A,
    ...(options.download ? { download_url: options.download } : {}),
    chunks: [{ name: `${name}.chunk`, hash: md5A, offset: 0, size: 2, size_decompressed: 2 }],
  };
}

function page(identity: string, items: ChunkFileDetail[], next_cursor: string | null = null, total = items.length, total_size = items.reduce((sum, item) => sum + item.size, 0)): ChunkDownloadPlanPage {
  return { identity, items: items.map((item) => ({ ...item, identity })), total, next_cursor, total_size };
}

function usePlans(plans: Record<string, Record<string, ChunkDownloadPlanPage>>): void {
  mocks.chunkDownloadPlan.mockImplementation(async (_domain, _version, identity, params) => {
    return plans[identity][params.cursor ?? "start"];
  });
}

function setupWriter(): void {
  mocks.writeChunkFile.mockImplementation(async (file: ChunkFileDetail, writable: ChunkWritableSink, signal: AbortSignal, onProgress, urlForChunk) => {
    if (file.download_url === "abort") {
      const controller = (signal as AbortSignal & { testController?: AbortController }).testController;
      controller?.abort();
      throw new DOMException("Aborted", "AbortError");
    }
    if (file.download_url === "fail") throw new Error("write failed");
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    if (file.chunks?.[0]) urlForChunk?.(file.chunks[0]);
    onProgress?.({ completed: 1, total: 1, receivedBytes: file.size, totalBytes: file.size });
    await writable.write(new Uint8Array(file.size).buffer);
    await writable.close();
  });
}

function options(root: TestDirectory, identities = ["component"], signal = new AbortController().signal) {
  return { domainId: "domain", version: "7.1.0", identities, root, baseName: "game-7.1.0", signal };
}

function outputDirectory(root: TestDirectory, name = "game-7.1.0"): TestDirectory {
  const directory = root.entries.get(name);
  if (!(directory instanceof TestDirectory)) throw new Error(`missing directory ${name}`);
  return directory;
}

beforeEach(() => {
  vi.clearAllMocks();
  setupWriter();
});

describe("downloadChunkDirectory", () => {
  it("collects every component page without a search filter and writes cross-component duplicates once", async () => {
    usePlans({
      componentA: {
        start: page("componentA", [detail("assets/shared.bin"), detail("assets/unique.bin", { hash: md5B })], "page-2", 3, 6),
        "page-2": page("componentA", [detail("other.bin")], null, 3, 6),
      },
      componentB: { start: page("componentB", [detail("ASSETS/SHARED.BIN")]) },
    });
    const root = new TestDirectory();
    const progress: Array<{ stage: string; completedFiles: number; totalFiles: number }> = [];

    const result = await downloadChunkDirectory({
      ...options(root, ["componentA", "componentB"]),
      onProgress: (item) => progress.push(item),
    });

    expect(result).toEqual({ directoryName: "game-7.1.0", files: 3, bytes: 6 });
    expect(mocks.chunkDownloadPlan).toHaveBeenCalledTimes(3);
    expect(mocks.chunkDownloadPlan).toHaveBeenNthCalledWith(1, "domain", "7.1.0", "componentA", { limit: 500, cursor: null }, expect.any(AbortSignal));
    expect(mocks.chunkDownloadPlan).toHaveBeenNthCalledWith(2, "domain", "7.1.0", "componentA", { limit: 500, cursor: "page-2" }, expect.any(AbortSignal));
    expect(mocks.chunkDownloadPlan).toHaveBeenNthCalledWith(3, "domain", "7.1.0", "componentB", { limit: 500, cursor: null }, expect.any(AbortSignal));
    expect(mocks.writeChunkFile).toHaveBeenCalledTimes(3);
    expect(mocks.chunkContentUrl).toHaveBeenCalledWith("domain", "7.1.0", "componentA", "shared.bin.chunk");
    const output = outputDirectory(root);
    expect((output.entries.get("assets") as TestDirectory).entries.size).toBe(2);
    expect(output.entries.has("other.bin")).toBe(true);
    expect(progress.at(-1)).toMatchObject({ stage: "downloading", completedFiles: 3, totalFiles: 3 });
  });

  it("uses the identity returned by the plan for chunk-content requests", async () => {
    usePlans({ manifestAlias: { start: page("canonical-component", [detail("file.bin")]) } });
    const root = new TestDirectory();

    await downloadChunkDirectory(options(root, ["manifestAlias"]));

    expect(mocks.chunkContentUrl).toHaveBeenCalledWith("domain", "7.1.0", "canonical-component", "file.bin.chunk");
  });

  it("rejects same-path files whose size or MD5 differs before creating an output directory", async () => {
    usePlans({
      first: { start: page("first", [detail("shared.bin")]) },
      second: { start: page("second", [detail("SHARED.BIN", { hash: md5B })]) },
    });
    const root = new TestDirectory();

    await expect(downloadChunkDirectory(options(root, ["first", "second"]))).rejects.toThrow(/路径冲突/);
    expect(root.entries.size).toBe(0);
    expect(mocks.writeChunkFile).not.toHaveBeenCalled();
  });

  it("rejects same-path files with a different size before creating an output directory", async () => {
    usePlans({
      first: { start: page("first", [detail("shared.bin")]) },
      second: { start: page("second", [detail("shared.bin", { size: 3 })]) },
    });
    const root = new TestDirectory();

    await expect(downloadChunkDirectory(options(root, ["first", "second"]))).rejects.toThrow(/路径冲突/);
    expect(root.entries.size).toBe(0);
    expect(mocks.writeChunkFile).not.toHaveBeenCalled();
  });

  it.each(["../escape.bin", ".", "folder/./escape.bin", "/absolute.bin", "folder\\escape.bin", "CON.txt", "trailing. ", "bad?.bin"])(
    "rejects unsafe path %s before creating an output directory",
    async (path) => {
      usePlans({ component: { start: page("component", [detail(path)]) } });
      const root = new TestDirectory();

      await expect(downloadChunkDirectory(options(root))).rejects.toThrow();
      expect(root.entries.size).toBe(0);
      expect(mocks.writeChunkFile).not.toHaveBeenCalled();
    },
  );

  it("requires a complete-file MD5 before creating an output directory", async () => {
    const missingHash = detail("file.bin");
    delete missingHash.hash;
    usePlans({ component: { start: page("component", [missingHash]) } });
    const root = new TestDirectory();

    await expect(downloadChunkDirectory(options(root))).rejects.toThrow(/MD5/);
    expect(root.entries.size).toBe(0);
    expect(mocks.writeChunkFile).not.toHaveBeenCalled();
  });

  it("rejects case-folded file and directory prefix conflicts during plan validation", async () => {
    usePlans({ component: { start: page("component", [detail("Folder"), detail("folder/child.bin")]) } });
    const root = new TestDirectory();

    await expect(downloadChunkDirectory(options(root))).rejects.toThrow(/路径冲突/);
    expect(root.entries.size).toBe(0);
  });

  it("chooses a suffixed directory when the requested name already exists and preserves its files", async () => {
    usePlans({ component: { start: page("component", [detail("file.bin")]) } });
    const root = new TestDirectory();
    const existing = new TestDirectory();
    const original = new TestFile();
    original.bytes.push(9, 8, 7);
    existing.entries.set("keep.bin", original);
    root.entries.set("game-7.1.0", existing);

    const result = await downloadChunkDirectory(options(root));

    expect(result.directoryName).toBe("game-7.1.0-2");
    expect(existing.entries.get("keep.bin")).toBe(original);
    expect(original.bytes).toEqual([9, 8, 7]);
    expect(outputDirectory(root, "game-7.1.0-2").entries.has("file.bin")).toBe(true);
  });

  it("chooses a suffixed directory when a file already occupies the requested name", async () => {
    usePlans({ component: { start: page("component", [detail("file.bin")]) } });
    const root = new TestDirectory();
    const existing = new TestFile();
    existing.bytes.push(1, 2, 3);
    root.entries.set("game-7.1.0", existing);

    const result = await downloadChunkDirectory(options(root));

    expect(result.directoryName).toBe("game-7.1.0-2");
    expect(root.entries.get("game-7.1.0")).toBe(existing);
    expect(existing.bytes).toEqual([1, 2, 3]);
    expect(outputDirectory(root, "game-7.1.0-2").entries.has("file.bin")).toBe(true);
  });

  it("creates zero-byte files from empty chunk lists", async () => {
    const empty: ChunkFileDetail = {
      identity: "component",
      name: "empty.bin",
      path: "empty.bin",
      size: 0,
      hash: "d41d8cd98f00b204e9800998ecf8427e",
      chunks: [],
    };
    usePlans({ component: { start: page("component", [empty]) } });
    const root = new TestDirectory();

    const result = await downloadChunkDirectory(options(root));

    expect(result).toEqual({ directoryName: "game-7.1.0", files: 1, bytes: 0 });
    const saved = outputDirectory(root).entries.get("empty.bin") as TestFile;
    expect(saved.closed).toBe(true);
    expect(saved.bytes).toEqual([]);
  });

  it("propagates cancellation and retains files completed before it", async () => {
    usePlans({ component: { start: page("component", [detail("done.bin"), detail("cancel.bin", { download: "abort" })]) } });
    const root = new TestDirectory();
    const controller = new AbortController() as AbortController & { testController?: AbortController };
    (controller.signal as AbortSignal & { testController?: AbortController }).testController = controller;

    await expect(downloadChunkDirectory(options(root, ["component"], controller.signal))).rejects.toMatchObject({ name: "AbortError" });
    const output = outputDirectory(root);
    expect(output.entries.has("done.bin")).toBe(true);
    expect(output.entries.has("cancel.bin")).toBe(true);
    expect((output.entries.get("done.bin") as TestFile).closed).toBe(true);
    expect((output.entries.get("cancel.bin") as TestFile).bytes).toEqual([]);
  });

  it("propagates writer errors without removing completed files", async () => {
    usePlans({ component: { start: page("component", [detail("done.bin"), detail("fail.bin", { download: "fail" })]) } });
    const root = new TestDirectory();

    await expect(downloadChunkDirectory(options(root))).rejects.toThrow("write failed");
    const output = outputDirectory(root);
    expect((output.entries.get("done.bin") as TestFile).closed).toBe(true);
    expect(output.entries.has("fail.bin")).toBe(true);
  });
});
