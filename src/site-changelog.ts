export interface SiteChangelogEntry {
  id: string;
  date: string;
  title: string;
  body: string;
}

export interface SiteChangelogDay {
  date: string;
  entries: SiteChangelogEntry[];
}

export const siteChangelog: SiteChangelogEntry[] = [
  {
    id: "2026-10-03-endfield-official-oss",
    date: "2026-10-03",
    title: "修复终末地历史版本下载",
    body: "终末地 PC 完整包和更新补丁改用官方 OSS 稳定链接，后续自动采集也保存该链接；修复旧版 Android APK 下载。原始来源和历史链接保留，运行时资源入口已移除。",
  },
  {
    id: "2026-10-03-hypergryph-pc-discovery",
    date: "2026-10-03",
    title: "新增明日方舟与终末地 PC 自动采集",
    body: "两款游戏的 PC 完整包现通过鹰角启动器官方 API 自动发现并收录，支持分包大小、MD5 和链接探活。终末地下载链接保留官方签名；批量与定时探活发现新版本时可自动通知 TG。历史记录和运行时资源保留原有来源。",
  },
  {
    id: "2026-10-03-probe-status-clarity",
    date: "2026-10-03",
    title: "区分定时检查与链接检测时间",
    body: "页脚分别显示定时任务最近启动、下次计划和链接最近实际检测时间，并说明普通模式的 20 小时跳过规则，避免将检测时间未变化误认为服务器停止运行。",
  },
  {
    id: "2026-10-03-changelog-browsing",
    date: "2026-10-03",
    title: "更新日志浏览优化",
    body: "更新日志现按日期分组，支持搜索标题和正文、展开记录详情，并可分批浏览更早的历史记录。",
  },
  {
    id: "2026-10-03-version-selector-layout",
    date: "2026-10-03",
    title: "修复小窗版本选择栏布局",
    body: "修复窄窗口中版本选择框与视图标签重叠、末尾标签被裁切的问题。工具栏按可用宽度自动换行；手机仍可横向滑动切换视图。",
  },
  {
    id: "2026-10-02-telegram-version-notification",
    date: "2026-10-02",
    title: "新增 TG 新版本通知",
    body: "配置 TG 后，批量和定时探活会先检查官方新版本，发现更新时自动通知；没有新版本时保持静默。单链接和单版本探活只检查指定目标。",
  },
  {
    id: "2026-10-01-wuwa-file-list-size",
    date: "2026-10-01",
    title: "修正鸣潮文件列表总大小",
    body: "鸣潮文件列表总大小现按当前版本的完整文件清单计算，避免重复计入补丁。1.X 至 3.7 已收录清单的版本均可显示正确大小。",
  },
  {
    id: "2026-10-01-file-list-modification-time",
    date: "2026-10-01",
    title: "更多游戏文件列表显示文件时间",
    body: "各游戏文件列表标题旁新增文件时间，显示官方清单或资源包的最后修改时间，统一以北京时间展示。切换资源或语音时同步更新；无法确认时间的历史版本暂不显示。",
  },
  {
    id: "2026-10-01-ember-pc-resource-branch",
    date: "2026-10-01",
    title: "异环 PC 资源更新",
    body: "异环 PC 资源现可跟随官方配置切换到当前资源分支，继续收录新版本和文件清单。",
  },
  {
    id: "2026-10-01-ember-pc-history",
    date: "2026-10-01",
    title: "补充异环 PC 历史版本",
    body: "补充 1.3.14 及 1.4 系列中官方清单可获取的版本，现已收录至 1.4.9，共 70 个版本。支持浏览对应版本的文件清单。",
  },
  {
    id: "2026-10-01-ember-file-list-modification-time",
    date: "2026-10-01",
    title: "异环文件列表新增文件时间",
    body: "异环文件列表标题旁新增文件时间，显示官方清单文件的最后修改时间，统一以北京时间展示。",
  },
  {
    id: "2026-09-30-chunk-download",
    date: "2026-09-30",
    title: "Chunk 下载功能更新",
    body: "支持将 Chunk 分块合并下载为完整文件，也可选择游戏资源和语音，直接保存为完整游戏目录。下载时可查看进度或随时取消。游戏目录下载需使用桌面版 Chrome 或 Edge。",
  },
  {
    id: "2026-09-27-sprite-pc-manifest",
    date: "2026-09-27",
    title: "新增《崩坏：因缘精灵》PC 文件清单",
    body: "《崩坏：因缘精灵》国服 CBT2 0.60.2 版本的 PC 文件清单现已收录，共 566 个文件。支持按目录浏览和搜索，并可查看文件大小与 MD5 校验信息。",
  },
];

export function groupSiteChangelogByDate(entries: readonly SiteChangelogEntry[]): SiteChangelogDay[] {
  const days = new Map<string, SiteChangelogEntry[]>();
  for (const entry of entries) {
    const day = days.get(entry.date);
    if (day) day.push(entry);
    else days.set(entry.date, [entry]);
  }
  return [...days]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([date, groupedEntries]) => ({ date, entries: groupedEntries }));
}

export function searchSiteChangelog(entries: readonly SiteChangelogEntry[], query: string): SiteChangelogEntry[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [...entries];
  return entries.filter((entry) =>
    `${entry.title}\n${entry.body}`.toLowerCase().includes(normalized),
  );
}
