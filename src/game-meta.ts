import type { Game } from "./types";

/**
 * Static display metadata for the game rail: publisher (厂商) and first
 * release date (发布时间). These are presentation facts, not archive facts,
 * so they live in the frontend next to game-icons.ts instead of the API.
 *
 * releaseDate uses the earliest public launch / public beta date (YYYY-MM-DD).
 * Unknown games fall back to the "其他" group at the bottom of the rail.
 */
export interface GameMeta {
  publisher: string;
  releaseDate: string;
}

export const gameMeta: Record<string, GameMeta> = {
  bh2: { publisher: "米哈游", releaseDate: "2014-01-26" },
  bh3: { publisher: "米哈游", releaseDate: "2016-10-14" },
  hk4e: { publisher: "米哈游", releaseDate: "2020-09-28" },
  hkrpg: { publisher: "米哈游", releaseDate: "2023-04-26" },
  nap: { publisher: "米哈游", releaseDate: "2024-07-04" },
  arknights: { publisher: "鹰角网络", releaseDate: "2019-05-01" },
  endfield: { publisher: "鹰角网络", releaseDate: "2026-01-22" },
  pns: { publisher: "库洛游戏", releaseDate: "2019-12-05" },
  wuwa: { publisher: "库洛游戏", releaseDate: "2024-05-22" },
  bluearchive: { publisher: "悠星", releaseDate: "2021-02-04" },
  aethergazer: { publisher: "勇仕网络", releaseDate: "2022-04-22" },
  tof: { publisher: "完美世界", releaseDate: "2021-12-16" },
  p5x: { publisher: "完美世界", releaseDate: "2025-01-09" },
  nte: { publisher: "完美世界", releaseDate: "2026-04-23" },
  reverse1999: { publisher: "深蓝互动", releaseDate: "2023-05-31" },
  snowbreak: { publisher: "西山居", releaseDate: "2023-07-20" },
  gf2: { publisher: "散爆网络", releaseDate: "2023-12-07" },
  calabiyau: { publisher: "创梦天地", releaseDate: "2024-02-01" },
};

export interface PublisherGroup {
  publisher: string;
  games: Game[];
}

const FALLBACK_DATE = "9999-12-31";

function releaseDateOf(gameId: string): string {
  return gameMeta[gameId]?.releaseDate ?? FALLBACK_DATE;
}

/**
 * Group games by publisher. Groups are ordered by each publisher's earliest
 * release date; within a group games are ordered by release date ascending.
 * Games without metadata are appended in a trailing "其他" group.
 */
export function publisherGroups(games: Game[]): PublisherGroup[] {
  const grouped = new Map<string, Game[]>();
  const unknown: Game[] = [];
  for (const game of games) {
    const meta = gameMeta[game.id];
    if (!meta) {
      unknown.push(game);
      continue;
    }
    const list = grouped.get(meta.publisher) ?? [];
    list.push(game);
    grouped.set(meta.publisher, list);
  }

  const groups: PublisherGroup[] = [...grouped.entries()].map(([publisher, list]) => ({
    publisher,
    games: [...list].sort((a, b) => releaseDateOf(a.id).localeCompare(releaseDateOf(b.id))),
  }));

  groups.sort((a, b) => {
    const earliestA = a.games.map((game) => releaseDateOf(game.id)).sort()[0];
    const earliestB = b.games.map((game) => releaseDateOf(game.id)).sort()[0];
    return earliestA.localeCompare(earliestB);
  });

  if (unknown.length) {
    groups.push({ publisher: "其他", games: unknown });
  }
  return groups;
}
