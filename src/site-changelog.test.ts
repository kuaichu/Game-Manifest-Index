import { describe, expect, it } from "vitest";
import { groupSiteChangelogByDate, searchSiteChangelog, type SiteChangelogEntry } from "./site-changelog";

describe("site changelog data helpers", () => {
  it("keeps same-day order while grouping dates newest first", () => {
    const shuffledEntries: SiteChangelogEntry[] = [
      { id: "older-first", date: "2026-04-12", title: "Older first", body: "" },
      { id: "newer-first", date: "2026-04-14", title: "Newer first", body: "" },
      { id: "older-second", date: "2026-04-12", title: "Older second", body: "" },
      { id: "newer-second", date: "2026-04-14", title: "Newer second", body: "" },
      { id: "middle", date: "2026-04-13", title: "Middle", body: "" },
    ];
    const groups = groupSiteChangelogByDate(shuffledEntries);

    expect(groups.map(({ date }) => date)).toEqual(["2026-04-14", "2026-04-13", "2026-04-12"]);
    expect(groups[0].entries.map(({ id }) => id)).toEqual(["newer-first", "newer-second"]);
    expect(groups[2].entries.map(({ id }) => id)).toEqual(["older-first", "older-second"]);
  });

  it("searches title and body across a long history and trims case-insensitively", () => {
    const entries: SiteChangelogEntry[] = Array.from({ length: 240 }, (_, index) => ({
      id: `entry-${index}`,
      date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
      title: `历史记录 ${index}`,
      body: index === 239 ? "在正文中包含 Chunk 历史检索词" : "普通正文",
    }));
    entries[217].title = "较早版本的 UniqueTitleMarker";

    expect(searchSiteChangelog(entries, "  uniquetitlemarker ").map(({ id }) => id)).toEqual(["entry-217"]);
    expect(searchSiteChangelog(entries, " CHUNK 历史检索词 ").map(({ id }) => id)).toEqual(["entry-239"]);
    expect(searchSiteChangelog(entries, "  ")).toHaveLength(240);
  });
});
