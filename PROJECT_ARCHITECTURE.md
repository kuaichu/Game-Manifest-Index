# Game Manifest Index (GMI V5) 项目架构说明

> 本文基于当前仓库代码整理（前后端、数据模型、采集/探活适配器、运行状态与部署拓扑），所有模块路径、符号名称与接口均对应仓库现状。

---

## 1. 系统定位与总体分层

**Game Manifest Index (GMI V5)** 是一个面向二次元游戏客户端历史版本与官方分发包清单的索引、探活、浏览与下载系统，覆盖 Android APK 与 Windows/PC 安装包、增量补丁、Chunk 清单及文件清单（支持 `mihoyo`、`hypergryph`、`kuro`、`perfectworld`、`manjuu` 等厂商，核心公开目录含 13 款主支持游戏及独立配置的非默认数据域/测试目录）。

系统总体分为 5 个核心层次：

```text
+-------------------------------------------------------------------+
| 展示与路由层 (Vue 3 + TypeScript + Vite SPA: src/)                |
|  - 前台归档/版本对比/Chunk 浏览器: ArchiveView.vue                |
|  - 受保护后台控制台(懒加载): AdminView.vue                        |
+-------------------------------------------------------------------+
                               |
                        /api/v1 (HTTP / JSON)
                   (自部署由 Nginx 同源反代至 8000)
                               |
+-------------------------------------------------------------------+
| Web API 与安全边界层 (FastAPI ASGI: backend/app.py)               |
|  - 公开只读契约: backend/api_contract.py (658 行)                 |
|  - 管理员鉴权与运维接口: backend/admin_routes.py                  |
+-------------------------------------------------------------------+
          |                              |
          v                              v
+--------------------------+   +------------------------------------+
| 异步运维与调度引擎       |   | 领域模型、存储锁与索引投影层       |
| - admin_operations.py    |   | - schema_v2.py / legacy_record_*   |
| - probe_scheduler.py     |   | - version_store.py / indexes.py    |
| - admin_probe.py         |   | - storage_locks.py / fs_safety.py  |
| - probe_policy.py        |   | - catalog_registry / inventory_*   |
| - telegram_notify.py     |   | - public_projection / manifest_*   |
|                          |   | - version_admin / admin_catalog_*  |
+--------------------------+   +------------------------------------+
          |                              |
          v                              |
+--------------------------+             |
| 厂商采集与探活插件层     |             |
| - url_adapters/ (官方发现)|             |
| - probe_adapters/(链接验活|            |
+--------------------------+             |
                                         v
+-------------------------------------------------------------------+
| 文件与轻量数据库持久化层                                          |
| - GMI_DATA_ROOT  (data/): Schema v2 JSON、index.json、manifests   |
| - GMI_STATE_ROOT (.cache/): 调度/任务 JSON 状态与 activity.sqlite3 |
+-------------------------------------------------------------------+
```

---

## 2. 权威数据、Schema v2 与磁盘存储结构

### 2.1 数据根目录（`GMI_DATA_ROOT`，默认 `data/`）

仓库以文件系统作为 Canonical 真相源，不依赖重型关系型数据库存放版本主数据：

```text
data/
├── catalog.admin.json                  # 后台可管理的自定义游戏/数据域目录配置
├── .cache/.gmi-data.lock               # 跨线程/跨进程数据写互斥文件锁
└── <vendor>/<game_id>/
    ├── android/
    │   ├── index.json                  # 当前数据域版本摘要索引
    │   └── <version>.json              # Schema v2 单版本规范记录
    └── pc/
        ├── index.json                  # 默认 PC 数据域 (<game_id>-pc) 索引
        ├── <version>.json              # 默认 PC 数据域单版本规范记录
        ├── manifests/ 或 chunk-manifests/  # 随版本保存的离线文件/Chunk 清单
        └── domains/<domain_id>/        # 已注册的非默认次级 PC 数据域（如 endfield-resources）
            ├── index.json
            └── <version>.json
```

- **Schema v2 规范（[schema_v2.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/schema_v2.py) — 690 行，旧格式规范化独立于 [legacy_record_normalizer.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/legacy_record_normalizer.py) — 485 行）**：
  - 记录级身份字段（`RECORD_IDENTITY_FIELDS`）：`("vendor", "game_id", "domain_id", "platform", "channel", "version")`。
  - 资源级身份 `artifact_id`（`a1_<32hex>`）：通过 `artifact_id()` / `artifact_identity_key()` 从记录身份与资源稳定属性推导，**不依赖**数组顺序、URL、大小、校验值或 `kind`/`package_type`/`delivery_mode`。
  - 允许 `kind`：`apk` / `package` / `patch` / `resource`；`component`：`game` / `voice` / `launcher` / `other` / `resource`；`urls[].current` 记录最近探活状态（`available` / `unavailable` / `unknown`、`http_code`、`checked_at` 等）。
  - `provenance.source_kind` 严格区分官方同步（`official_sync`）、历史回填（`third_party_history`）、迁移（`legacy_migration`）与手工录入（`manual`）。
- **并发事务与安全写入（[storage_locks.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/storage_locks.py)、[fs_safety.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/fs_safety.py)、[version_store.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/version_store.py)、[indexes.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/indexes.py)）**：
  - 所有写入通过可重入线程锁 `DATA_LOCK` + 跨进程 OS 文件锁 `data_file_lock`（Windows `msvcrt.locking` / POSIX `fcntl.flock`）串行化。
  - 由 [fs_safety.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/fs_safety.py) 统一校验路径组件合法性、拦截符号链接与 Windows `0x400` 重解析点并执行 `mkstemp` + `fsync` + `os.replace` 原子写入；在单次事务（`record_index_transaction` / `write_v2_record`）中原子写入版本 JSON 并同步更新对应 `index.json`。
- **次级 PC 数据域白名单（[domain_registry.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/domain_registry.py)）**：
  - 显式注册非默认 PC 域（例如 `("hypergryph", "endfield") -> ("endfield-resources",)`），也支持通过 [catalog_admin.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/catalog_admin.py) 从 `catalog.admin.json` 读取自定义域。

### 2.2 运行态目录（`GMI_STATE_ROOT`，默认 `.cache/`）

由 [admin_state.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/admin_state.py) 与 [activity_store.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/activity_store.py) 管理：
- `.cache/admin/schedules.json`：采集计划时间参数与内置探活调度参数（`enabled`、`interval_hours`、`mode`）。
- `.cache/admin/probe_scheduler.json`：内置探活调度器运行期限与上次任务游标（`next_run_at`、`last_started_at`、`last_job_id`）。
- `.cache/admin/latest_operation.json`：最近一次运维任务快照，支持页面刷新或服务重启后的状态追踪。
- `.cache/activity.sqlite3`：轻量 SQLite 追加日志表 `activity_events`，记录公开可见的版本更新（`version_update`）与链接失效（`version_unavailable`）事件。

---

## 3. 后端架构（`backend/`）

### 3.1 应用装配与生命周期（[app.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/app.py)）

`create_app(...)` 为 FastAPI 工厂函数（支持测试注入 `data_root`、`state_root`、`admin_token`、`upstream`、`discovery`、`probe_fn`、`clock`、`scheduler_timer`）：
1. 挂载 `create_api_app()` 生成的公开只读 API 及 `app.state.contract`（`ApiContract`）。
2. 按环境变量 `GMI_CORS_ORIGINS` 可选配置 CORS。
3. 挂载 `create_admin_router()` 生成的 `/api/v1/admin/*` 路由，并初始化 `OperationManager` 与 `AdminStateStore`。
4. 初始化 `ProbeScheduler`（仅当 `GMI_ADMIN_TOKEN` 非空且不含空白字符时 `authorized=True`），并在 ASGI `lifespan` 中启动定时轮询，退出时优雅停止调度器并等待运维线程收尾（最长 30 秒）。
5. 额外暴露公开只读接口 `GET /api/v1/probe/schedule-status`，脱敏返回内置探活调度状态与证据有效期（`evidence_ttl_hours`）。

### 3.2 公开只读 API 契约与库存投影层

公开只读契约按职责拆分为 5 个正交模块，在磁盘边界校验 Schema v2 记录并投影为公开 JSON，不泄露本地路径、内部字段与源码采集配方：
- **[catalog_registry.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/catalog_registry.py)**（87 行）：厂商、公开游戏目录与本地官方 CDN 主机白名单单一真相源。
- **[inventory_loader.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/inventory_loader.py)**（479 行）：规范版本记录与 `index.json` 校验加载器，提供 `DATA_LOCK` 保护下的 `lstat` 快照指纹缓存（`snapshot_data_root`）。
- **[public_projection.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/public_projection.py)**（615 行）+ **[probe_policy.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/probe_policy.py)**（50 行）：20 小时探活证据保鲜判定、URL/血缘脱敏及游戏/数据域/版本/资源公开字段投影。
- **[manifest_projection.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/manifest_projection.py)**（583 行）：库洛画质包（`resource-packs.json`）、文件清单元数据、Sophon Chunk 文档及版本对比投影。
- **[api_contract.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/api_contract.py)**（658 行）：`ApiContract` 协调器与公开 HTTP 路由挂载：

| 路由 | 职责 |
| --- | --- |
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/probe/latest` | 全局最近一次有效实测探活时间戳 |
| `GET /api/v1/activity`, `GET /api/v1/games/{game_id}/activity` | 全站 / 单游戏动态事件流（结合 `ActivityStore` 与可见性过滤） |
| `GET /api/v1/games`, `GET /api/v1/games/{game_id}/domains` | 公开启用的游戏目录与下属数据域列表 |
| `GET /api/v1/domains/{domain_id}/versions` | 数据域版本列表及可用性聚合统计 |
| `GET /api/v1/domains/{domain_id}/versions/{version}` | 单版本公开详情与 artifact 投影 |
| `GET /api/v1/domains/{domain_id}/versions/{version}/artifacts` | 按类型/可用性/分页条件筛选 artifacts |
| `GET /api/v1/domains/{domain_id}/compare` | 双版本对比（支持 `artifacts` 与 `files` 两种范围） |
| `GET /api/v1/domains/{domain_id}/leads` | 关键代表版本引导（最新可用、最新全部等） |
| `GET /api/v1/domains/{domain_id}/chunk-manifests` 等 | Chunk 清单列表、版本清单及按 `identity` 浏览文件分页/下载计划/单文件元信息 |
| `GET /api/v1/domains/{domain_id}/versions/{version}/files`, `file`, `file-content` | 远端或本地校验清单的文件树分页、单文件详情与受限只读文件内容 |
| `GET /api/v1/domains/{domain_id}/versions/{version}/artifact-tree` | 文件目录树浏览 |
| `GET /api/v1/domains/{domain_id}/versions/{version}/chunk-content` | 受官⽅主机白名单与体积上限保护的 Sophon Chunk 字节流代理（供前端浏览器合成文件/目录下载） |

### 3.3 远端/本地清单解析层

- **[manifest_readers.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/manifest_readers.py)**（867 行）：
  - 解析本地核验的清单与官方 MiHoYo Sophon Chunk 资源（Protobuf + Zstandard），带条目数/字节上限与 LRU 内存缓存（`MAX_CHUNK_MANIFEST_CACHE_ENTRIES = 8`、`64 MiB`），严格限制官方主机白名单（`OFFICIAL_SOPHON_HOSTS`：`autopatchcn.yuanshen.com`、`autopatchcn.bhsr.com`、`autopatchcn.juequling.com`、`autopatchcn.bh3.com`）并防止路径穿越（`strict_relative_posix`）。
- **[mihoyo_package_files.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/mihoyo_package_files.py)**（700 行）：
  - 通过 HTTP Range 等受界读取方式解析 MiHoYo 官方安装包分卷/ZIP 内文件清单与详情，用于支持包内文件浏览与版本文件级对比。

### 3.4 后台鉴权路由、版本/目录管理与运维调度

- **鉴权与路由（[admin_routes.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/admin_routes.py)）**：
  - 使用 `Authorization: Bearer <token>` + 常量时间比对（`hmac.compare_digest`）保护 `/api/v1/admin/*`。
  - 包含：调度配置 CRUD（`/sync/schedule`、`/probe/schedule`、`/probe/scheduler`）、单链接/批量链接探活（`/probe/url`、`/probe/urls`）、单版本探活（`/domains/{domain_id}/versions/{version}/probe`）、异步运维任务（`/operations/start|latest|{job_id}|{job_id}/cancel`）、目录与版本管理（`/catalog`、`/games`、`/domains`、`/domains/{domain_id}/versions`、`/editable`、`/artifacts/edit`）。
- **目录与版本维护（[catalog_admin.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/catalog_admin.py)、[admin_catalog_service.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/admin_catalog_service.py) — 339 行、[version_admin.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/version_admin.py) — 605 行）**：
  - `catalog_admin.py` + `admin_catalog_service.py`：`catalog.admin.json` 底层配置读写、后台目录聚合投影（`catalog_projection`）以及游戏/数据域 CRUD 与空目录安全删除。
  - `version_admin.py`：手工录入单 APK 版本、在线编辑现有版本元信息/APK/PC `artifacts`（保留原有不可变身份与血缘或按 Schema v2 重新生成合法 `artifact_id`）、切换 `is_visible`、永久删除版本快照。
- **探活写回与异步运维（[admin_probe.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/admin_probe.py)、[admin_operations.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/admin_operations.py)、[probe_scheduler.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/probe_scheduler.py)、[telegram_notify.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/telegram_notify.py)）**：
  - **单目标写回原则**：`probe_records` 只更新目标 `artifacts[].urls[].current`，不改写 `artifact_id`、血缘 provenance、references 与其它候选 URL。
  - **单活运维槽位**：`OperationManager` 通过互斥锁保证同一时间只运行一个 `discover` / `probe` 任务（或单次手动探活），采用有界环形日志（`MAX_JOB_LOGS = 256`）和增量游标（`after`）避免长时间任务撑爆内存或状态文件。
  - **定时调度**：`ProbeScheduler` 通过 `APSchedulerTimer` 每 5 秒检查持久化到期时间，到点先写回新 deadline 再触发 `OperationManager.start(...)`（支持 `normal` / `full` 模式），防止宕机重启重放积压任务。
  - **Telegram 通知**：`telegram_notify.py` 在批处理/定时发现新版本或探活状态变化时推送按游戏聚合的摘要通知（不阻塞主流程）。

---

## 4. 采集与探活插件层（`url_adapters/` & `probe_adapters/`）

### 4.1 官方发现适配器（`url_adapters/`）

严格遵守**官方源原则**（仅访问游戏厂商官方接口、启动器配置或 CDN 清单）：
- **调度入口（[url_adapters/service.py](file:///d:/Project/Active/Game%20Manifest%20Index/url_adapters/service.py)）**：
  - `DISCOVERERS`（13 款 Android）：
    - MiHoYo：`hk4e`、`hkrpg`、`nap`（`mihoyo_download_porter.py`），`bh3`（`mihoyo_bh3_download_porter.py`），`bh2`（`mihoyo_bh2_download_page.py`）
    - Hypergryph：`arknights`、`endfield`（`hypergryph_launcher_latest.py`）
    - Kuro：`wuwa`（`kuro_wuwa_mc_manifest.py`）、`pns`（`kuro_pns_manifest.py`）
    - Perfect World：`tof`、`p5x`、`nte`（`perfectworld_webops.py`）
    - Manjuu：`azurpromilia`（`manjuu_azurpromilia.py`）
    - 另含原生 Schema v2 组织构建器与厂商 APK 解析辅助（`apk_v2_organizer.py`、`*_apk_organizer.py`、`apk_manifest.py`）。
  - `PC_DISCOVERERS`（11 款 PC）：
    - MiHoYo（`hk4e`、`hkrpg`、`nap`、`bh3`）：两阶段并行写入同一规范记录——`mihoyo_game_packages.py`（包与补丁）+ `mihoyo_chunk_manifests.py`（Sophon Chunk 清单）
    - Kuro（`wuwa`）：`kuro_manifests.py`（含新版资源包端点的资源发现与清单）
    - Perfect World（`tof`、`p5x`、`nte`）：`perfectworld_patcher.py`
    - Hypergryph（`arknights`、`endfield`）：`hypergryph_game_packages.py`
    - Manjuu（`azurpromilia`）：`manjuu_azurpromilia.py`（官方 PC 启动器 `packageconfig` 在线签名发现与本地抓包导入）
  - 公共基础能力：`url_adapters/common.py`、`url_adapters/endpoints.json`。

### 4.2 URL 探活适配器（`probe_adapters/`）

- **唯一分发路由（[probe_adapters/registry.py](file:///d:/Project/Active/Game%20Manifest%20Index/probe_adapters/registry.py)）**：
  - 根据 `platform`、`vendor`、`game_id` 与 URL 精确匹配唯一适配器（多匹配或无匹配时报错，Android 末位可回退 `shared_generic_apk`）。
- **Android 适配器（`probe_adapters/android/`）**：`mihoyo_autopatch.py`、`mihoyo_bh3_cdn.py`、`mihoyo_bh2_benghuai.py`、`hypergryph_arknights_hycdn.py`、`hypergryph_endfield_hycdn.py`、`kuro_wuwa_mc_cdn.py`、`kuro_pns_txcdn.py`、`perfectworld_webops.py`、`manjuu_syncstation.py`、`shared_generic_apk.py`。
- **PC 适配器（`probe_adapters/pc/`）**：`hypergryph_arknights.py`、`hypergryph_endfield.py`、`mihoyo_autopatch.py`、`mihoyo_bh3_cdn.py`、`kuro_cdn.py`、`perfectworld_patcher.py`、`manjuu_syncstation.py`（配合 `mihoyo_package_common.py`）。
- **公共探活核心（[probe_adapters/common.py](file:///d:/Project/Active/Game%20Manifest%20Index/probe_adapters/common.py)、[probe_adapters/service.py](file:///d:/Project/Active/Game%20Manifest%20Index/probe_adapters/service.py)）**：
  - 使用子进程硬超时、Range/HEAD 探测、HTTP 403 明确判定不可用、OSS 未解冻归档识别等规则生成 `current` 证据；通过 [android_record_compat.py](file:///d:/Project/Active/Game%20Manifest%20Index/backend/android_record_compat.py) 将结果映射回 Schema v2 字段。

---

## 5. 前端架构（Vue 3 + TypeScript + Vite，`src/`）

### 5.1 路由、入口与 API 客户端

- **入口与路由（[main.ts](file:///d:/Project/Active/Game%20Manifest%20Index/src/main.ts)、[App.vue](file:///d:/Project/Active/Game%20Manifest%20Index/src/App.vue)、[router.ts](file:///d:/Project/Active/Game%20Manifest%20Index/src/router.ts)）**：
  - `/` 重定向至上次访问的游戏或默认 `/games/nte`；`/android/:gameId?` 兼容重定向至 `/games/:gameId/android`。
  - `/games/:gameId/:domainId?/:version?/:mode?` 挂载主页面 `ArchiveView`（首屏直出）。
  - `/admin` **路由级懒加载** `AdminView.vue`，使后台 JS 与专属 CSS 均不打入前台首屏包。
- **API 层与契约类型（[api.ts](file:///d:/Project/Active/Game%20Manifest%20Index/src/api.ts)、[types.ts](file:///d:/Project/Active/Game%20Manifest%20Index/src/types.ts)）**：
  - `apiBase()` 默认同源 `/api/v1`（可通过构建时 `VITE_API_BASE_URL` 覆盖）；自动附加 `no-cache` 与 `AbortSignal`，统一包装为 `ApiError`；区分公开 `api` 与携带 `Bearer` 令牌的 `adminApi`。

### 5.2 前台页面模块（`ArchiveView` 生态）

```text
ArchiveView.vue (1261 行: 路由协同、弹窗状态、领域呈现编排)
├── Composables (状态加载、筛选与呈现编排)
│   ├── useArchiveLoader.ts            # 游戏/域/版本列表与概览加载
│   ├── useArchiveArtifactsLoader.ts   # artifacts、leads、文件树、Chunk 清单分页加载
│   ├── useArchiveFiltersAndPacks.ts   # 鸣潮画质包状态、文件类型与 Chunk 组件筛选 (223 行)
│   ├── useArchivePresentationMeta.ts  # 面板标题、文件时间/体积摘要与历史归档引导 (257 行)
│   ├── useArchiveCompare.ts           # 版本对比状态与比较请求
│   ├── useArchiveExport.ts            # 下载/导出 JSON 与外链构造
│   └── useAvailabilityInvalidation.ts # 跨标签页监听后台探活失效刷新
├── 领域工具与纯函数
│   ├── domain-presentation.ts       # 按厂商/模式决定卡片字段、模式页签与标签映射
│   ├── archive-artifact-helpers.ts  # 日期/相对时间/首选可用 URL/图标推导
│   ├── game-meta.ts / game-icons.ts / game-activity.ts / site-changelog.ts
│   ├── chunk-download.ts / chunk-directory-download.ts / selected-file-download.ts
│   │   # 浏览器端拉取 chunk-content，配合 fzstd 解压与 spark-md5 校验合成文件/目录
│   └── clipboard.ts / version-grouping.ts
└── UI 组件
    ├── archive/
    │   ├── ArchiveGameSidebar.vue       # 左侧游戏切换、搜索与图标栏
    │   ├── ArchiveControlStrip.vue      # 平台/模式切换、版本选择器与过滤控制
    │   ├── ArchiveApkList.vue           # Android APK 卡片与元数据列表
    │   ├── ArchivePackageList.vue       # PC 安装包卡片、WuWa 资源包、分页浏览
    │   ├── ArchivePatchList.vue         # 通用 / WuWa / HoYo 三类差分补丁列表
    │   ├── ArchiveCompareView.vue       # 双版本结构化/文件级对比面板
    │   ├── ArchiveResourcePackPicker.vue / ArchiveWuwaRawIndexMenu.vue
    └── 通用浏览器与弹窗
        ├── VersionPicker.vue            # 大小版本分组选择器
        ├── ChunkManifestView.vue        # Chunk 清单概览与目录合成下载
        ├── ChunkFileBrowser.vue         # 虚拟/分页文件列表、多选打包与下载
        ├── chunk/ChunkFileDetailModal.vue # 单文件块分布与哈希详情弹窗
        ├── RemoteArtifactTree.vue / ArtifactTree.vue / FragmentFileRow.vue
        ├── SourceProvenanceModal.vue / SiteChangelogModal.vue / ProbeScheduleInfo.vue
```

### 5.3 后台管理控制台（`AdminView` 生态）

```text
AdminView.vue (729 行: 鉴权生命周期、全局 Toast/Confirm、跨 Tab 持久化状态宿主)
├── 专属样式 (仅 /admin Chunk 按层叠顺序加载)
│   ├── styles/admin-shell.css       (976 行: 外壳、左侧导航栏、登录页、全局通知、双栏骨架)
│   ├── styles/admin-catalog.css     (1013 行: 游戏/数据模块表单、图标预览、控件与标准按钮)
│   ├── styles/admin-content.css     (1635 行: 版本级联栏、健康概览、版本分组与 APK/PC 卡片)
│   ├── styles/admin-operations.css  (746 行: 探活调度面板、运维控制台与终端日志窗口)
│   ├── styles/admin.css             (572 行: 配置台 v2 扁平化覆盖层，0 重复块)
│   └── styles/admin-responsive.css  (345 行: 后台窄屏与断点适配层)
├── Composables (全部在 AdminView 创建，切换 Tab 不丢失状态)
│   ├── admin-shell.ts                  # AdminShell 共享接口契约
│   ├── useAdminContent.ts (726 行)     # 版本加载/保存、可见性、单版本探活与整体编排
│   │   ├── useAdminArtifactDrafts.ts (220 行) # 可视化/JSON 双模式草稿增删与单 URL 探测
│   │   └── useAdminVersionCreate.ts  (262 行) # 手工录入单 APK 新版本草稿校验与提交
│   ├── useAdminVersionList.ts (365 行) # 游戏/模块级联下拉、搜索/健康筛选、分层折叠与自动展开
│   ├── useAdminProbe.ts (148 行)       # 采集计划与探活定时参数及状态轮询
│   └── useAdminOperations.ts (436 行)  # 批量运维启动/取消/日志增量轮询/结果筛选
├── 领域工具
│   ├── admin-version-editor.ts      # Draft 转换、规范化对比、PC 差分校验与状态徽标
│   ├── admin-ui-capabilities.ts / admin-format.ts / admin-date-time.ts / operation-scope.ts
└── UI 组件 (components/admin/)
    ├── AdminLoginView.vue / AdminRail.vue / AdminConfirmDialog.vue
    ├── AdminGameCatalog.vue / AdminDomainCatalog.vue (+ CatalogShell / CatalogActions / SectionCard)
    ├── AdminContentPanel.vue (348 行)
    │   ├── AdminVersionList.vue (372 行)         # 级联选择、健康概览、主列表 (slot 承载工作台)
    │   ├── AdminVersionBasicCard.vue (92 行)     # 版本号/渠道/version_code/文件时间
    │   ├── AdminApkArtifactCard.vue (156 行)     # 单 APK 信息、URL 测试与校验值折叠
    │   └── AdminPcArtifactsCard.vue (222 行)     # PC 资源列表/JSON 切换 (+ AdminPcArtifactFields.vue)
    └── AdminProbePanel.vue (+ AdminOperationProgress.vue)
```

### 5.4 CSS 架构与按需拆包（[styles.css](file:///d:/Project/Active/Game%20Manifest%20Index/src/styles.css)）

- **前台全局 CSS（`src/styles.css` 按精确层叠顺序 `@import`）**：
  `base.css` → `layout-sidebar.css` → `control-strip-picker.css` → `file-panel-cards.css` → `chunks-toast.css` → `compare-view.css` → `remote-browser-misc.css` → `responsive.css` → `modals.css`。
- **组件作用域 CSS**：`src/styles/chunk-file-browser.css` 由 `ChunkFileBrowser.vue` 以 `<style scoped src>` 引入（详情弹窗样式已外提至 `ChunkFileDetailModal.vue`）。
- **后台独立 CSS**：`admin-shell.css` + `admin-catalog.css` + `admin-content.css` + `admin-operations.css` + `admin.css` + `admin-responsive.css` 仅由懒加载的 `AdminView.vue` 按层叠顺序引入，前台 CSS 构建体积约 `116.76 kB`（gzip `20.88 kB`），后台约 `76.03 kB`（gzip `13.79 kB`）。

---

## 6. 测试与工具脚本

### 6.1 自动化测试体系

- **前端测试（Vitest + jsdom，共 30 个测试文件 / 400 项测试）**：
  - 覆盖路由与状态持久化（`route-state.test.ts`、`version-routing.test.ts`、`archive-navigation.test.ts`）、领域呈现与格式工具（`domain-presentation.test.ts`、`game-activity.test.ts`、`admin-format.test.ts`、`admin-date-time.test.ts`）、Chunk 解析与多选下载（`chunk-download.test.ts`、`chunk-directory-download.test.ts`、`chunk-file-browser.test.ts`、`selected-file-download.test.ts`、`wuwa-file-manifest.test.ts`、`azurpromilia-catalog.test.ts`）、API 与后台能力（`api.test.ts`、`admin-view-capabilities.test.ts`、`operation-scope.test.ts` 等）。
- **后端与适配器测试（`unittest` / `pytest`）**：
  - `backend/test_*.py`（20 个测试文件）：覆盖底层原语与零跨模块私有导入校验（`test_backend_primitives.py`）、Schema v2、存储锁与事务、索引、公开 API 契约（`test_api_contract.py`）、管理员版本/操作/调度/通知、内存上界与基线审计。
  - `url_adapters/**/test_*.py` & `probe_adapters/test_*.py`：覆盖各厂商官方发现与探活适配回归测试。

### 6.2 一次性迁移/恢复脚本（`scripts/`）

- `scripts/migrate_pc_data_baseline.py`（及审计报告）：PC 基线数据迁移脚本。
- `scripts/recover_pc_history_from_archive_db.py`（及审计报告）：从历史归档数据库回填/恢复可证实 PC 历史记录脚本。

---

## 7. 构建、分支治理与部署形态

### 7.1 分支与发布模型（[BRANCHING.md](file:///d:/Project/Active/Game%20Manifest%20Index/BRANCHING.md) / [AGENTS.md](file:///d:/Project/Active/Game%20Manifest%20Index/AGENTS.md)）

- 长期分支：`main`（正式发布与部署导出基线）← `integration/v5`（主集成，吸收 `core/*`、`backend/*`、`frontend/*`、`integration/apk`、`integration/pc`）。
- 平台隔离：`apk/*` 基于 `integration/apk`，`pc/*` 基于 `integration/pc`，经各自集成验证后再正常合并进入 `integration/v5`。
- 禁止在 `main`、`integration/*` 与 `snapshot/*` 上直接开发提交；所有功能改动先在短周期任务分支完成验证后再整合。

### 7.2 生产自托管部署（[deploy/frontend/](file:///d:/Project/Active/Game%20Manifest%20Index/deploy/frontend/)）

- **前端自托管**：`npm run build:selfhost` 使用 `.env.selfhost`（`VITE_API_BASE_URL=/api/v1`）输出到 `.cache/selfhost/dist`，运行在独立的 `gmi-web.service`（非特权 Nginx 监听 `8080` 端口）：
  - `/api/` 反代至 `http://127.0.0.1:8000`（关闭缓冲、透传 Host 与协议头、300s 超时支持大文件/Chunk 流）。
  - `/assets/` 长期不可变缓存（`immutable`）；`/index.html` 与 SPA 回退 `no-cache`。
- **后端运行时**：仅部署 `backend/`、`probe_adapters/`、`url_adapters/`（不含测试文件）、`data/`、`.cache/`、`.venv/` 到服务端（`10.0.0.213`），由 `gmi-v5` 服务托管 `uvicorn backend.app:app`（`8000` 端口），并以服务器 `/opt/GMI/data` 作为线上权威数据。
