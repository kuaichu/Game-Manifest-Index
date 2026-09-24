# Game Manifest Index 项目交接文档

更新日期：2026-09-24（Asia/Shanghai）

本文按当前 Git、代码、服务器状态和本会话实际验证结果整理。项目名称统一使用 **Game Manifest Index**。保留现有文件名 `GMI_V5_global_handoff.md` 作为交接入口；本机目录、环境变量、分支和服务器服务名是既有技术标识，本轮未重命名。

## 当前结论

- 定时探活、探活状态展示修复、未知筛选修复、前台管理入口移除及蓝色星原 PC / Android 归档下载展示修复，已提交并推送到 GitHub。
- 定时探活可用 URL 轮换修复的功能提交为 `c363cdf`；交接文档提交后 `integration/v5` tip 为 `d65078b`，`main` tip 为 `3abae81`。交接文档保留在 `integration/v5`；`main` 按公开仓库清理约定不跟踪内部交接文档。
- Debian 12 服务器 `10.0.0.234` 的后端位于 `/opt/GMI`，代码 tip 为 `3abae81`（运行时代码与 `ba78e67` 相同）；systemd 服务 `gmi-v5.service` 为 `active`、`enabled`，监听 `0.0.0.0:8000`，单 worker。
- 内网 API：`http://10.0.0.234:8000/api/v1`。本轮服务重启后健康及蓝色星原域能力接口均为 200；公网 API 已确认为 `https://api.yeque.top:9000/gmi/api/v1`，健康、域、artifact 和文件清单接口均已验证。
- 服务器计时器 `running=true`，现有计划保持 `enabled=true`、`interval_hours=12`、`mode=normal`；2026-09-24 发布验收时下一轮为 `2026-09-24T08:17:26Z`。
- 本机数据仍有大量未提交修改。迁移快照已在服务器核对一致；后续本机与服务器各自的探活和管理操作不会通过 Git 自动同步。
- 日常工作区 `E:\Project\Active\GMI V5` 仍保留大量未提交的其他游戏数据、README 和新增条目；本次发布在隔离工作树中完成，未纳入这些变更。

## 项目与入口

Game Manifest Index 索引游戏资源链接、版本及元数据，不托管安装包。前端使用 Vue 3 + TypeScript + Vite，后端使用 FastAPI；资源记录采用 schema v2。

- 本机日常目录：`E:\Project\Active\GMI V5`。
- GitHub：<https://github.com/kuaichu/Game-Manifest-Index>。
- 后端入口：`backend/app.py`。
- 前台页面：`src/views/ArchiveView.vue`；管理页：`src/views/AdminView.vue`。
- 前台侧栏已移除“管理后台”链接，`/admin` 路由、Token 鉴权及后台功能仍保留。
- `url_adapters/` 负责官方来源发现与整理，`probe_adapters/` 负责探活及结果应用。
- `data/` 保存记录、索引和清单；`.cache/` 是默认状态及缓存目录。
- `README.md` 面向 GitHub 访客，仅介绍项目用途、功能、游戏支持和边界；安装、启动、环境变量及部署说明保留在本文。分支晋级以 `BRANCHING.md` 为最高仓库级规则。
- 新增内测归档：`data/manjuu/azurpromilia/pc/0.3.0.6.json`、`index.json` 和 `manifests/0.3.0.6/pg_item_v2.json`。版本记录含 644 个 `pg_chunk` segment artifact 和 1 个 `pg_item_v2` file-manifest artifact；独立文件清单含 34,758 个文件，官方 URL 由清单 base URL 与相对路径还原。
- 新增 Android 内测 APK：`data/manjuu/azurpromilia/android/0.3.0.2634121.json` 和 `index.json`，后端自动识别默认域 `azurpromilia-android`。仅保存官方直链和元数据，未注册自动采集或探活适配器。
- `data/catalog.admin.json` 注册游戏 `azurpromilia`（蓝色星原：旅谣）和 `azurpromilia-pc`；厂商为 `manjuu`，域能力为 `packages/files/archive`，适配器显示为 `generic`。图标使用 Apple App Store `artworkUrl512` 远程地址；前端厂商显示元数据为“蛮啾网络”。
- 蓝色星原没有注册自动采集适配器，也不会进入批量或定时探活候选；PC 版本的 645 个 URL 和 Android 内测 APK 的 1 个 URL 均没有 `urls[].current` 探活证据。
- 蓝色星原域仅声明 `metadata_inference`、`live_probe=false`；前端隐藏该游戏的“无证据”徽章并允许官方直链下载，不伪造探活结果。其他游戏仍保留原有证据门控。
- 2026-09-24 定时探活修复已在独立工作树完成真实本地调度验证并发布：候选只保留 `official` / `legacy` 中当前状态为 `available` 的 URL；新发现且没有 `current` 的 URL 首次进入探活；`unavailable` / `unknown` URL 后续跳过；蓝色星原 Android / PC 候选继续为 0。
- 证据过期投影已与定时探活候选资格联动：仍在轮换范围内的可用 URL 才会显示过期状态；不再轮换的旧失效 URL 保留 `unavailable`，不附加“证据过期”或下载门控。

## 本地开发与运行

从上述本机日常目录打开 PowerShell。准备 Python 3.12、Node.js 20.19+（20.x）或 22.12 及以上、npm、Git 和 `curl`。服务器另已验证 Debian 12 / Python 3.11.2。

首次安装：

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

前端终端：

```powershell
$env:VITE_API_BASE_URL = '/api/v1'
npm run dev -- --port 5173 --strictPort
```

前台 `http://127.0.0.1:5173/`，管理页 `http://127.0.0.1:5173/admin`，健康检查 `http://127.0.0.1:8000/api/v1/health`。Vite 将 `/api` 转发到本机 8000。开发终端保持运行，按 `Ctrl+C` 停止对应服务；同一数据 / 状态目录仅允许一个后端 worker 或实例。

| 环境变量 | 使用方与含义 |
| --- | --- |
| `GMI_ADMIN_TOKEN` | 后端管理 Bearer Token，未设置时管理接口不可用 |
| `GMI_DATA_ROOT` | 后端数据目录绝对路径，默认仓库下的 `data/` |
| `GMI_STATE_ROOT` | 后端状态目录绝对路径，默认仓库下的 `.cache/` |
| `GMI_CORS_ORIGINS` | 后端允许的前端 origin，多个值以逗号分隔 |
| `VITE_API_BASE_URL` | 前端 API 基址，默认 `/api/v1`，生产构建时确定 |

示例文件为 `.env.production.example`。后端读取进程环境，配置变化需重启；前端生产 API 地址变化需重新构建。Token 不放进前端配置。后台写操作测试使用独立数据副本和状态目录。

常用检查按改动选择：

```sh
python -m unittest backend.test_probe_scheduler backend.test_scheduled_probe_engine backend.test_admin_sync_operations backend.test_admin_version_admin
npm test -- --run src/admin-view-capabilities.test.ts src/route-state.test.ts
npm run build
```

后端主要使用 `unittest`，前端使用 Vitest；需要完整前端回归时运行 `npm test`。普通文档修改不必运行代码测试或构建。

### 定时探活实现约定

- `GET /api/v1/admin/probe/schedule` 读取计划，`PUT` 保存计划；`GET /api/v1/admin/probe/scheduler` 返回运行状态。这些接口均受管理鉴权保护。
- 计划支持 1～168 小时间隔及 `normal` / `full`；首次启用或修改后等待完整周期，相同计划不重置倒计时。
- 每 5 秒检查一次，UTC 计算间隔，前端按浏览器时区展示。
- `normal` 跳过 20 小时内有效的可用 URL 证据，`full` 忽略新鲜度；两者均先从官方来源发现新 URL，再轮换 `source_kind=official` / `legacy` 中新发现或上次可用的链接，跳过已失效及未判定链接。
- 自动任务、手动批量任务、单 URL / 单版本探活互斥；忙时顺延，停机漏跑合并为一轮。终末地 PC `.chk/.blc` 运行时资源不进入批量探活。
- `admin/probe_scheduler.json` 保存下次执行时间；保留状态目录才能重启续计时。派发前先保存下周期，若此时崩溃可能跳过本轮；派发失败留错误并下周期重试。
- 停用计划取消未来触发，已运行任务单独取消。关闭服务会请求取消任务并最多等待 30 秒；不支持多 worker / 多实例协调。

### 通用部署说明

前端运行 `npm run build` 后将 `dist/` 放到支持 SPA 路由回退的静态服务。构建前配置 `VITE_API_BASE_URL`；生产部署不能依赖 Vite 开发代理。

后端由 systemd 等服务管理器运行，启动命令及现有配置见后文。HTTPS、前缀转发由反向代理处理；跨域通过 `GMI_CORS_ORIGINS` 指定。数据目录和状态目录需持久化、可写；代码更新、数据迁移和计划状态更新分别处理，不能用 `git pull` 替代数据同步。

## Git 与工作区

以下为 2026-09-16 的历史发布引用；当前提交见文首和文末 2026-09-24 记录：

| 功能发布引用 | 提交 | 说明 |
| --- | --- | --- |
| `integration/v5` 功能基线 | `fd4dcd6` | 蓝色星原 Android APK 归档与展示修复发布；其后仅有交接文档提交 |
| `main` 功能基线 | `2714bb1` | 正常合并 `integration/v5`；其后仅有交接文档提交 |
| `codex/project-overview` | `c7538db` | 历史任务分支，保留原引用 |
| `data/azurpromilia-apk` | `9bd9647` | 蓝色星原 Android APK 数据与前端展示修复，已 squash 到 `integration/v5` |
| 服务器 `/opt/GMI` | `2714bb1` | 与当前 main 的功能代码内容一致，已重启验收 |

此前 PC 发布过程：蓝色星原任务分支提交 `9e41f49`，squash 到 `integration/v5` 得到 `4d71430`；由于 `main` 保留此前空提交，使用正常合并得到 `1747971`，随后推送 GitHub 并部署服务器。本次 Android 发布记录见文末补充。

2026-09-15 16:15 本机统计有 565 项已跟踪 `data/` 修改、13 项未跟踪数据条目。此前发布排除了这些内容和本交接文档。它们来自历史同步、探活或管理操作，不可 reset、clean、覆盖或直接批量提交。

- 本交接文档已在本轮更新，并随文档提交晋级到 `integration/v5` / `main`。
- `E:\Project\Active\GMI V5-main-release` 是晋级时创建的 main worktree；其他历史 worktree 仍存在。
- 不要擅自删除 worktree 或任务分支。下一次变更前重新检查分支占用和用户改动。
- 此前蓝色星原 PC 任务修改了 catalog、后端厂商/官方域白名单、探活候选排除、仅元数据直链下载展示、前端通用 file-manifest 展示与分页。本次新增 Android APK 数据并统一前台验证状态隐藏逻辑；未修改其他游戏数据，也未更改服务器计划或环境变量名。功能代码已推送并部署至服务器 `2714bb1`。

## 已完成能力与最近修复

已具备游戏 / 模块目录管理、版本管理、PC artifact 编辑、手动采集和探活、任务进度和日志，以及内置定时探活。

`c7538db` 包含 23 个功能文件，主要内容：

1. `backend/probe_scheduler.py`：APScheduler 3.x 随 FastAPI 生命周期启停，保存下次执行时间，支持普通 / 全量模式、UTC 周期、忙时顺延、漏跑合并和单 worker 互斥。
2. `backend/app.py`、`admin_routes.py`、`admin_state.py`、`admin_operations.py`、`admin_probe.py`：调度器、受保护状态接口与现有执行器集成。
3. `src/composables/useArchiveArtifactsLoader.ts`：APK 兼容接口即使 `http_code=null`，只要已有布尔探活结论和检查时间，也可正确显示结论。解决“版本选择器不可用、卡片未验证”的矛盾，保留 HTTP 403 的未判定状态。
4. `src/operation-scope.ts`、`src/views/AdminView.vue`：未知计数和列表统一排除 `ok=false` 的异常，展示 HTTP 拒绝、缺少文件证据、OSS 归档未恢复等原因，不再将未知写成“正常”。
5. `src/views/ArchiveView.vue`、`src/styles.css`：移除前台管理入口及其桌面 / 移动端专用样式；直接访问 `/admin` 仍可用。
6. `.github/workflows/probe-scheduler.yml`：Windows / Ubuntu / macOS、Python 3.12 定时器兼容性矩阵。该文件已推送，但本会话未取得云端三平台全部通过的结果。

此前已发布：探活 curl 硬超时、Endfield 运行时资源排除、OSS 归档识别、旧 HTTP URL 探活证据保留、单版本探活完成后的同源页面刷新、结构化日志、Chunk 类别名展示层乱码修复。

## 适配器覆盖

以注册表为准，不把历史数据存在与自动采集能力混为一谈：

- Android 自动采集 / 探活：12 款，包括原神、星铁、绝区零、崩坏3、崩坏学园2、明日方舟、终末地、鸣潮、战双、幻塔、P5X、异环。
- PC 自动采集：8 款，包括原神、星铁、绝区零、崩坏3、鸣潮、幻塔、P5X、异环。
- PC 探活：上述 8 款加明日方舟、终末地，共 10 款。后两者未注册到日常 PC 自动采集。
- 米哈游 PC 按 packages 和 chunks 两个阶段采集，保持同一 canonical 记录及已有身份。
- 注册位置：`url_adapters/service.py` 的 `DISCOVERERS` / `PC_DISCOVERERS`；`probe_adapters/registry.py` 的 Android / PC 探活注册表。
- `shared_generic_apk` 仅用于未指定厂商 / 游戏的 APK URL，不是第三方发现后备源。
- 蓝色星原目前是 data-only 内测归档，不属于 `DISCOVERERS` / `PC_DISCOVERERS` 自动采集注册表；`backend.admin_probe.candidates()` 对 `vendor=manjuu`、`game_id=azurpromilia` 显式返回空候选，保留清单浏览但避免无适配器探活。

## 服务器部署与数据

| 项目 | 当前值 |
| --- | --- |
| 系统 / Python | Debian 12 / Python 3.11.2 |
| 项目目录 | `/opt/GMI` |
| Python 环境 | `/opt/GMI/.venv` |
| 进程服务 | `gmi-v5.service`，运行中且开机启动 |
| 服务文件 | `/etc/systemd/system/gmi-v5.service` |
| 环境文件 | `/etc/gmi-v5.env`，root 所有，权限 600 |
| 数据目录 | `/opt/GMI/data` |
| 状态目录 | `/opt/GMI/.cache` |
| 监听地址 | `0.0.0.0:8000`，单 worker |
| API 基址 | `http://10.0.0.234:8000/api/v1` |
| CORS 来源 | `https://gmi.yeque.top`、`https://game-manifest-index-v2.pages.dev` |

服务器管理凭据及后台 Token 已由用户提供并用于部署；本文不保存真实值。后台 Token 与 SSH 密码是不同配置，不应互相替代。

现有 systemd 服务的启动命令为：

```sh
/opt/GMI/.venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```

常用只读运维命令：

```sh
systemctl status gmi-v5 --no-pager
journalctl -u gmi-v5 -n 100 --no-pager
curl --fail --max-time 10 http://127.0.0.1:8000/api/v1/health
```

服务器实际依赖：FastAPI 0.136.1、Starlette 1.0.0、Pydantic 2.13.5、Uvicorn 0.53.0、APScheduler 3.11.3。

初次安装按宽松范围选到了 FastAPI 0.141.1 / Starlette 1.6.0，75 项后端测试中的路由清单测试失败；只读分析确认新版出现 `_IncludedRouter` 结构，相关实际接口仍能访问。随后将 FastAPI / Starlette 对齐本机已验证版本，重新检查依赖并运行同一组测试，75 项全部通过。已把已验证依赖快照写到 `/root/gmi-v5-dependencies-verified-20260915.txt`，安装前版本记录在 `/root/gmi-v5-dependencies-before-20260915.txt`。

### 数据快照

用户明确选择同步本机最新 `data/` 和探活计划。已生成并上传的快照：

- 本机文件：`C:\Users\Administrator\AppData\Local\Temp\gmi-v5-data-20260915-1200.tar.gz`。
- SHA-256：`eb7aa55e04e035c92b5fef45c6a560abe38c560fc5add62fec44e3a05263d738`。
- 包含 944 个 data 文件；其中一个是临时锁文件 `data/.cache/.gmi-data.lock`。
- 已逐文件比对：服务器 943 个实际数据文件与快照哈希全部一致，无额外文件；差额仅为未迁移的锁文件。
- 上传时使用的 `/tmp/gmi-v5-data.tar.gz` 后来已不存在，不能假设该路径仍可解压。

上述一致性是迁移快照验收结果，不代表后续本机定时探活产生的新证据会自动同步到服务器。不要再次覆盖已经验收的数据或删除 `.cache/admin`。

### 2026-09-16 调度状态（历史记录）

- 本机 `.cache/admin/schedules.json`：探活启用，每小时、`normal`；本轮读取到后续任务已执行并生成下次时间。
- 服务器计划：`enabled=false`、`interval_hours=1`、`mode=normal`；每日采集为禁用。
- 服务器调度状态：`running=true`、`next_run_at=null`、`error=null`。
- 最近派发记录：`7032c47a61854d34`，开始时间 `2026-09-15T06:02:23Z`，任务状态 `finished`。这证明存在历史派发记录，不代表当前计划启用。
- 服务器计划文件在 14:32 被修改为禁用。后续只读核对发现该状态，已询问用户是否恢复；目前没有明确恢复答复，保持原状。

## 前端与公网访问

- 前端使用 Cloudflare Pages；已知地址为 `https://game-manifest-index-v2.pages.dev` 和 `https://gmi.yeque.top`。
- 构建命令 `npm run build`，输出 `dist`。实际 Pages 项目设置及当前部署分支仍需在发布时核对。
- `acdfbd8` 的提交说明是触发 Pages 生产部署，但空提交或推送成功不等于部署成功。
- 修复发布前曾通过 HTTP 读取线上 JS，确认线上仍有旧版“正常”和混入异常的未知筛选；当时本机 Vite 已提供修复代码。
- 2026-09-16 本轮通过 HTTP 复查两个前端地址均为 200；线上 JS `index-D-xK3XS2.js` 已包含蓝色星原隐藏探活徽章的条件及通用 file-manifest 加载代码。未进行浏览器像素级验收。
- 本机 API 与 Vite 转发已实际验证蓝色星原：游戏、域、版本、artifact 分页、文件目录和搜索接口均返回 200；文件总数 34,758、总大小 77,865,464,813 字节。
- 前端通用 `files` 域已复用 `ChunkFileBrowser` 读取 generic file-manifest；artifact 列表使用页码和每页 50/100/200/500 条选择，不再依赖“加载下一页”。后端 artifact 接口返回筛选后的 `total`。
- 历史 API 地址 `https://api.yeque.top:9000/gmi-v2/api/v1/health` 曾返回 404，不再作为生产基址。
- 当前线上 JS 内的 API 基址为 `https://api.yeque.top:9000/gmi/api/v1`。本轮健康与蓝色星原域能力、artifact、文件清单接口均成功；artifact 总数 645、文件数 34,758、总大小 77,865,464,813 字节。反向代理配置文件本轮未修改。

## 探活“未知”的含义

蓝色星原当前版本的“未判定”只表示没有探活证据；本轮核对 `current_count=0`，并已从候选生成器排除。不要把它解释成 645 个链接已被检查后全部未知。

已核对的 9 月 15 日 11:35 全量任务 `58a303f840d04f74`：检查 2988 条，2176 可用、180 失效、628 未知、4 异常。它是已分析的历史全量任务，不能覆盖后续定时任务统计。

628 条未知由终末地 PC 623 条 HTTP 403、终末地 Android 2 条 HTTP 403、鸣潮 Android 3 条 HTTP 200 但缺少有效文件证据组成。普通拒绝访问、验证页和网络错误不能统一解释为文件失效。

崩坏3 Android 8.3 曾返回 `available=false`，原因 `oss_archive_not_restored`。前端把缺失 HTTP 状态码当作未验证的错误已修复，不需要修改该条数据或来源。

20 小时证据有效期仍保留，但只对仍在定时轮换范围内的可用 URL 标记 `stale`。失效或未判定的旧 URL 保留真实状态且无过期时间；版本与 artifact 汇总使用同一判断。APK 兼容详情仍是独立投影。

## 已实际验证

- 本机状态修复：5 个前端测试文件共 68 项通过，`vue-tsc --noEmit`、构建通过。
- 前台管理入口移除：`src/route-state.test.ts` 13 项通过，本机 Vite 返回已移除入口的代码。
- 发布前：4 个前端测试文件共 48 项通过，`npm run build` 通过，功能范围差异检查通过。
- Debian 服务器：依赖对齐后 `pip check` 通过；`backend.test_probe_scheduler`、`backend.test_scheduled_probe_engine`、`backend.test_admin_sync_operations`、`backend.test_admin_version_admin` 共 75 项通过。
- 部署验收：内网健康及游戏列表 200；正确 Token 管理接口 200，无 Token 401；Pages origin 的 CORS 预检 200。
- 本轮文档复查：内网健康、12 款游戏列表及带正确 Token 的调度接口再次返回 200；systemd 为 active / enabled；远程 Git 引用与上表一致。
- 蓝色星原 catalog / API 验收：本机游戏列表 13 个、域列表 24 个；`/api/v1/games/azurpromilia/domains`、版本列表、文件清单和搜索详情均 200；App Store 图标 URL 实测返回 `200 image/jpeg`。
- 本轮回归：`backend.test_api_contract` 57 项、前端相关 Vitest 83 项、`npm run build` 均通过。蓝色星原探活候选数在本机及服务器均为 0；服务器 `pip check` 通过，服务重启后健康与域能力接口均 200。未进行客户端浏览器像素级验收。
- Windows 隔离计时器真实网络验收属于 9 月 14 日历史证据：自动派发一条原神 Android 官方链接，HTTP 206，写入副本且原记录哈希未变。

本轮实际运行了后端 API / 探活候选回归、前端 Vitest 和 production build；未进行客户端浏览器像素级验收。

## 剩余事项与工作约束

1. 服务器现有定时计划为已启用、每 12 小时、`normal`；本轮部署保持原配置。蓝色星原仍被候选排除。
2. 公网 API、线上前端构建 API 基址和本次蓝色星原更新已完成 HTTP 验收；浏览器像素级验收仍未进行。
3. 当前 CI 使用宽松依赖安装，本会话未读取 GitHub Actions 运行结果；不能宣称三平台全绿。若处理兼容性，应在独立任务中固定或升级依赖并验证。
4. 每日采集外部调度、retention、多 worker / 多实例协调仍未实现；macOS 实际运行尚未核实。
5. 乱码修复仅限指定 Chunk 标题的展示层；历史 JSON 与采集编码源头未全面修复。
6. 文档的新项目名称不授权重命名既有目录、服务、环境变量、分支或交接文件。
7. 保护本机未提交数据与服务器实际配置；未知外部变更先核对，不能套用旧 PID、旧快照路径或历史结论。
8. 禁止客户端集成浏览器、桌面控制、Chrome CDP 和用户浏览器会话。允许 HTTP / API、命令行及符合项目要求的独立 headless 工具。
9. 本轮功能代码已提交、推送并部署；交接文档随后提交并推送。`AGENTS.md`、`BRANCHING.md` 未修改。工作区中此前未提交的其他游戏数据、README 和新增条目仍保留，后续操作前必须重新核对范围。

早前本机后台启动曾在进程创建前被执行层返回 `blocked by policy`，根因未确认，之后用户手动启动成功。它不代表应用启动失败，也不应再作为服务器部署未完成的依据。

## 2026-09-16 蓝色星原 Android APK 发布补充

- 新增 `data/manjuu/azurpromilia/android/0.3.0.2634121.json` 和 `index.json`，域为 `azurpromilia-android`。APK 文件大小为 `1,384,742,820` 字节，CRC64 为 `18123626472714408145`，来源为用户提供的 Manjuu 官方直链；未解析 APK 内部 version code，记录保持 `null`。
- 前端 `src/views/ArchiveView.vue` 对蓝色星原的 PC 与 Android 域统一使用 metadata-only 展示：隐藏“未验证”徽章、可用性筛选和锁定下载状态，保留官方直链复制与下载。未新增适配器，未写入探活证据。
- 发布提交：任务分支 `9bd9647`；`integration/v5` squash 提交 `fd4dcd6`；`main` 正常合并提交 `2714bb1`。两条远程分支均已推送到 GitHub。
- 服务器 `/opt/GMI` 已快进到 `2714bb1` 并重启 `gmi-v5.service`。验收结果：服务 `active` / `enabled`，`GET /api/v1/health` 返回 200，蓝色星原域列表和 `azurpromilia-android` 版本接口返回 200。
- 公网 API 的健康、Android 版本列表和版本详情均返回 200。`https://gmi.yeque.top` 用常规 HTTP User-Agent 请求返回 200，线上 JS `index-CyxHGaab.js` 已包含蓝色星原统一隐藏可用性展示的条件；Python 默认 User-Agent 曾返回 403，未将其误判为应用故障。
- 本次实际验证：`src/azurpromilia-catalog.test.ts` 与 `src/archive-navigation.test.ts` 共 22 项通过，`npm run build` 通过。未进行客户端浏览器像素级验收。
- 本机和服务器仍保留此前未提交的数据变更；服务器探活计划仍为 `enabled=false`，本次部署没有启用或修改计划。

## 2026-09-24 定时探活可用 URL 轮换修复

- `backend/admin_operations.py` / `backend/admin_probe.py`：定时任务只处理官方或历史来源中当前可用的 URL；新发现 URL 允许首次探活，已确认失效或未知的 URL 不再被后续自动轮次反复检查；`normal` 仍按 20 小时证据有效期轮换，`full` 仅用于显式全量轮次。
- `backend/api_contract.py`：公共版本、artifact 和 URL 投影使用同一轮换资格判断。旧的 `unavailable` / `unknown` 状态不再被错误转换成证据过期；只有仍在定时轮换范围内的可用 URL 才会产生 `stale` / `expires_at`。
- `backend/version_store.py` 及 Android / PC 官方发现适配器：发现写回按 artifact、来源和 URL 保留已有探活 `current`，即使发现器返回同一 URL 的新状态，也不会重新激活已确认失效的链接。
- 蓝色星原 PC / Android 仍未注册定时探活，候选生成器对两端返回 0。
- 本地真实调度任务 `2049512056b84f76`：发现 20/20 成功；探活只检查 1 条新发现且无旧证据的原神 PC 3.7.0 patch URL，结果 HTTP 206；已有可用证据和旧失效 URL 均未重复检查。旧明日方舟 Android 1.1.50 的 403 URL 仍投影为 `unavailable`、`evidence_status=verified`、`expires_at=null`。
- 本地调度计划已恢复为 `enabled=false`、`interval_hours=24`、`mode=normal`。本轮相关后端测试 86 项、Android / PC 适配测试 43 项、前端相关 Vitest 5 项及生产构建通过。完整 API 合约测试 58 项中 56 项通过，2 项基线断言仍预期 24 个域和蓝色星原 `windows`，而当前数据为 25 个域、`multi`；与本轮改动无关。
- 发布提交：功能提交 `c363cdf`、`integration/v5` tip `d65078b`、`main` tip `3abae81` 均已推送 GitHub。服务器 `/opt/GMI` 已更新到 `3abae81`，功能发布时已重启 `gmi-v5.service`；服务 `active` / `enabled`，内网健康接口 200。旧明日方舟 Android 1.1.50 失效 URL 在服务器 API 中仍为 `unavailable`、`evidence_status=verified`、`expires_at=null`。
- 服务器保留原有 `enabled=true`、12 小时、`normal` 计划与现存数据；本次未同步或提交本机、服务器未提交的 `data/` 记录。`main` 不跟踪内部交接文档，本文保留在 `integration/v5`。
