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
    id: "2026-11-17-mobile-game-drawer",
    date: "2026-11-17",
    title: "手机上切换游戏更好找",
    body: "手机等小屏幕上，顶部不再只有一排没有名字的游戏小图标，改为显示当前游戏；点一下展开游戏列表，按厂商分组并可搜索游戏名称或代号。",
  },
  {
    id: "2026-11-17-file-toolbar-one-row",
    date: "2026-11-17",
    title: "文件列表顶部更紧凑",
    body: "同时提供完整包文件和 Chunk 分块的版本，“数据来源”和“组件清单”合并到同一行，文件列表能多露出一些。拖动切换视图时，原来的选项会变暗、目标选项变亮，更容易看出松手后会去哪。",
  },
  {
    id: "2026-11-17-mode-tab-motion",
    date: "2026-11-17",
    title: "视图切换更顺滑",
    body: "切换完整包、文件列表、版本对比等视图时，高亮会滑到新选项，下方内容淡入显示；也可以按住当前选项拖到别的选项上，松手即切换。切到没有搜索框的视图（如版本对比）时，选项栏不再往右偏。系统开启“减少动态效果”时不播放动画。",
  },
  {
    id: "2026-11-16-compare-and-search-polish",
    date: "2026-11-16",
    title: "版本对比和搜索更顺手",
    body: "版本对比页的“基准版本”移到最左边，点新增、删除、修改的统计卡片可以直接筛选，再点一次取消；每条差异改用 #1、#2 这样的序号，大小没变的会淡化显示，方便看出真正改了什么。搜索框输入内容后右侧出现 ✕，一键清空。文件列表没勾选文件时，批量操作栏收成一行，说明文字可点“? 说明”展开。页面顶部的留白也收紧了一些。",
  },
  {
    id: "2026-11-16-unified-file-list",
    date: "2026-11-16",
    title: "文件列表样式统一",
    body: "各游戏的文件列表改为同一种样式：文件夹排在前面，各列对齐，行距更紧凑，复制、下载等按钮在鼠标移到该行时显示。工具栏的“下载游戏目录”挪到组件选择旁边，上下两排控件统一为同样高度。",
  },
  {
    id: "2026-11-16-wuwa-pc-resource-packs",
    date: "2026-11-16",
    title: "鸣潮 PC 收录 3.8.0 画质包",
    body: "鸣潮 PC 从 3.8.0 起改为“公共包 + 画质包”的方式发布：公共包是必装部分，另有 SD、HD、UHD 三档画质包，安装时选一档即可。本站已按新方式收录，每个包都有完整文件清单和更新补丁。",
  },
  {
    id: "2026-11-16-wuwa-pack-picker",
    date: "2026-11-16",
    title: "鸣潮文件列表可切换画质包",
    body: "鸣潮 3.8.0 及之后版本的文件列表顶部可以在公共包和各档画质包之间切换，默认显示公共包；下方列出 SD、HD、UHD 三种安装组合各自的总大小。总大小和“索引信息”会跟着所选的包变化。3.7.1 及更早的版本不受影响。",
  },
  {
    id: "2026-11-16-lighter-home-styles",
    date: "2026-11-16",
    title: "首页加载更轻",
    body: "管理后台的样式不再随首页一起下载，首页的样式文件减少约四成。",
  },
  {
    id: "2026-11-13-beijing-time-activity",
    date: "2026-11-13",
    title: "数据动态统一显示北京时间",
    body: "数据动态和游戏页“最近资源变动”里的时间与日期分组统一按北京时间显示，不再随访问者电脑的时区变化。",
  },
  {
    id: "2026-11-02-source-provenance-wording",
    date: "2026-11-02",
    title: "来源说明更准确",
    body: "改正各游戏来源说明中不准确的描述，补充内测版本的来源，并说清各类校验值分别代表什么。",
  },
  {
    id: "2026-11-01-activity-timeline",
    date: "2026-11-01",
    title: "数据动态改为紧凑时间线",
    body: "数据动态按日期分组，日期标题在滚动时固定在顶部，每条记录更紧凑。同一次发布的 PC 与 Android 记录合并为一行，3.3.0 与 3.3 这类写法不同的同一版本也会合并；新增按游戏名、版本号或平台搜索。游戏页的“最近资源变动”同样会把这类发布的两个平台都列出来。",
  },
  {
    id: "2026-11-01-control-strip-and-compare-copy",
    date: "2026-11-01",
    title: "优化版本切换栏与对比说明",
    body: "视图较多的游戏在常见桌面宽度下，搜索框不再单独占一行；空间不足时改为版本与搜索在上、视图切换在下的两行布局。版本对比页的说明改为更易懂的文字。",
  },
  {
    id: "2026-10-22-chunk-only-version-browsing",
    date: "2026-10-22",
    title: "修复仅含 Chunk 版本的浏览",
    body: "有些米哈游版本只提供 Chunk 分块下载、没有完整包，以前打开这类版本会被跳回旧版本。现在会停留在所选版本，并提示切换到文件视图；文件视图默认显示该版本可用的 Chunk 数据。",
  },
  {
    id: "2026-10-22-responsive-file-views",
    date: "2026-10-22",
    title: "优化窄屏文件与分块视图",
    body: "调整文件列表、分块清单和视图切换按钮在手机等窄屏上的排列，页面不再需要左右拖动。过长的文件名和清单信息可以查看完整内容，手机上的分块下载按钮也更紧凑。",
  },
  {
    id: "2026-10-22-activity-and-initial-load",
    date: "2026-10-22",
    title: "精简游戏活动展示",
    body: "游戏页的活动栏只显示最近一次版本更新，同一版本的 PC 和 Android 各占一条，不再堆着旧记录。",
  },
  {
    id: "2026-10-17-game-icon-quality",
    date: "2026-10-17",
    title: "提升游戏图标清晰度",
    body: "异环、战双帕弥什、明日方舟替换为官方高清图标，改善侧栏及数据动态在高分屏上的模糊显示。",
  },
  {
    id: "2026-10-13-memory-and-large-lists",
    date: "2026-10-13",
    title: "优化大清单浏览与下载",
    body: "文件清单改为分页浏览，可以跨页勾选，打开大目录时不再卡顿。读取清单和下载 Chunk 时占用的内存更少；同时修复了大批量任务完成后状态没有保存下来的问题。",
  },
  {
    id: "2026-10-11-http403-unavailable",
    date: "2026-10-11",
    title: "统一 HTTP 403 链接状态",
    body: "服务器拒绝访问（HTTP 403）的链接统一显示为“不可用”，历史记录也一样，不再单独显示为“访问受限”。",
  },
  {
    id: "2026-10-10-changelog-layout-and-modal-scroll",
    date: "2026-10-10",
    title: "优化数据动态列表与弹窗滚动",
    body: "数据动态按日期分组，游戏、平台和版本一目了然，并修正终末地图标在深色背景下的显示。打开更新日志、来源说明、文件详情或手机上的版本选择时，背后的页面不再跟着滚动。",
  },
  {
    id: "2026-10-03-selected-files-download",
    date: "2026-10-03",
    title: "文件清单支持多选下载",
    body: "文件清单可以勾选多个文件，在电脑版 Chrome 或 Edge 中选一个文件夹批量保存，保留原有目录结构，并核对大小和 MD5。普通文件直接下载，Chunk 文件会自动拼成完整文件。其他浏览器可以复制或导出官方下载链接，Chunk 文件则导出拼合所需的清单。",
  },
  {
    id: "2026-10-03-endfield-official-oss",
    date: "2026-10-03",
    title: "修复终末地历史版本下载",
    body: "终末地 PC 完整包和更新补丁改用官方长期有效的下载地址，之后自动收录的版本也一样；同时修复了旧版 Android 安装包无法下载的问题。原来的链接仍保留在记录里；“运行时资源”入口已移除。",
  },
  {
    id: "2026-10-03-hypergryph-pc-discovery",
    date: "2026-10-03",
    title: "新增明日方舟与终末地 PC 自动采集",
    body: "两款游戏的 PC 完整包现在会从鹰角官方启动器自动发现并收录，可以查看各分卷大小和 MD5，并检测链接是否可用。批量或定时检测发现新版本时，可以自动发 TG 通知。已有的历史记录不受影响。",
  },
  {
    id: "2026-10-03-probe-status-clarity",
    date: "2026-10-03",
    title: "区分定时检查与链接检测时间",
    body: "页面底部分别显示定时检查上次开始和下次计划的时间，以及链接最近一次实际检测的时间。20 小时内检测过的链接会被跳过，所以检测时间没变不代表服务停了，页面上也写明了这一点。",
  },
  {
    id: "2026-10-03-changelog-browsing",
    date: "2026-10-03",
    title: "更新日志更好浏览",
    body: "更新日志现按日期分组，支持搜索标题和正文、展开记录详情，并可分批浏览更早的历史记录。",
  },
  {
    id: "2026-10-03-version-selector-layout",
    date: "2026-10-03",
    title: "修复小窗版本选择栏布局",
    body: "修复窗口较窄时版本选择框和视图标签叠在一起、最后一个标签被截掉的问题。工具栏放不下时自动换行；手机上仍可左右滑动切换视图。",
  },
  {
    id: "2026-10-02-telegram-version-notification",
    date: "2026-10-02",
    title: "新增 TG 新版本通知",
    body: "配置 TG 后，批量检测和定时检测会先查官方有没有新版本，有更新就自动通知，没有就不打扰。单独检测某个链接或版本时，只检查选中的那一项。",
  },
  {
    id: "2026-10-01-wuwa-file-list-size",
    date: "2026-10-01",
    title: "修正鸣潮文件列表总大小",
    body: "鸣潮文件列表的总大小改为按当前版本的完整文件清单计算，不再把补丁重复算进去。1.x 到 3.7 已收录清单的版本都能显示正确大小。",
  },
  {
    id: "2026-10-01-file-list-modification-time",
    date: "2026-10-01",
    title: "更多游戏文件列表显示文件时间",
    body: "各游戏文件列表的标题旁新增文件时间，显示官方清单或资源包的最后修改时间（北京时间）。切换资源或语音时会跟着更新；时间无法确认的历史版本暂不显示。",
  },
  {
    id: "2026-10-01-ember-pc-resource-branch",
    date: "2026-10-01",
    title: "异环 PC 继续收录新版本",
    body: "官方调整了异环 PC 的资源发布方式，本站的采集已经跟上，新版本和文件清单会继续收录。",
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
    body: "异环文件列表的标题旁新增文件时间，显示官方清单的最后修改时间（北京时间）。",
  },
  {
    id: "2026-09-30-chunk-download",
    date: "2026-09-30",
    title: "Chunk 下载可拼成完整文件",
    body: "Chunk 分块可以直接下载并拼成完整文件，也可以选好游戏资源和语音，一次保存成完整的游戏目录。下载时能看到进度，也可以随时取消。保存游戏目录需要使用电脑版 Chrome 或 Edge。",
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
