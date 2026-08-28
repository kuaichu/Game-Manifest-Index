# GMI V5 项目状态

## 项目作用

GMI V5 是 Game Manifest Index 的干净重建版本。

这个项目的目标是从官方或已验证来源采集游戏版本资源，整理成稳定的版本记录格式，
再通过后端 API 提供给前端使用。前端负责浏览版本、比较资源、复制链接、查看状态，
以及后续的后台管理操作。

项目需要同时支持两类资源：

- Android APK 资源；
- PC 资源，包括 packages、patches、voice、chunks、manifest 等。

APK 迁移从已经验证可用的 V4 工作现场开始。PC 迁移暂缓历史数据导入，等格式和适配器
稳定后再建立 PC 数据基线，避免把未定型数据混入可信主线。

## 项目身份和目录角色

- `E:\Project\Active\GMI V5`
  - 当前干净 V5 仓库。
  - 后续开发、迁移、验证都以这里为准。

- `E:\Project\Active\GMI`
  - 旧项目。
  - 只能作为旧实现参考来源。
  - 旧项目较乱，不允许整仓库或整分支直接合入 V5。

- `E:\Project\Active\GMI V4\apk-validated-baseline`
  - V4 中已经验证过的 APK 基线现场。
  - 当前工作树已封存到 V5 的 `snapshot/apk-validated-baseline` 分支。
  - 这个来源只能用于查看、diff、提取已确认文件和对比行为。

V4/V3 只能作为参考材料。V5 不允许从旧项目整仓合并，也不允许把旧项目的脏工作树重新打包成
V5 主线。

## 当前真实分支

### `main`

- 提交：`c6bf94b Initial empty baseline`
- 内容：空树。
- 定位：V5 最终可信产品状态。
- 规则：开发期间不直接提交，不直接开发。只有 `integration/v5` 完成最终验收后才合入。

### `integration/v5`

- 当前提交：以 Git 中 `integration/v5` 的实际分支指针为准。
- 定位：V5 开发期当前最新可信基线。
- 当前已包含：
  - `.gitignore`
  - `BRANCHING.md`
  - `PROJECT_STATUS.md`
  - 已晋级的前端基线
  - 已晋级的 `core/schema`
  - 已晋级的 `core/version-store`
  - 已晋级的 `core/indexes`

日常新任务应从最新 `integration/v5` 或对应平台 integration 分支切出。

### `integration/apk`

- 定位：APK 平台验证分支。
- 当前已包含完整 core、12 款 Android 数据基线、官方 URL adapters、probe adapters 和
  默认 collector registry。
- 当前平台验收：12/12 官方采集成功，12/12 专项 probe 为 `available` / HTTP 206，
  schema、artifact identity、indexes 和 provenance 检查通过。
- 晋级规则：使用 normal merge 合入 `integration/v5`，不得 squash 整个平台分支。

### `integration/pc`

- 定位：PC 平台验证分支。
- 当前包含已经同步的 shared core 基线和已验证的米哈游官方 PC package collector。
- 新 PC 任务从该分支创建，验证后 squash merge 回该分支。

### `frontend`

- 提交：`5baf8f7 Establish frontend baseline`
- 内容：旧前端迁入后的前端基线。
- 状态：已 build 验证，并已通过 squash merge 晋级到 `integration/v5`。
- 后续规则：冻结该分支。新的前端修改使用 `frontend/*` 任务分支。

### `snapshot/apk-validated-baseline`

- 提交：`bfb2023 Snapshot validated APK baseline`
- 类型：orphan branch，无父提交。
- 来源路径：`E:\Project\Active\GMI V4\apk-validated-baseline`
- 来源 HEAD：`5d3dd41`
- 快照时间：`2026-08-28 21:00:03 +08:00`
- 内容：V4 已验证 APK 工作树现场。
- 规则：只读参考，禁止 merge 到 `integration/*` 或 `main`。

### 已完成任务分支

- `core/branching-rules`
  - 用于更新 `BRANCHING.md`。
  - 已 squash merge 到 `integration/v5`。

- `core/schema`
  - 用于迁移新版 schema、校验和 artifact identity。
  - 已测试并 squash merge 到 `integration/v5`。

- `core/version-store`
  - 用于新版记录的安全保存、路径和覆盖规则。
  - 已测试并 squash merge 到 `integration/v5`。

- `core/indexes`
  - 用于生成和读取 Android/PC `index.json`。
  - 已测试并 squash merge 到 `integration/v5`。

- `apk/data-baseline`
  - 用于迁入 12 款 Android 的已验证历史数据和索引。
  - 已测试并 squash merge 到 `integration/apk`。

- `apk/url-adapters`
  - 用于迁入 12 款 Android 的官方采集器和厂商专项 organizer。
  - 已测试并 squash merge 到 `integration/apk`。

- `apk/probe-adapters`
  - 用于迁入四个厂商的 Android URL 探活与 canonical current 更新。
  - 已测试并 squash merge 到 `integration/apk`。

- `apk/registry-integration`
  - 用于注册 12 款 Android 的默认官方 collector 并提供内部 discovery API。
  - 已测试并 squash merge 到 `integration/apk`。

这些任务分支后续不再继续开发，可冻结或删除。

## 不可破坏的语义约束

重构不等于允许改变行为。任何任务分支都不得静默改变以下语义：

- 官方采集源或官方 endpoint；
- source provenance；
- JSON 字段含义；
- artifact identity；
- public API contract；
- APK/PC 平台归属边界。

官方采集源不能自行替换成第三方。Amarea/HoyoFiles 只能用于历史补全，不能替代官方采集链路。

如果确实需要改变上述语义，必须先明确声明原因、影响范围和验证方式，再进入实现。

## 已完成内容

### V4 APK 已验证流程

当前已确认：V4 APK 主流程正常，不需要重写。

已验证流程为：

```text
厂商专项采集
  -> 厂商专项整理
  -> 新格式检查
  -> 通用写入
  -> 从 artifacts[].urls[] 读取 URL
  -> 匹配厂商验活器
  -> 结果写入 urls[].current
```

12 款 Android 的 APK 相关测试已验证通过。V5 迁移 APK 时应提取这套已确认行为，而不是把
`snapshot/apk-validated-baseline` 整体合入。

### 分支和协作规则

`BRANCHING.md` 已建立 V5 分支规则：

- `main` 是最终可信状态；
- `integration/v5` 是开发期可信集成主干；
- `integration/apk` 和 `integration/pc` 是平台验收分支；
- `core/*`、`backend/*`、`frontend/*`、`apk/*`、`pc/*` 是短生命周期任务分支；
- `snapshot/*` 是只读历史参考；
- 任务分支验证后优先 squash merge；
- 长期 integration 分支之间使用 normal merge；
- Agent 不允许直接修改 `main`、`integration/*` 或 `snapshot/*`；
- 任务结束前必须检查 `git diff --stat` 和 `git diff --name-status`；
- 重构不得静默改变官方数据源、来源归属、字段语义、artifact identity、API 契约或 APK/PC 归属边界。

### 前端基线

旧前端已经迁入 V5，并晋级到 `integration/v5`。

主要内容：

- `package.json`
- `package-lock.json`
- `vite.config.ts`
- `tsconfig.json`
- `index.html`
- `public/`
- `src/`

已验证：

```text
npm run build
```

结果：通过。

### `core/schema`

新版 schema 已从 APK 快照中选择性迁入 V5。

当前文件：

- `backend/__init__.py`
- `backend/schema_v2.py`
- `backend/test_schema_v2.py`

当前能力：

- v2 version record 格式定义；
- strict validation；
- legacy record normalization；
- artifact identity key；
- `artifact_id` 生成和校验；
- schema 相关单元测试。

已验证：

```text
python -m unittest backend.test_schema_v2
```

结果：26 个测试通过。

### `core/version-store`

新版记录的通用保存能力已从 APK 快照中选择性迁入 V5。

当前文件：

- `backend/version_store.py`
- `backend/storage_locks.py`
- `backend/test_version_store.py`

当前能力：

- Android/PC canonical 数据路径；
- 新记录及已有 v2 记录校验；
- 损坏文件、identity 冲突和不安全路径阻断；
- matching legacy 记录原样保护；
- 已有 `is_visible` 人工字段保留；
- 默认不覆盖、显式覆盖和原子写入；
- 进程内及跨进程数据写锁。

已验证：

```text
python -m unittest backend.test_version_store backend.test_schema_v2
```

结果：40 个测试通过。

### `core/indexes`

Android/PC 版本索引能力已作为独立 core 模块加入 V5。

当前文件：

- `backend/indexes.py`
- `backend/test_indexes.py`

当前能力：

- Android/PC 索引路径和平台目录映射；
- 从有效版本记录生成公共版本摘要；
- 数字版本降序排序；
- 隐藏、损坏和 identity 不匹配记录过滤；
- 空索引删除和原子写入；
- 严格 index reader；
- 单游戏和全数据根目录索引重建。

当前 PC index 只写 Android/PC 样本共同确认的字段，不提前加入
`artifact_count`、`artifact_kinds` 或 `chunk_summary` 等专项摘要。

已验证：

```text
python -m unittest backend.test_indexes backend.test_version_store backend.test_schema_v2
```

结果：52 个测试通过。

### APK 数据基线

已从只读 `snapshot/apk-validated-baseline` 选择性迁入 12 款 Android 的已验证数据。

当前内容：

- 269 个 schema v2 版本记录；
- 12 个 `index.json`；
- 12 款游戏，覆盖米哈游、鹰角、库洛和完美世界。

历史记录继续保守使用 URL 级 `source_kind: legacy`，没有补写或伪造官方同步
provenance。数据文件与 snapshot 对应文件逐一一致，当前索引生成器可无差异重建全部
12 个索引。

已验证：

```text
python -m unittest backend.test_apk_data_baseline
python -m unittest backend.test_indexes backend.test_version_store backend.test_schema_v2
```

结果：54 个测试通过。

### APK URL adapters

12 款 Android 的厂商官方采集和 canonical v2 整理逻辑已从已验证 APK 快照中
选择性迁入。

| 厂商 | 游戏 | 输入 | 输出 | 直接依赖 | 行为变化 |
| --- | --- | --- | --- | --- | --- |
| 米哈游 | `hk4e`、`hkrpg`、`nap` | 官方 `download_porter` | 单 APK canonical v2 | curl、后续 APK probe、VersionStore | 成功路径无变化；probe 改为延迟导入 |
| 米哈游 | `bh3` | 独立官方 `download_porter` | 共享米哈游 organizer 的 canonical v2 | 同上 | organizer 异常统一包装为 adapter 错误 |
| 米哈游 | `bh2` | 官方 download page | 共享米哈游 organizer 的 canonical v2 | 同上 | organizer 异常统一包装为 adapter 错误 |
| 鹰角 | `arknights`、`endfield` | 官方 launcher latest | 单 APK canonical v2 | curl、后续 APK probe、VersionStore | 成功路径无变化；probe 改为延迟导入 |
| 库洛 | `wuwa`、`pns` | 官方 Android manifest | 单 APK canonical v2 | curl、后续 APK probe、VersionStore | 成功路径无变化；probe 改为延迟导入 |
| 完美世界 | `tof`、`p5x`、`nte` | 官方 gameDownload JS + APK manifest | 单 APK canonical v2 | curl、`remotezip`、`pyaxmlparser`、后续 APK probe、VersionStore | 成功路径无变化；probe 改为延迟导入 |

所有 endpoint 与 V4 已验证快照逐字符一致；输出继续使用
`provenance.source_kind=official_sync`，URL candidate 使用对应厂商 provider 和
`source_kind=official`。默认代码不包含 Amarea、HoYoFiles、GitHub、社区或其他第三方
fallback。旧 flat 米哈游 adapter 没有迁入，也不存在默认入口。

已验证：

```text
python -m unittest discover -s url_adapters -p 'test_*.py'
python -m unittest backend.test_apk_data_baseline backend.test_indexes backend.test_version_store backend.test_schema_v2
python -m compileall -q url_adapters
```

结果：18 个 adapter 测试和 54 个 core/data 回归通过。真实联网采集需等 APK probe 与
registry 接入完成后在 `integration/apk` 统一验收。

### APK probe adapters

四个厂商的 Android URL 专项探活、URL dispatch 和 canonical v2 current 更新已从
已验证 APK 快照中选择性迁入。

- 输入：版本记录中的官方 APK URL candidate，以及 vendor/game context；
- 输出：规范化 probe observation；写回时只替换目标 candidate 的 `current`；
- 来源：只探测 collector 已发现的官方 CDN URL，不承担版本 discovery；
- 依赖：Python 标准库、系统 curl、当前 schema v2；
- 游戏：覆盖全部 12 款 Android，8 个专项 probe 模块，其中共享模块按 game context 区分；
- V4 来源：transport、厂商 dispatch、重定向后二次 dispatch 和 BH3 特殊策略来自已验证实现；
- V5 调整：写回收敛为 v2-only，拒绝 legacy record；非正 timeout 在请求前阻断。

`apply_result()` 不改变原 URL、provider、source_kind、priority、artifact identity、checksum、
references 或 file time，不写顶层 status、artifact attributes、reason、confidence 等旧字段。
写入字段仅限 `state/http_code/checked_at/response_size/etag/crc64/last_modified/final_url`，且
`final_url` 只在跳转后地址实际变化时出现。

已验证：

```text
python -m unittest probe_adapters.test_common probe_adapters.test_service probe_adapters.test_registry
python -m unittest discover -s url_adapters -p 'test_*.py'
python -m unittest backend.test_apk_data_baseline backend.test_indexes backend.test_version_store backend.test_schema_v2
```

结果：23 个 probe、18 个 URL adapter 和 54 个 core/data 测试通过。另对米哈游、鹰角、
库洛和完美世界各 1 个基线官方 APK URL 执行 timeout 10 秒的真实只读探活，4/4 为
`available`、HTTP 206；未写回仓库数据。

### APK registry integration 与平台验收

内部 discovery registry 精确注册 12 款 Android 的 canonical v2 collector，提供单任务和
并发 `discover_games()` API。默认 registry 不含 legacy、old、第三方 collector 或 PC adapter，
也不提供第三方 fallback。每个采集结果在返回前重新通过 schema v2 校验。

公开 HTTP route、后台 operation、可持久化批量 probe 和 CLI 依赖 PHASE 8 的
`backend/api-contract` / `backend/sync-operations`，没有在 APK registry 分支中提前迁入。

在全新系统临时目录完成了 12 款 Android 的真实官方联网平台验收：

- 12/12 discovery 成功并写出 canonical v2；
- 12/12 命中对应厂商专项 probe；
- 12/12 `available`、HTTP 206；
- 12/12 probe 写回后 schema 仍有效且 artifact_id 不变；
- 12/12 索引重建成功并与临时记录一致；
- provenance、provider、source_kind 和 endpoint 均符合官方来源约束；
- 未发现 canonical 禁止字段或 PC adapter 混入。

相关自动验证共包括 25 个 URL adapter/registry、23 个 probe 和 54 个 core/data 测试。

### 米哈游 PC packages

四款中国服米哈游 PC 游戏已经接入官方 HoYoPlay `getGamePackages`：

| V5 游戏 | HoYoPlay game id | 官方 biz | 当前 archive 响应 |
| --- | --- | --- | --- |
| `hk4e` | `1Z8W5NHUQb` | `hk4e_cn` | 8 个连续分卷 |
| `hkrpg` | `64kMb5iAWu` | `hkrpg_cn` | 12 个连续分卷 |
| `nap` | `x6znKlJ0xK` | `nap_cn` | 10 个连续分卷 |
| `bh3` | `osvnlOc0S8` | `bh3_cn` | 1 个完整 archive |

四款统一使用官方 endpoint `https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages`
和 launcher id `jGHBHlcOq1`。collector 只读取 `main.major.game_pkgs`，明确排除 patches、
audio、pre-download、resource list 和 Sophon chunks。Amarea/HoyoFiles 没有进入默认链路。

archive basename 的 `.001`、`.002` 等后缀被解析为 canonical `package_type=segment` 和
从 1 开始的 `part`；无分卷后缀的单个 archive 使用 `package_type=full`。如果 full 与
segments 同时出现，两者都会保留。官方响应中的十进制字符串 size 会严格规范化为
canonical integer，MD5 规范化为小写；artifact id 只由共享 schema helper 生成。

真实只读采集 4/4 成功并通过 schema、provenance 和 artifact identity 检查。需要注意：
`getGamePackages` 的 archive 版本可能落后于同游戏当前 Sophon branch tag；本 adapter 只记录
package endpoint 实际返回的版本，不把它冒充 Sophon 当前版本，也不在本任务混入 chunk 数据。
package URL 尚未 probe，留给后续 `pc/probe-adapters`。

## 暂未迁移内容

以下内容还没有进入 V5 的可信基线：

- APK 公开 API 和后台 operation 接线（由后续 backend 阶段完成）；
- PC patches、voice、chunks 和其他厂商 manifest/package 适配器；
- PC probe adapters；
- PC 数据基线；
- backend API contract；
- backend sync operations；
- backend version admin；
- retention policy。

这些内容必须按 `BRANCHING.md` 的规则，通过独立任务分支迁移、验证、审查，再晋级到
对应 integration 分支。

## 当前下一步

原定近期顺序是：

```text
snapshot/apk-validated-baseline
  -> frontend 晋级 integration/v5
  -> core/schema
  -> core/version-store
  -> core/indexes
```

其中 `snapshot/apk-validated-baseline`、`frontend` 晋级和 `core/schema` 已完成。

APK 平台模块和首个 PC packages 任务已经完成，当前下一步是 `pc/mihoyo-patches`。

分支路径：

```text
integration/pc
  -> pc/mihoyo-patches
  -> validation
  -> squash merge -> integration/pc
```

预计修改范围：

- 米哈游 PC 官方差分包资源采集；
- canonical v2 patch artifacts；
- 对应 parser/organizer 测试和官方来源验证。

PC 开发不得修改 Android collector、organizer、probe 或 registry。

这一阶段不要迁入：

- `data/`
- `probe_adapters/`
- API route；
- frontend 文件；
- APK 采集器；
- APK 验活器；
- packages、voice、chunks 和其他厂商 PC 专项逻辑。

## 近期路线

推荐顺序：

```text
pc/mihoyo-patches
  -> pc/mihoyo-voice
```

PC 开发应等共享 core 稳定后再开始。`pc/data-baseline` 不要现在创建，等 PC 格式和适配器
稳定后再迁移历史数据。

后端业务能力建议在数据和适配器基础稳定后推进：

```text
backend/api-contract
  -> backend/sync-operations
  -> backend/version-admin
```

只有确认仍然需要 retention 行为时，才创建 `backend/retention-policy`。

## Agent 执行规则

每个任务开始前：

- 切到最新可信父分支；
- 创建短生命周期任务分支；
- 声明预计修改目录或文件。

每个任务结束前：

- 跑最小相关验证；
- 检查 `git diff --stat`；
- 检查 `git diff --name-status`；
- 对职责范围外文件给出明确解释，否则不得合并。

默认禁止事项：

- 不直接提交到 `main`；
- 不直接提交到 `integration/v5`、`integration/apk`、`integration/pc`；
- 不 merge `snapshot/*`；
- 不从未完成任务分支继续派生新任务分支；
- 不把旧项目 `E:\Project\Active\GMI` 整体搬进 V5。
