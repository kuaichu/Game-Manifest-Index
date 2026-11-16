# Game Manifest Index 交接文档

更新日期：2026-11-16（Asia/Shanghai）。

本文件只记录接手需要的**当前状态**：入口、部署、分支基线、发布方式、行为要点和遗留问题。工作规则见 [AGENTS.md](AGENTS.md)，分支与晋级规则见 [BRANCHING.md](BRANCHING.md)，PHASE 1–10 的重建与验收过程见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。文中带日期的数字都是当次核对的快照，线上数据会持续增长。

## 1. 项目概览

Game Manifest Index 从游戏厂商官方渠道采集 Android APK 与 PC 资源（完整包、补丁、语音、文件清单、Sophon Chunk），整理为 schema v2 版本记录，通过 FastAPI 提供给 Vue 3 + TypeScript + Vite 前端。本站不持久托管安装包；文件下载按需由后端流式代理官方内容。

| 项目 | 位置 |
| --- | --- |
| 本机仓库 | `D:\Project\Active\Game Manifest Index` |
| GitHub | <https://github.com/kuaichu/Game-Manifest-Index>（只发布 `main`） |
| 前台 | <https://gmi.yeque.top>；管理页 `/admin`，前台不提供入口 |
| 独立前端副本 | `D:\Project\Active\Game Manifest Index-src`（见第 3 节） |

覆盖范围：公开 14 款游戏。官方自动采集注册 Android 12 款、PC 10 款，以 `url_adapters/service.py` 为准；探活能力以 `probe_adapters/registry.py` 和具体 URL 类型为准。归档游戏数不等于自动化覆盖数：蓝色星原 Android / PC、因缘精灵 CBT2 是内测归档，没有采集或探活适配器属于预期。

## 2. 线上部署

### 访问链路

```text
浏览器 → gmi.yeque.top
       → 47.117.21.253（openresty + Anubis 防机器人验证，用户自管）
       → 内网 10.0.0.213:8080  gmi-web（自托管 Nginx 静态前端）
            └ /api/ → 127.0.0.1:8000  gmi-v5（FastAPI 后端）
```

- 浏览器只访问同源 `https://gmi.yeque.top/api/v1`，不需要 CORS。内网可直连后端 `http://10.0.0.213:8000/api/v1` 和前端 `http://10.0.0.213:8080/`。
- curl 等工具访问 `gmi.yeque.top` 会先拿到 Anubis 验证页，核对线上前端时优先请求内网 8080。
- **已停用**：Cloudflare Pages（`game-manifest-index-v2.pages.dev`）和 9000 端口公网 API（`api.yeque.top:9000/gmi/api/v1`）。推送 `main` 不再更新线上前端。旧服务器 `10.0.0.234` 也已停用。

### 服务器 `10.0.0.213`

Debian 13。同机还运行 model-gallery、github-star-show、cpa-quota-viewer、doudian 等其他服务，GMI 只操作下表中的路径和服务。SSH 用 root 密码登录，密码在使用时由用户提供，不写入仓库、脚本或日志；主机指纹已在本机 `~/.ssh/known_hosts`。

| 路径 / 服务 | 内容 | 部署时 |
| --- | --- | --- |
| `/opt/GMI/backend/`、`probe_adapters/`、`url_adapters/` | 后端运行代码（不含测试），含 `backend/requirements.txt`、`url_adapters/endpoints.json` | 用 `main` 的内容整体替换 |
| `/opt/GMI/data/` | **正式游戏数据** | 绝不覆盖、清理或用本地数据替换 |
| `/opt/GMI/.cache/` | 管理计划、调度与任务状态、缓存 | 不动 |
| `/opt/GMI/.venv/` | Python 3.13.5，FastAPI 0.136.1 / Starlette 1.0.0 / uvicorn 0.53.0（11-01 核对） | 仅在 requirements 变化时安装 |
| `gmi-v5.service` | `/opt/GMI/.venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1`；环境文件 `/etc/gmi-v5.env`（600） | 后端代码变化时 restart |
| `/opt/gmi-web/` + `gmi-web.service` | 前端静态产物、Nginx 二进制与配置，端口 8080 | 见 `deploy/frontend/README.md` |

`/opt/GMI` 只放运行文件：没有 Git，也不放前端源码、构建配置、`scripts/`、文档或测试。服务器不保存代码备份，代码以 GitHub 和本机仓库为准。

### 数据权威

`/opt/GMI/data` 是唯一的正式数据。本地 `data/` 只是参考；同一数据有差异时一律以服务器为准，即使本地时间戳更晚。只有服务器缺失的本地独有数据可以增量补充，补充前先按现有身份确认缺失，并保留服务器已有内容、artifact 身份和来源。完整规则见 AGENTS.md 的 Server Data Authority。代码部署不等于数据同步。

### 调度

- 内置定时任务每小时启动一次 `normal` 轮次：先做官方发现（Android + PC），再探活新发现的 URL 或上次可用的 URL。`normal` 会跳过 20 小时内的有效证据，`full` 忽略新鲜度。所以"每小时启动"不等于"每小时重测全部链接"。
- 配置 TG 后，只在发现新版本时通知，没有更新时保持静默。Bot Token 在 `/etc/gmi-v5.env` 中。
- 独立的每日采集计划只保存配置（10-17 快照为启用，`08:00`、`13:23`）。外部触发方式、时区和漏跑行为都是 `UNKNOWN`。

### 最近一次线上核对（2026-11-16，只做了 HTTP 检查，未 SSH）

- 内网和同源健康检查均为 `status=ok`；公开游戏 14 款。
- 定时探活 running / enabled / 每小时 normal / 无错误。
- 最近活动：11-12 异环 PC `1.5.6`，11-11 鸣潮 Android `3.8.0`，11-10 星铁 `4.7.0` 与幻塔 PC `6.5.3`。
- `10.0.0.213:8080` 和 `gmi.yeque.top` 返回的主脚本都是 `index-D7QmMR1d.js`，与本机从 `main@199f759` 按 selfhost 模式构建的结果同名。
- 未核对：服务器后端文件哈希（最后一次是 11-01 核对，等于 `main@3e8d11a` 的运行部分）、`gmi-web` 服务状态与 Nginx 配置、服务日志。

## 3. 代码与分支基线

| 分支 | 提交 | 说明 |
| --- | --- | --- |
| `main` / `origin/main` | `199f759` | 公开发布线，不含内部文档 |
| `integration/v5` | 见 `git log` | 开发基线，含内部文档；功能代码与 `main` 一致 |
| `integration/apk` | `dffdc62` | 没有独有提交，落后于 V5，平台任务开始前按 BRANCHING.md 同步 |
| `integration/pc` | `a159eeb` | 同上 |

- **未合入**：`backend/telegram-archive-details`，内容是 TG 通知附带各游戏归档详情。属于后端改动，发布时要重启 gmi-v5。
- **已 squash、分支未删除**（删除需另行授权）：`frontend-self-host`、`frontend-activity-timezone`、`frontend/activity-timeline-and-control-strip`、`backend/handoff-server-213`、`codex/readme-showcase`。
- 部分分支挂在 `C:/Users/Administrator/.codex/worktrees/` 下的 worktree 里；`pc/wuwa-resource-packs` 停在 `integration/pc`，没有新提交。另有 2 个 9 月的旧 stash。
- 本地 integration 分支的 upstream 显示 `gone`，这是预期情况，不需要重建远端分支。
- 历史分支备份：`C:/Users/Administrator/.codex/backups/gmi-branches/20261002-710f2140fe7f43bf884c496ae7cdeaa0/before-cleanup.bundle`、`.cache/unified-backend-fixes/completed-task-branches.bundle`、`.cache/probe-rewrite-completed-tasks.bundle`。只用于查阅，不整支合回。

### 独立前端副本 `Game Manifest Index-src`

- 独立的本地 Git 仓库，只有 `main`，没有远端，由其他 AI 持续开发。
- 两边以文件为单位双向同步：
  - 副本的改动，带入主项目的任务分支，验证后 squash 到 `integration/v5`；
  - 主项目的前端改动，同步回副本，开分支验证后 `--no-ff` 合并到副本 `main`。
  - 不要整目录覆盖：以前整目录覆盖曾丢失 AdminView 中的 `artifact_id`。
- 两边有意保留不同的配置：副本的 `vite.config.ts` 带代理变量和轮询监听，`tsconfig.json` 带 noUnused 检查。副本 `.env.development.local` 代理到 `http://10.0.0.213:8000`。
- 最近同步点：副本 `main@bab3e62` 对应主项目 `fb5ba15`。
- 副本当前有**未提交**的同步分支 `sync/provenance-from-original`，内容是主项目 11-02 的来源说明修正和 11-16 的北京时间显示。合并后，`src/` 与主项目完全一致；408 项测试、vue-tsc 和构建均通过。待提交并合并到副本 `main`，同时更新副本 README 里的同步点。

## 4. 发布流程

### Git 流程

任务分支（从对应 integration 分支创建）→ 验证 → squash 到 `integration/v5` → 普通合并到 `main` → 推送 `origin/main`。用户已长期授权：`integration/v5` 合并到 `main` 后直接推送。

- 内部文档（`AGENTS.md`、`BRANCHING.md`、`PROJECT_STATUS.md`、本文件）一律不进入 `main`。纯文档改动只 squash 到 `integration/v5`。
- 推送 `main` 只更新 GitHub，前端和后端都需要另外部署。

### 前端发布

1. 从 `main` 执行 `npm ci`、`npm run build:selfhost`，产物输出到 `.cache/selfhost/dist/`，使用 `.env.selfhost` 中的同源 `/api/v1`。
2. 按 `deploy/frontend/README.md` 上传到 `/opt/gmi-web/site/`：先传 assets，再传 HTML，确认新入口健康后再清理旧文件。Nginx 配置有变化时，先校验再 `systemctl reload gmi-web`。纯静态更新不需要重启 gmi-v5。
3. 验证：`http://10.0.0.213:8080/` 首页引用的 `index-*.js` 与本机构建同名，或包含本次新代码。

`npm run build` 读取 `.env.production` 中已停用的 9000 地址，**产物不能用于部署**。

### 后端发布

1. 本机 `git archive main backend probe_adapters url_adapters`，去掉 `test_*.py` / `conftest.py`。
2. 只读记录指纹：服务 active、健康状态、data 文件数与摘要、`.cache` 摘要、`/etc/gmi-v5.env` 与 service 文件哈希、MainPID。
3. 上传到 `/tmp` 临时目录，整体替换三个代码目录（上游已删除的文件随之消失）。
4. 用 `/opt/GMI/.venv/bin/python` 导入全部非测试模块；`backend.app` 只编译不导入。
5. 代码有变化时 `systemctl restart gmi-v5`，确认健康、游戏列表和调度状态，并查看 `journalctl -u gmi-v5`。
6. 再次核对第 2 步的指纹，确认数据、状态和环境未变；删除服务器和本机的临时文件。

如需在服务器环境跑后端测试，把代码和测试一起上传到 `/tmp` 的独立目录，用正式 `.venv` 运行，测完删除，不要在 `/opt/GMI` 中运行。

服务器只读检查：

```sh
systemctl status gmi-v5 gmi-web --no-pager
/opt/GMI/.venv/bin/python -m pip check
curl --fail --max-time 10 http://127.0.0.1:8000/api/v1/health
curl --fail --max-time 10 http://127.0.0.1:8000/api/v1/probe/schedule-status
curl --fail --max-time 10 http://127.0.0.1:8080/api/v1/health
```

管理计划和调度运行状态分别读取 `/api/v1/admin/probe/schedule`、`/api/v1/admin/probe/scheduler`，需要 Bearer Token。

## 5. 本机开发与验证

环境要求：Python 3.12，Node.js 20.19+ 或 22.12+。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt "fastapi==0.136.1" "starlette==1.0.0"
npm ci
```

后端（另开终端）：

```powershell
$env:GMI_ADMIN_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host '管理 Token' -AsSecureString)).Password
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

前端：

```powershell
$env:VITE_API_BASE_URL = '/api/v1'
npm run dev -- --port 5173 --strictPort
```

Vite 把 `/api` 转发到本机 8000。同一份数据和状态目录只运行一个后端实例 / worker；后台写操作的验证使用独立的数据副本和状态目录。

不带管理权限的本机预览可以使用参考数据副本（可能落后于服务器）：先把 `GMI_DATA_ROOT` 设为 `.cache/local-server/runtime-data`、`GMI_STATE_ROOT` 设为 `.cache/frontend-handoff-backend/state`，把 `GMI_ADMIN_TOKEN`、`GMI_TELEGRAM_BOT_TOKEN`、`GMI_TELEGRAM_CHAT_ID` 设为空，再用 `.cache/local-server/venv/Scripts/python.exe` 启动 uvicorn。连接线上后端调试前端时，用独立副本的 dev server（代理到 213）。

| 环境变量 | 含义 |
| --- | --- |
| `GMI_ADMIN_TOKEN` | 管理 Bearer Token；未配置时管理接口返回 503 |
| `GMI_DATA_ROOT`、`GMI_STATE_ROOT` | 数据和状态目录，默认是项目下的 `data/`、`.cache/` |
| `GMI_CORS_ORIGINS` | 允许的前端 origin，逗号分隔 |
| `GMI_TELEGRAM_BOT_TOKEN`、`GMI_TELEGRAM_CHAT_ID` | 新版本 TG 通知，由环境提供 |
| `VITE_API_BASE_URL` | 前端 API 基址，构建时确定；正式发布使用 `.env.selfhost` |

验证按改动选择相关检查，不默认跑全量。示例：

```powershell
.\.venv\Scripts\python.exe -m unittest backend.test_api_contract.TemporaryContractTests backend.test_api_contract.HttpUpstreamTests
npm test -- src/selected-file-download.test.ts src/chunk-file-browser.test.ts
```

固定迁移基线、历史计数和来源白名单测试只用于历史快照审计，不能拿来判断持续更新的线上数据。10-02 全量核对时有 4 项已知失败：管理页旧文案、FastAPI 新版的路由枚举、NTE 固定白名单、要求内测归档也必须有适配器。它们不代表线上故障。

## 6. 代码入口与行为要点

| 入口 | 职责 |
| --- | --- |
| `backend/app.py`、`backend/api_contract.py` | 应用启动、公共 API 与数据投影 |
| `backend/admin_routes.py`、`backend/admin_operations.py` | Token 鉴权、采集及探活管理任务 |
| `backend/version_store.py`、`backend/storage_locks.py`、`backend/indexes.py` | 记录与索引的事务提交、共享数据锁、索引构建 |
| `backend/admin_probe.py`、`probe_adapters/service.py` | 探活目标身份核对、只生成 `current` 的状态转换、统一写回 |
| `backend/admin_state.py`、`backend/probe_scheduler.py` | 管理计划与任务状态；内置定时发现 + 探活 |
| `backend/telegram_notify.py`、`backend/activity_store.py` | 新版本 TG 通知；版本更新与链接全部失效的活动记录 |
| `backend/manifest_readers.py`、`src/chunk-download.ts`、`src/chunk-directory-download.ts` | 官方清单解析、Chunk 校验合成与目录写入 |
| `src/components/ChunkFileBrowser.vue`、`src/selected-file-download.ts` | 文件勾选、直链流式保存、Chunk 合成、复制与导出 |
| `url_adapters/service.py`、`probe_adapters/registry.py` | 官方采集与探活注册表 |
| `src/views/ArchiveView.vue`、`src/views/AdminView.vue` | 前台归档页与管理页 |
| `src/site-changelog.ts` | 公开更新日志（最新条目为 2026-11-01） |
| `deploy/frontend/` | 自托管前端的 Nginx 配置、systemd 服务与部署说明 |

### 存储与探活不变量

- `version_store.record_index_transaction()` 在共享进程锁和文件锁内同时提交一条记录及其所属域的索引，运行异常时回滚两份文件；不保证断电或强杀进程时的一致性。`persist_v2_record()` 是完整发布接口；`write_v2_record()` 只写记录，只能在事务内使用。
- 探活提交链：`admin_probe._run_probe` → `current_fn(identity, target_url, result)` → `_commit_probe`。网络请求在事务外执行；提交时重新读取最新记录，核对身份、来源和候选元数据后，只替换目标 `artifacts[].urls[].current`。旧的 `apply_fn` / `apply_*_result()` 已删除，不要恢复。
- 管理编辑按 `artifact_id` 匹配资源，不依赖数组位置；目录配置的读改写和版本 CRUD 都有数据锁保护。
- 后台任务启动失败会释放执行槽：忙碌返回 409，启动失败返回 503。

### 采集与来源

- 默认发现只用官方接口。第三方来源只用于明确的历史导入，并保留真实来源（见 AGENTS.md）。
- 明日方舟和终末地 PC 共用鹰角完整包适配器（`batch_proxy` 的 `get_latest_game`）。终末地下载链接投影为官方 OSS `beyond-prod.oss-cn-shanghai.aliyuncs.com`。只注册了完整包采集，运行时资源入口已在前台隐藏，历史数据保留。
- 异环 PC 从 `publish_PC/config.xml` 的 `ResConfig` 跟随 `PC_<数字>` 资源分支。遇到坏配置、循环或超过 4 层时明确失败，不回退旧版本。
- HTTP 403 统一显示为"不可用"。官方 OSS 的 `HEAD 200` 只能证明元数据可读；归档冻结的对象 GET 仍可能返回 `403 InvalidObjectState`。
- 因缘精灵 CBT2 `0.60.2` 有文件清单，但没有下载 URL 候选。

### 下载与文件清单

- `file-content` 只接受记录内的文件身份和路径，由官方清单解析下载目标；受域名、路径、重定向、大小和超时限制，不接收用户指定的 URL。
- Chunk 合成：桌面 Chrome / Edge 可以逐块校验并流式写盘；其他浏览器走 Blob 合成，上限 64 MiB。后端单块代理的压缩体积上限为 64 MiB。不支持加密或未知压缩格式。
- 目录下载和多选下载需要安全上下文和 `showDirectoryPicker`（桌面 Chrome / Edge）。下载时在所选目录下新建子目录，不覆盖已有文件，支持进度和取消，但不支持断点续传。
- 文件清单每页 100 条，翻页时保留跨页勾选；切换版本、来源、组件或搜索条件时清空勾选。
- Sophon 清单使用实例内存缓存（最多 8 项、合计 64 MiB），不持久化。

### 展示

- 页面时间统一显示为北京时间。页脚分别显示定时任务最近启动时间、下次计划时间和链接最近实际检测时间。
- 文件列表标题显示官方清单或资源包的最后修改时间。日期缺失或冲突时隐藏，不借用采集时间。分卷时间都可靠时取最晚的分卷时间。
- 公开更新日志只写普通用户能感知的变化；管理员功能和内部流程不写进去。

## 7. 已知问题与未验证项

- 每日采集的外部触发、时区、漏跑补偿仍为 `UNKNOWN`。retention、多 worker / 多实例协调未实现。
- 后端进程自 10-22 起没有重启过（11-01 核对），精简后的 `/opt/GMI` 还没经历过冷启动。下次重启时注意查看 `journalctl -u gmi-v5`。
- 服务器后端代码自 11-01 起没有再按文件哈希核对过；`gmi-web` 的服务状态、Nginx 配置和外层反代都没有核对过。
- 已提交的 `.env.production` 仍是 9000 地址，`npm run build` 的产物会指向已停用的 API。是改成同源 `/api/v1` 还是移除这个文件，尚未决定。
- 线上视觉、真实管理写入和大文件 / 整游戏下载没有重新验收；HTTP 和脚本比对不能代替浏览器验收。
- 部分历史下载已失效，需要官方恢复，例如终末地 PC `0.5.27`（OSS 冻结）、原神 5.5.0 的部分分卷（404）、崩坏3 Android 7.6–7.9 APK。
- 鸣潮 `3.5.0` 等缺少可靠官方时间的历史版本不显示日期。历史 JSON 和采集编码的乱码问题没有从源头修复。
- 任务结束时快照保存失败，会把已完成的操作归为失败。多次并发探活同一候选时，后完成的结果会覆盖先完成的；未实现按开始时间淘汰旧结果。
- 本机 Git / HTTPS 曾出现证书和 TLS 错误；11-16 推送正常。不要修改系统证书或凭证存储来绕过。

## 8. 历史时间线

只列交付和部署节点；PHASE 1–10 的重建与验收见 PROJECT_STATUS.md。

| 日期 | 提交 / 操作 | 内容 |
| --- | --- | --- |
| 2026-10-01 | 数据补录 | 异环 PC 新增 8 个版本，原记录未覆盖 |
| 2026-10-03 | main `c1b153d` | 多选文件下载（直链流式保存与 Chunk 合成）；终末地历史 PC OSS 链接修复 |
| 2026-10-04 | 数据补录 | 终末地 PC `0.5.27` 导入 8 个历史分卷，下载仍不可用 |
| 2026-10-10 | `e3ee888` | 数据动态按日期分组；修复多个弹窗的背景滚动 |
| 2026-10-11 | `474b1b2` | HTTP 403 统一显示为不可用 |
| 2026-10-13 | main `2301f35` | 归档读取、清单缓存与下载内存优化；清单分页与跨页勾选 |
| 2026-10-17 | main `de4bd1e` → `cd99c54` | 高清官方图标；数据锁与管理编辑修复；记录 / 索引统一事务；探活写回重写为只生成 `current` |
| 2026-10-22 | main `dd0156e`、`2597c3c` | 合入独立前端管理台重构；公开更新日志精简；后端修复上线 |
| 2026-10-22～25 | 服务器迁移 | gmi-v5 迁到 `10.0.0.213`，旧服务器 `10.0.0.234` 停用 |
| 2026-11-01 | main `3e8d11a` | 紧凑活动时间线、双平台版本号写法差异修复、控制栏布局、通俗的对比说明 |
| 2026-11-01 | 服务器清理 | `/opt/GMI` 删除 Git 和开发文件，只保留运行文件；数据未变，未重启 |
| 2026-11-02 | main `142d597`、`d021b97` | 来源说明与校验说明改为准确表述，来源说明补充两款内测归档 |
| 2026-11-07 | main `54662cb` | README 展示截图 |
| 2026-11 中旬 | 部署变更 | Pages 与 9000 API 停用，改为自托管前端经公网服务器转发（具体日期未记录） |
| 2026-11-16 | V5 `f79f602`、`1c02acd`；main `199f759` | 合入已上线的北京时间显示与自托管前端配置 |
