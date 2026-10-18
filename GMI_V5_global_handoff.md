# Game Manifest Index 项目交接文档

更新日期：2026-10-19（Asia/Shanghai）。本文件保留接手所需的入口、基线和未完成事项；工作规则见 [AGENTS.md](AGENTS.md)，分支与晋级规则见 [BRANCHING.md](BRANCHING.md)。本次核对本地代码、实时 GitHub main、本机 HTTP 服务与前端独立副本配置，补齐 10 月 17 日后端修复及重写记录；没有重新检查服务器、线上前端或执行业务测试。服务器及历史验收均另标核对日期，不以旧记录替代实时状态。

## 1. 项目与入口

Game Manifest Index 索引游戏资源链接、版本和元数据，不持久托管安装包；文件下载按需通过后端流式代理官方内容。前端使用 Vue 3 + TypeScript + Vite，后端使用 FastAPI，资源记录采用 schema v2。

- 本机目录：`D:\Project\Active\Game Manifest Index`；仓库：<https://github.com/kuaichu/Game-Manifest-Index>。
- 前台：<https://gmi.yeque.top>，另有 <https://game-manifest-index-v2.pages.dev>；管理页为 `/admin`，前台不提供管理入口。
- 公网 API：`https://api.yeque.top:9000/gmi/api/v1`；内网 API：`http://10.0.0.234:8000/api/v1`。

| 入口 | 职责 |
| --- | --- |
| `backend/app.py`、`backend/api_contract.py` | 应用启动、公共 API 与数据投影 |
| `backend/admin_routes.py`、`backend/admin_operations.py` | Token 鉴权、采集及探活管理任务 |
| `backend/version_store.py`、`backend/storage_locks.py`、`backend/indexes.py` | canonical 记录与索引的事务提交、共享数据锁及索引构建 |
| `backend/admin_probe.py`、`probe_adapters/service.py` | 探活目标身份核对、仅生成 `current` 的状态转换及统一写回 |
| `backend/admin_state.py` | 管理计划、任务状态及结果详情限额保存 |
| `backend/probe_scheduler.py` | 内置定时探活 |
| `backend/telegram_notify.py` | 批量及定时任务的新版本 TG 通知 |
| `backend/activity_store.py` | 游戏版本更新、全部链接失效的活动记录 |
| `backend/manifest_readers.py`、`src/chunk-download.ts`、`src/chunk-directory-download.ts` | 官方清单解析、Chunk 校验合成与目录写入 |
| `src/components/ChunkFileBrowser.vue`、`src/selected-file-download.ts` | 文件勾选、普通直链流式保存、Chunk 合成、复制及导出 |
| `url_adapters/pc/hypergryph_game_packages.py` | 明日方舟与终末地 PC 官方完整包发现 |
| `src/components/SiteChangelogModal.vue`、`src/site-changelog.ts` | 更新日志搜索、按日期分组及详情展开 |
| `src/composables/useModalScrollLock.ts` | 弹窗背景滚动锁定与恢复 |
| `src/views/ArchiveView.vue`、`src/views/AdminView.vue` | 前台归档与管理页 |
| `url_adapters/service.py`、`probe_adapters/registry.py` | 官方采集和探活注册表，以此判断能力覆盖 |
| `data/`、`.cache/` | 游戏记录、索引及清单；运行状态和缓存 |

## 2. 当前基线

本地与 GitHub 基线对应 2026-10-19 的只读核对；以下提交号是本次文档任务开始前的功能基线，纯文档提交会改变本地提交号，不改变功能代码。服务器、游戏数量及线上调度信息仍为 10 月 17 日快照，本次没有重新连接服务器。

10 月 17 日已完成三轮后端修复及探活写回重写，代码已推送 GitHub main，当次没有部署服务器或同步游戏数据。任务均经过相应的 core / backend / APK / PC 分支验证及集成；临时分支已删除。本次文档任务开始前仅保留本地 `main`、`integration/v5`、`integration/apk`、`integration/pc`，没有历史 snapshot / safety 分支；上轮清理后 GitHub 仅保留 main（本次只重新核对 main 引用），integration 的旧 upstream 显示 gone 不表示需要重建远端分支。

本次只更新 `GMI_V5_global_handoff.md`。用户已有 `AGENTS.md`、`BRANCHING.md`、`PROJECT_STATUS.md`、`README.md` 四份未提交修改，保持原样。`PROJECT_STATUS.md` 的部分基线与历史数量仍过时，仅作历史背景。根目录 README 为用户编辑的内部版本，不得覆盖公开 main README；内部工作约定和交接文档不进入公开 main。文档任务从 `integration/v5@a00d640` 创建 `backend/handoff-current-state`，按约定验证后 squash 到 V5、正常合并至本地 main 并保留文档排除规则，仅本地提交，不推送或写服务器。

历史分支备份在 `C:/Users/Administrator/.codex/backups/gmi-branches/20261002-710f2140fe7f43bf884c496ae7cdeaa0/before-cleanup.bundle`；最近两轮代码任务备份在 `.cache/unified-backend-fixes/completed-task-branches.bundle`、`.cache/probe-rewrite-completed-tasks.bundle`。备份只用于查阅，不应整支合回当前集成分支。

| 项目 | 最近确认的基线 |
| --- | --- |
| 本地功能代码（10 月 19 日） | `integration/v5@a00d640`；`integration/apk@dffdc62`；`integration/pc@a159eeb`。平台分支均已包含 `bd86d40` 的共享探活接口重写，但分别只包含自身的旧写回函数清理；后续任务开始前按 BRANCHING.md 同步所需共享变更 |
| 公开代码（10 月 19 日） | 本次文档任务前本地 main、origin/main 及实时 GitHub main 均为 `cd99c5491fc961c8a9299460cccf3b20f49acf28`；main 与 V5 的 backend、probe_adapters、url_adapters、src 源码一致，整体树差异为 `.gitignore` 和公开分支排除的内部文档。纯本地文档合并之后本地 main 可领先 GitHub，不能据此声称已推送 |
| 服务器代码（10 月 17 日最后核对） | `/opt/GMI@de4bd1ee6af572ab9de183502c528cfbbec103c9`。本对话后续只推送代码并重启本地预览，未部署服务器；10 月 19 日没有重新核实服务器 HEAD，当前实际部署为未确认 |
| 前台发布（10 月 17 日快照） | 两个前台域名首页当时均返回 HTTP 200；本次未重新核对部署、在线 JS 哈希或浏览器交互 |
| 服务器运行环境（10 月 17 日快照） | 虚拟环境 `/opt/GMI/.venv`；FastAPI `0.136.1`、Starlette `1.0.0`；Debian 12、Python 3.11.2 及 `pip check` 通过为更早记录，均未在本次重跑 |
| 服务器服务（10 月 17 日快照） | `gmi-v5.service` 当时 active / enabled，内外网健康接口均返回 200；此前部署为 `0.0.0.0:8000`、单 worker；当前运行状态未重新核实 |
| 服务及环境文件 | `/etc/systemd/system/gmi-v5.service`、`/etc/gmi-v5.env`（最后记录权限 600） |
| 服务器数据及状态目录 | `/opt/GMI/data`、`/opt/GMI/.cache` |
| 线上定时探活（10 月 17 日快照） | 当时启用，每小时，`normal`；调度器运行中且无错误，最近一轮北京时间 13:48:46 启动、13:49:03 完成；当前配置和轮次未重新读取 |
| 每日采集配置（10 月 17 日快照） | 当时保存为启用，时间 `08:00`、`13:23`；外部自动触发、时区与漏跑行为仍未验证 |
| 本机运行（10 月 19 日） | `127.0.0.1:8000` 健康、游戏列表及计划状态接口均连接被拒绝，`127.0.0.1:5173/` 也连接被拒绝；本次没有启动服务。10 月 17 日曾运行最新后端并验证健康与 14 款游戏，属于历史验收 |
| 已知历史部署备份 | `/root/gmi-selected-downloads-backup-c1b153d` 为 10 月 3 日备份；之后的最新服务器备份位置未核实，不作为当前部署基线 |

**游戏数据以服务器 `/opt/GMI/data` 为准，本地仅供参考。** 同一数据存在差异时一律采用服务器内容，即使本地时间戳更晚。仅本地独有、服务器尚未收录的新数据可增量补充；先确认缺失的身份或条目，再保留服务器已有内容、artifact 身份和来源。完整约定见 `AGENTS.md` 的 Server Data Authority。

9 月 30 日对比确认服务器版本和探活证据比本地更新，且服务器保留未提交运行数据。10 月 1 日异环补采增量写入 8 个版本，原记录及清单未覆盖。10 月 3 日多选下载部署只更新代码，部署窗口内服务器 data 目录 1,042 个文件（含锁文件）、管理计划及调度状态逐项核对未变；本地 913 个参考数据文件和五份用户文档也已核对保留。文件数量是该次发布快照，后续采集可能增长。代码更新不等于数据同步，Git 提交或旧快照不能替代服务器实际数据。

10 月 17 日服务器只读扫描到 data 目录 1,109 个文件，其中符合 `schema_version == 2` 且包含 `artifacts` 的 JSON 记录为 649 条（Android 286、Windows 363），异环 PC 74 条。此处仅统计结构与数量，没有重新执行全量 schema 校验。服务器仍有大量未提交运行数据；不得将服务器工作区当作可以清理或用本地 Git 数据覆盖的代码副本。

10 月 3 日以后的主要交付如下；提交用于定位代码，验收记录的适用范围见第 3 节：

| 日期 | 提交或数据操作 | 内容 |
| --- | --- | --- |
| 2026-10-04 | 服务器历史数据补录 | 终末地 PC `0.5.27` 导入 8 个历史分卷，保留历史来源；原 CDN 与 OSS 下载均未恢复，OSS 返回 `403 InvalidObjectState` |
| 2026-10-10 | `e3ee888` | 数据动态按日期紧凑分组，修复更新日志、来源说明、文件详情和移动端版本弹层的背景滚动 |
| 2026-10-11 | `474b1b2` | 所有 HTTP 403 统一判定、展示为不可用，包括历史探活证据 |
| 2026-10-13 | `8a49f24`；公开 main `2301f35` | 优化归档读取、清单缓存、任务状态与下载内存；清单分页、跨页勾选；Blob 合成上限改为 64 MiB |
| 2026-10-17 | `720652a`；公开 main `de4bd1e` | 异环换为 300×300 官方图标，战双及明日方舟换为 192×192 官方应用图标 |
| 2026-10-17 | `c005c8a`、`880a0b9`；main `0f5bd38` | 数据锁重入、管理编辑按资源 ID 匹配、目录配置读改写锁、任务启动失败释放执行槽、探活状态与失效活动判断、普通包缓存并发及递归文件计数修复 |
| 2026-10-17 | `8c3d088`、`42b0300`；main `3085eec` | 记录与索引统一事务；CRUD、探活及鹰角 PC 采集接入，删除分散索引补救；Zstd 分配前限制和下载数据域单次解析 |
| 2026-10-17 | `bd86d40`、`dffdc62`、`a159eeb`；V5 `a00d640`，main `cd99c54` | 探活写回接口重写为只生成 current，身份定位与写入归提交层；移除 Android / PC 整记录写回函数、嵌套 persist 事务及整记录深拷贝；修复重复 URL 无法按资源分别写回 |

### 后端修复后的维护边界

- `version_store.record_index_transaction(record, root)` 在共享进程锁与文件锁内协调一条记录及所属域索引，成功时重建索引，运行异常时恢复两份文件。`persist_v2_record()` 默认同时发布记录及索引；`write_v2_record()` 是仅写记录的底层接口，在 CRUD / 探活事务内使用，不能把它当作完整发布接口。相同记录的嵌套事务可加入外层，不同记录共用同一索引不能嵌套；保留匹配的 legacy 记录不做迁移。异常恢复不保证断电或强杀进程时一致性。
- 管理版本编辑使用 `artifact_id` 匹配资源，前端编辑及 JSON 导入保留可选 ID；不依赖数组位置。目录配置的读改写和版本 CRUD 读取至提交均有数据锁保护；不要单独删除读取前的外层锁。
- 探活提交链为 `admin_probe._run_probe` → `current_fn(identity, target_url, result)` → `_commit_probe`。网络和状态转换在存储事务外执行；转换函数仅接收独立的六个记录身份字段、目标 URL 和探活结果，不接触 canonical 记录。共享入口为 `probe_adapters.service.current_from_result()`，分别复用 Android / PC 字段转换，保留平台校验及官方重定向规则。
- 提交时重新读取最新记录，核对记录身份及 provenance、artifact 身份与元数据、URL 候选除 current 外的元数据，再定位目标；允许未变资源重排，拒绝将旧探活结果写到已经变化的资源。只复制选中路径并替换其 `artifacts[].urls[].current`，一次事务提交记录与索引；事件在提交成功后发布。同一 URL 可属于不同 artifact 或元数据能唯一识别的不同候选；无法唯一定位的重复候选会拒绝提交，不能再按整条记录内 URL 唯一性决定写回对象。
- 旧 `apply_fn` 注入及 `apply_result()`、`apply_android_v2_result()`、`apply_pc_v2_result()` 已删除。应用工厂、管理路由、批量及定时任务统一使用 `current_fn`；不要恢复整记录回调或添加旧接口 fallback。新路径一次探活只进入一次记录事务，不做整记录深拷贝。
- 后台任务启动保存 / 线程启动失败会释放执行槽，忙碌与启动失败分别反馈 409 / 503。手动与批量探活状态选择、版本详情证据状态已统一修正，过期的已知可用证据不再漏记资源转失效的活动。
- 普通包清单缓存按 key 合并并发读取，文件总数递归统计；Zstd 对已知输出大小先检查帧头，未知大小采用 SDK 输出限制。文件内容接口复用已解析的数据域，并在线程池解析，避免在事件循环重复扫描。上述改动保留现有 HTTP 字段语义、schema v2 身份、来源信息与官方端点；管理编辑额外支持可选 artifact_id。

当前已具备归档及文件清单浏览、管理操作、官方采集、手动及定时探活、公开平台与版本路由、按日期分组的更新动态、游戏活动和最近探活时间展示。因缘精灵、蓝色星原及崩坏学园2的图标已本地化。接手时留意以下行为：

- 当前官方自动采集注册覆盖 Android 12 款、PC 10 款，以 `url_adapters/service.py` 为准；归档游戏数不等于自动化覆盖数，探活能力还须按 `probe_adapters/registry.py` 及具体 URL 类型判断。
- 定时轮次先做官方发现，再检查 `official` / `legacy` 中新发现或上次可用的 URL；跳过已失效及未知链接。`normal` 跳过 20 小时内有效证据，`full` 忽略新鲜度。过期状态仅用于仍在轮换范围内的可用 URL；任务互斥，状态目录用于重启续计时。
- 管理页批量探活与定时探活均先发现官方新版本；配置 TG 后，只在发现新版本时通知，没有更新保持静默。单链接、单版本探活不触发整款游戏采集。测试群为 `-1003962096060`，已实际送达过测试消息；Bot Token 在环境配置中，不写入代码、日志正文或交接文档。
- 页脚分别展示定时任务最近启动、下次计划及链接最近实际检测时间；每小时启动不代表每小时重测全部链接，20 小时跳过规则可使检测时间保持不变。时间统一展示为北京时间，规则说明通过次级提示呈现。
- 小窗版本工具栏按可用宽度换行，手机视图标签可横向滑动；更新日志按日期分组，支持标题 / 正文搜索、展开详情和分批浏览历史。
- 数据动态采用按日期紧凑分组的布局；更新日志、来源说明、文件详情和移动端版本弹层打开时锁定背景滚动，关闭后恢复。异环、战双与明日方舟已替换高清官方图标。
- HTTP 403 统一展示为“不可用”，历史证据也按同一规则投影，不再展示为“访问受限”。官方 OSS `HEAD 200` 仅证明可读取元数据，不能据此判定可下载；归档冻结对象的 GET 仍可能返回 `403 InvalidObjectState`。10 月 11 日已核查崩坏3 Android 7.6～7.9 APK 属于这种情况，不能把 PC 完整包的可用结论套用到 Android。
- 蓝色星原 PC / Android 是内测版本归档，没有自动采集或探活；前台按元数据允许官方直链，不把缺少证据解释为已探活未知。终末地 PC 运行时资源不进入批量探活。
- 明日方舟与终末地 PC 共用鹰角完整包适配器，POST `https://launcher.hypergryph.com/api/proxy/batch_proxy` 的 `get_latest_game`，使用各自 appcode；不同于 Android 的 `get_latest_apk`。默认发现只用官方接口。记录沿用 `data/hypergryph/{game}/pc/{version}.json` 和现有 index 结构，不借用第三方归档作为新版本发现或失败回退。
- 终末地 PC 官方完整包 / 补丁的可验证下载链接使用 `beyond-prod.oss-cn-shanghai.aliyuncs.com`；适配器将已验证路径的 `beyond.hycdn.cn` 完整包链接投影为官方 OSS 链接，保留来源与原始链接证据，不做任意 URL 替换。10 月 3 日曾验证 8 个历史 PC 版本的 678 条 OSS 候选，并修复部分旧版 Android APK 下载，不代表所有历史资源始终可用；后来补录的 `0.5.27` 仍不可下载。历史数据修复是单独操作，不能随代码部署上传本地数据。历史完整包 / 补丁有修复不代表新适配器会自动发现所有历史补丁。
- 明日方舟与终末地前台不展示运行时资源入口，历史数据保留。当前 PC 自动发现只注册完整包采集，没有新增运行时资源采集器；隐藏入口不应被解释为这些历史资源仍会自动更新。
- 崩坏：因缘精灵 CBT2 `0.60.2` 已有文件清单，但没有下载 URL 候选；清单存在不代表可以下载或自动采集。
- 米哈游 Chunk 文件详情提供“下载完整文件”规则。桌面 Chrome / Edge 可逐块校验、流式写盘，不受 Blob 文件总大小上限约束；其他浏览器的 Blob 合成上限现为 64 MiB。前端对单 Chunk 的压缩及解压大小各设 512 MiB 校验上限，但正常同源下载路径的后端 Chunk 代理另限制压缩体积为 64 MiB，超过即拒绝；流式模式不会解除单块限制。加密或未知压缩格式仍不支持。
- “下载游戏目录”按所选主资源 / 语音组件重建全部清单文件，不受当前目录或搜索影响；支持进度和取消，在所选目录下新建子目录，不覆盖已有文件。输出是资源目录，不是厂商安装程序；失败或取消保留已完成文件。
- `ChunkFileBrowser.vue` 的文件清单按每页 100 条请求，使用上一页 / 下一页浏览，只挂载当前页；支持勾选、多选、全选本页文件、清空、目录保存、复制和导出，目录不参与勾选。翻页保留跨页选择，全选本页不会自动选中其他页；切换版本、来源、组件、目录或搜索时清空选择并取消当前批量任务。此改动未覆盖其他 `RemoteArtifactTree.vue` 文件树组件。
- 多选下载按详情来源分别执行：普通直链通过同源 `file-content?source=package&identity=...&path=...` 流式保存原文件；Chunk 复用现有分块下载、解压与合成逻辑。均保留完整相对路径、校验大小与 MD5，支持进度 / 取消，在所选目录下新建子目录，不覆盖文件。普通直链复制 / 导出官方 URL；Chunk 复制 / 导出合成配方 JSON，不提供不存在的整文件直链。
- `file-content` API 只接受记录内文件身份和路径，由官方清单解析下载目标；受官方域名、路径、重定向、大小及超时限制，不接收用户指定远端 URL。解决官方 CDN 无 CORS 的浏览器写盘问题，客户端下载经服务器流式中转；失败或断开连接关闭上游资源，不改 canonical 数据。
- 目录下载按安全上下文及 `showDirectoryPicker` 能力区分不可用原因：HTTPS 下缺少接口时提示浏览器不支持，不再误导用户重新使用 HTTPS。Firefox / Safari 当前不支持这条目录写入路径；需要支持目录选择的桌面 Chrome / Edge。
- 下载使用同源 Chunk 内容代理及分页 `chunk-manifests/{identity}/download-plan` 接口。已校验的 Sophon 清单采用最多 8 项、估算驻留体积合计 64 MiB 的实例内存缓存，同时读取同一清单的请求合并；超出单项预算的清单不驻留，不能保证始终避免重复读取。清单分页避免复制整份内容；不写正式记录或持久化缓存。
- 10 月 13 日已优化单版本读取、普通包清单缓存与下载 MD5 分块校验，减少全库扫描、重复解析及整文件缓冲复制。管理任务结果详情按 512 KiB 预算保留前缀，截断时返回 `items_truncated`、`items_total`、`items_omitted`；状态文件仍限制 2 MiB，修复大批量结果导致完成状态无法落盘的问题。详情被截断不代表实际操作只执行了展示的部分。
- 异环 PC 从 `publish_PC/config.xml` 的 `ResConfig` 自动发现 `PC_<数字>` 资源分支；2026-10-01 验收时为 `PC_140`、`1.4.9`；2026-10-02 线上最新记录已为 `1.4.10`，本次未重新请求官方配置确认分支。合法自指终止，坏配置、未知路径、循环或超过 4 个配置明确失败，不回退旧版本；仅使用已验证的主 CDN。幻塔 / P5X 保持原采集路径。
- 异环 PC 已复抓 62 个已有版本并增补 8 个，2026-10-01 共 70 个版本；2026-10-02 线上已增长到 71 个；`1.4.1`、`1.4.3`、`1.4.5` 在两个已确认的官方分支均为 404。历史配置未知字段未借用最新配置补齐。
- 鸣潮文件列表总大小按所选完整清单求和，排除备选补丁，不随搜索、目录或分页改变。`artifact-tree?kind=file` 返回可选 `manifest_total_size`；服务器 1.X 至 3.7 共 47 个有清单的版本已核对一致，3.6 为 83.27 GB、3.7 为 80.52 GB。
- 各游戏文件列表标题显示官方清单或资源包的最后修改时间（北京时间），tooltip 区分来源，随资源 / 语音切换；不是内部每个文件的 mtime。版本 attributes 提供 `file_modified_at` / `file_time_source`，保留异环 `manifest_modified_at`；实际文件列表返回 `file_time` / `file_time_source`。Chunk 利用清单 GET 响应头，其余缺失元数据仅在选中清单时对官方来源做受限 HEAD，内存缓存 64 项 / 10 分钟；版本枚举不联网，不改正式数据。日期缺失、无效或冲突时隐藏，不借用采集或导入时间。站内更新日志位于 `src/site-changelog.ts`，当前已记录至 `2026-10-17`。
- 官方完整包各分卷可以有不同修改时间：分卷编号连续且各卷时间可靠时，标题取最晚分卷时间；同一分卷的候选 URL 时间互相矛盾时仍隐藏，不用部分分卷日期代替完整包。绝区零 3.2.0 完整包为北京时间 `2026.08.22 12:12`；星铁另有 6 个版本恢复日期显示。
- Chunk 清单超过 8 个组件时使用紧凑下拉选择，少量组件保留 chips。绝区零 2.0 后有 91–118 个官方组件，缺失 / 字面 null 名称用资源编号补充，完整保留 identity、浏览及目录下载选择。下载目录按钮左侧间距桌面 14px、移动端 19px；手机下拉框不再因 flex-basis 被拉高。

## 3. 运行与验证

本地准备 Python 3.12、Node.js 20.19+（20.x）或 22.12+。从项目目录安装依赖；以下 FastAPI / Starlette 版本与已验证服务器一致，仓库 requirements 仍采用宽松范围：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt "fastapi==0.136.1" "starlette==1.0.0"
npm ci
```

后端终端：

```powershell
$env:GMI_ADMIN_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host '管理 Token' -AsSecureString)).Password
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

前端另开终端：

```powershell
$env:VITE_API_BASE_URL = '/api/v1'
npm run dev -- --port 5173 --strictPort
```

前台为 `http://127.0.0.1:5173/`，管理页为 `/admin`，健康接口为 `http://127.0.0.1:8000/api/v1/health`。Vite 将 `/api` 转发到本机 8000；按 `Ctrl+C` 停止服务。同一数据和状态目录仅运行一个后端实例 / worker，后台写操作验证使用独立数据副本与状态目录。

### 本机后端与前端独立副本

2026-10-19 实际请求本机 8000 的健康、游戏及公开调度状态接口，以及 5173 首页，均连接被拒绝；本次没有启动服务。10 月 17 日最后一次重启曾运行 `integration/v5@a00d640`，健康正常、游戏列表为 14 款；预览进程没有配置管理及 TG 凭证，自动探活未启用。进程登记在 `.cache/frontend-handoff-backend/process.json`，stdout / stderr 为同目录 `backend-probe-rewrite.*.log`。PID 23548 / 29052 是当时记录，不能据此结束现存进程；重启前先核实端口和进程命令行。

该预览使用 `.cache/local-server/venv/Scripts/python.exe`、数据 `.cache/local-server/runtime-data`、状态 `.cache/frontend-handoff-backend/state`。数据是本机参考副本，可能落后于服务器。需要恢复相同的无管理权限预览时，在项目目录另开终端：

```powershell
$env:GMI_DATA_ROOT = Join-Path (Get-Location) '.cache/local-server/runtime-data'
$env:GMI_STATE_ROOT = Join-Path (Get-Location) '.cache/frontend-handoff-backend/state'
$env:GMI_ADMIN_TOKEN = ''
$env:GMI_TELEGRAM_BOT_TOKEN = ''
$env:GMI_TELEGRAM_CHAT_ID = ''
.\.cache\local-server\venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

前端已按用户要求独立复制到 `D:\Project\Active\Game Manifest Index-src`，包含 `src`、`public`、包配置、Vite / TypeScript 配置及已安装依赖；该副本交给其他 AI 修改，不能擅自覆盖、回拷或同步到仓库。2026-10-19 只读检查确认其 `.env.development.local` 为 `VITE_API_BASE_URL=/api/v1`、`VITE_PROXY_TARGET=http://10.0.0.234:8000`；`vite.config.ts` 从后者读取代理目标，未设置时才回退本机 `127.0.0.1:8000`。当前副本使用服务器后端，并非 10 月 17 日最初准备时的本机代理；这不代表服务器具备最新本地修复，本次也未请求服务器或启动副本验证。

在独立副本目录可执行：

```powershell
Set-Location 'D:\Project\Active\Game Manifest Index-src'
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

若要切换至本机后端，需明确调整该副本的 `VITE_PROXY_TARGET` 为 `http://127.0.0.1:8000` 并重启 Vite；本次仅记录配置，没有修改副本。旧 `.cache/local-server/processes.json`、`start-local-backend.py` 与此前 8018 / 5188 下载验收服务均属历史辅助材料，不应直接当作当前启动配置；`.cache` 不随代码发布。

| 环境变量 | 含义 |
| --- | --- |
| `GMI_ADMIN_TOKEN` | 后端管理 Bearer Token，未配置时管理接口不可用 |
| `GMI_DATA_ROOT`、`GMI_STATE_ROOT` | 数据和状态目录，默认项目下的 `data/`、`.cache/` |
| `GMI_CORS_ORIGINS` | 允许的前端 origin，以逗号分隔 |
| `GMI_TELEGRAM_BOT_TOKEN`、`GMI_TELEGRAM_CHAT_ID` | 新版本 TG 通知的 Bot 与目标群；均由环境提供，Token 不进入仓库 |
| `VITE_API_BASE_URL` | 前端 API 基址，默认 `/api/v1`，生产构建时确定 |

示例见 `.env.production.example`。后端环境修改需重启，生产 API 基址变化需重新构建；Token 不进入前端配置或仓库。

按改动选择相关检查，不默认跑全量测试或构建。固定迁移基线、历史计数及来源白名单测试用于历史快照审计，不应直接用于判断不断更新的线上数据；探活覆盖也不等于所有归档 URL 都必须有适配器，内测归档例外应保留。例如：

```powershell
.\.venv\Scripts\python.exe -m unittest backend.test_api_contract.TemporaryContractTests backend.test_api_contract.HttpUpstreamTests
npm test -- src/selected-file-download.test.ts src/chunk-file-browser.test.ts
```

前端发布前配置生产 `VITE_API_BASE_URL`，运行 `npm run build`，将 `dist/` 部署到支持 SPA 路由回退的静态服务。生产环境不依赖 Vite 代理；后端由 systemd 运行，HTTPS 与 API 前缀由反向代理处理，数据和状态目录需持久化。

服务器只读检查：

```sh
systemctl status gmi-v5 --no-pager
/opt/GMI/.venv/bin/python -m pip check
curl --fail --max-time 10 http://127.0.0.1:8000/api/v1/health
```

管理计划及运行状态分别读取 `/api/v1/admin/probe/schedule`、`/api/v1/admin/probe/scheduler`，需 Bearer Token。

2026-10-19 本次文档更新实际完成：

- 核对本地分支、提交及 main / V5 功能源码差异，`git ls-remote` 确认 GitHub main 仍为 `cd99c54`；核对旧探活函数已移除及当前 current / 事务调用链。
- 本机 8000 的健康、游戏列表、公开调度状态以及 5173 首页均连接被拒绝；没有启动服务、触发采集 / 探活 / TG、同步数据或发布。
- 只读检查前端独立副本的 package、环境与 Vite 代理配置，确认现指向 `10.0.0.234:8000`；未修改或验收该副本。
- 未连接服务器、读取线上管理计划或扫描服务器数据；下列服务器和浏览器结果均为历史记录。本次只做文档检查，不重新运行下述业务测试。

10 月 17 日后端修复期间实际完成的验证（不同轮次有重叠，不累加为最终全量测试数）：

| 对应代码 | 当轮验证及边界 |
| --- | --- |
| `880a0b9` / main `0f5bd38` | 324 项后端、133 项前端相关测试通过，类型检查与生产构建通过 |
| `42b0300` / main `3085eec` | 458 项后端 / 适配器、62 项前端 API / 下载测试通过；覆盖记录与索引恢复、CRUD、探活、采集流水线、Zstd 输出限制、事件循环响应；使用临时数据及假上游，没有写生产数据 |
| `a00d640` / main `cd99c54`（最后重写） | 最终合并代码的 174 项相关测试通过，包括探活提交、管理同步、定时探活、活动、存储事务、调度、任务可靠性与内存、管理 CRUD、Android / PC 转换；覆盖重复 URL、候选重排、无关编辑保留、非法 current 拒绝和索引失败恢复 |
| 最后重写的运行跟踪 | Android 与 Windows 各一次临时探活均写回成功，每次记录事务进入 1 次，整记录深拷贝 0 次；10 月 17 日本机重启后健康接口正常、游戏列表 14 款，公开调度 disabled；未部署服务器或验收生产 UI |

10 月 17 日较早的只读核对曾确认服务器 HEAD、服务 active / enabled、内外网健康、每小时 normal 计划与调度无错误，并统计 649 条 v2 结构记录；当时未执行全量 schema 校验。这些结论只适用于当时，不能替代 10 月 19 日的实时服务器核对。

以下更早的发布验收摘自原对话交付记录，本次未重新运行：

| 日期 | 当时报告的验证 |
| --- | --- |
| 2026-10-10 | 56 项局部测试、类型检查、生产构建及四种窗口宽度的滚轮验收通过，数据动态与弹窗滚动修复上线 |
| 2026-10-11 | HTTP 403 状态相关测试及正式站验证通过，崩坏3 Android 7.6～7.9 APK 均显示不可用 |
| 2026-10-13 | 244 项后端、106 项前端测试通过；正式站分页和真实下载验收通过，服务器与 Cloudflare 已更新 |
| 2026-10-17 | 图标更新上线，正式站桌面及手机高分屏显示已验证 |

上述记录不能证明当前全套测试均通过，也不能替代当前前端脚本、浏览器或全量下载验收。

2026-10-03 多选下载的实际验收如下；临时测试服务使用服务器数据的独立副本，只请求官方源，不对服务器游戏记录执行写入：

| 范围 | 已验证结果 |
| --- | --- |
| 局部检查 | 文件浏览器 18 项、下载 helper 16 项通过，Vue / TypeScript 类型检查通过；服务器候选代码的 21 项相关接口及上游测试通过，覆盖流式响应、断开连接后的释放及错误处理 |
| 普通直链 | 蓝色星原 `baselib.dll`（420,968 bytes）与 `libssl-1_1-x64.dll`（697,912 bytes）实际批量写入浏览器私有目录，独立回读 MD5 与官方清单一致，导出两条官方链接正确 |
| Chunk 合成 | 绝区零 3.2.0 的 `vk_swiftshader_icd.json`、`APMConfig.json` 从官方压缩块合成为 106 / 110 bytes 文件，独立回读 MD5 正确；导出的两份文件配方正确 |
| 目录与取消 | 普通文件 `mj_sdk/res/app_config.dat` 的嵌套路径保留；启动真实文件请求后取消生效；手机 390px 下两类工具栏无越界，不支持目录接口时保存按钮禁用，复制 / 导出仍可用 |
| 线上后端 | 已部署服务实际返回普通 SDK 文件 1,952 bytes 且 MD5 正确，两个 Chunk 内容接口返回 107 / 111 bytes 官方压缩块；公网普通文件接口返回 200，并允许 `https://gmi.yeque.top` CORS |
| 发布与保护 | Cloudflare 部署成功，线上 JS 包含多选入口；服务器为 `c1b153d`，服务 active，调度器运行且无错误；部署窗口内 1,042 个 data 文件及计划状态未变 |

六个独立 headless 场景均通过，报告和脚本在 `.cache/selected-download-verification/browser-report.json`、`verify-browser.cjs`。目录选择接口在测试中替换为浏览器原生 OPFS 临时目录，真实执行创建 / 写入 / 回读；未操作用户目录，也未验收操作系统原生目录选择对话框。线上未重新跑这六个浏览器场景，大文件 / 整游戏下载未以这些小文件结果作保证。

鹰角 PC 首次上线验收从官方接口采集并探活明日方舟 `77.0.0` 的 20 个完整包分卷、终末地 `1.5.3` 的 54 个分卷，均可用；重复发现没有新版本时保持静默。终末地历史 PC OSS 修复验证 8 个版本共 678 条候选，原始字段和其余 1,032 个 JSON 文件保留。报告分别在 `.cache/arknights-discovery/server-acceptance-report.json`、`pc-oss-server-acceptance-report.json`；历史数据修复备份为 `/root/gmi-endfield-pc-oss-data-backup-20261003`。这些版本号和数量对应当次验收，不代表之后实时最新数据。

以下是 2026-10-01 的历史验收，保留为背景，不代表最新发布重新运行：

| 范围 | 已验证结果 |
| --- | --- |
| 最新兼容性提示 | 文件浏览器 14 项局部测试、类型检查及生产构建通过；线上 headless 模拟 HTTPS 下缺少目录接口，提示与禁用状态正确，未在 Firefox 实际运行 |
| 组件与分卷时间 | 后端 72 项（含服务器 Python 3.11）、前端相关 51 项通过；核查 67 个 Chunk 版本与 144 个 archive 包版本；公网绝区零 3.2.0、星铁 4.4.0 完整包日期正确 |
| 视觉与交互 | 独立 headless Chromium 验收桌面 1600×1000、平板 820×1000、手机 390×844；绝区零新旧版、原神、星铁、崩坏3布局正常，末项 / 未命名组件可选，来源切换更新时间；线上手机确认 19px 间距、118 个选项、无页面横向溢出 |
| 鸣潮大小与日期 | 47 个有清单版本总量一致，公网 3.7 为 `86,456,782,554` bytes；其他已列游戏的代表版本官方日期已核对，缺失时间的版本保持隐藏 |
| 异环采集 | 官方总控配置发现 `1.4.9`，公网返回 70 个版本与清单时间 `2026-09-29T20:00:03Z` |
| Chunk 下载 | 公网两个 Chunk 合成 `globalgamemanagers`，完整 MD5 与清单一致；本地 headless 验证单文件 / 目录写入，使用浏览器私有目录，未自动操作用户目录选择器 |
| 最新部署 | 两个前台新 JS 哈希一致，服务健康；1,040 个游戏数据文件及管理调度状态未变 |

上述历史验收记录对应 2026-10-01 的检查，记录中的浏览器及独立测试服务当时已退出，截图及验收记录保存在本机 `.cache/visual-filelists/`；不能把这些结果当作每次发布均重新通过。

2026-10-02 健康核对：前端 315 项测试中 314 通过、1 失败，类型检查及临时目录生产构建通过；后端、采集及探活现有测试共 502 项，其中 497 通过、3 失败、2 跳过。4 项失败分别是管理页旧文案断言、临时环境 FastAPI `0.142.2` 的路由枚举行为与测试不兼容、NTE 固定历史白名单未覆盖 `1.3.14`、探活测试错误要求蓝色星原内测归档也有适配器。测试失败均保留，未据此修改业务代码；不能把本地参考数据或历史断言失配直接当作线上故障。

上述 2026-10-02 健康核对还实际请求了线上健康、Android/PC 代表性版本与资源查询、版本比较、Chunk 清单，以及鉴权保护和调度器读取；内测两款均没有探活候选。当时扫描的 634 条线上 canonical 记录通过 schema 校验，这个数字只计当时已扫描记录，不是当前 data 目录文件总数，也不能证明所有业务行为。未验证项目集中列在下一节。

## 4. 剩余问题

- 每日采集自动触发、外部调度部署、时区及漏跑行为仍为 `UNKNOWN`；保存启用配置不等于任务实际运行。
- retention、多 worker / 多实例协调未实现；macOS 实际运行未核实。记录 / 索引事务只保证运行异常时回滚，不覆盖断电或强杀进程；未提供崩溃日志恢复机制。
- 最新后端代码已推送至 GitHub `main@cd99c54`，本对话没有部署服务器；服务器 HEAD 和线上行为须重新核实，不能宣称已与 GitHub 一致。Cloudflare 部署及其他云端 CI 三平台结果本次也未核实。
- 本机 Git / HTTPS 历史曾出现证书及 TLS 错误。10 月 17 日代码已通过凭证管理器成功推送，本次只重新执行 `git ls-remote`；不表示全部网络或未来写入始终正常，不修改系统证书、路由或凭证存储绕过问题。
- 两个域名的当前前端脚本与全部线上视觉及交互未重新验收；历史 HTTP 成功不能代替浏览器验证。本次未请求线上前端或运行浏览器；后续浏览器与工具边界遵循 `AGENTS.md`。
- 鸣潮 `3.5.0` 历史清单 / 记录缺少可追溯官方来源时间，暂不显示日期，大小正常；其他无法确认官方时间的历史版本也隐藏日期，不编造或借用时间。
- 部分历史完整包已失效或没有可靠时间证据，例如原神 5.5.0 有分卷 404，不能保证所有完整包来源都显示日期。
- 整目录与多选目录下载需要支持 File System Access API 的桌面 Chrome / Edge 和安全上下文；Blob 合成现限 64 MiB。流式保存没有该文件总大小上限，但历史超过 512 MiB 的文件仅验证了可进入流式路径，百 GB 整游戏尚未做全量实下载，单 Chunk 仍受前后端限制。不支持自动断点续传，关闭或离开页面会取消任务。原生目录选择对话框尚未自动验收，手机 / Firefox 的替代入口以能力模拟验证，不代表已在各浏览器实际运行。
- 已知官方归档冻结的历史下载无法靠切换 OSS 域名恢复，包括终末地 PC `0.5.27` 和上述崩坏3 Android APK；需要官方恢复对象访问。本次未重新请求这些安装包，历史可用性不能视为永久有效。
- 历史 JSON 及采集编码源头尚未全面修复，已有乱码修复仅覆盖指定展示位置。
- 任务结束快照保存失败时，已完成的操作可能被归类为失败；尚未定义并验证该场景的产品语义，未纳入本轮修复。多次并发探活同一候选的提交仍可能由后完成者覆盖 current，未实现基于探活开始时间的结果淘汰。
