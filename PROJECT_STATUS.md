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

- 当前已知基线提交：`ccb6e00 docs: add V5 project status`
- 定位：V5 开发期当前最新可信基线。
- 当前已包含：
  - `.gitignore`
  - `BRANCHING.md`
  - `PROJECT_STATUS.md`
  - 已晋级的前端基线
  - 已晋级的 `core/schema`
  - 已晋级的 `core/version-store`

日常新任务应从最新 `integration/v5` 或对应平台 integration 分支切出。

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

## 暂未迁移内容

以下内容还没有进入 V5 的可信基线：

- Android/PC `index.json` 生成与读取；
- APK 数据基线；
- APK URL adapters；
- APK probe adapters；
- APK registry 和 API 接线；
- PC packages、patches、voice、chunks、manifest 相关适配器；
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

当前下一步建议做 `core/indexes`。

分支路径：

```text
integration/v5
  -> core/indexes
  -> validation
  -> squash merge -> integration/v5
```

预计修改范围：

- Android `index.json` 生成和读取；
- PC `index.json` 生成和读取；
- 对应索引规则和测试。

优先参考 snapshot 中与索引直接相关的已验证实现和测试。

这一阶段不要迁入：

- `data/`
- `url_adapters/`
- `probe_adapters/`
- API route；
- frontend 文件；
- APK 采集器；
- APK 验活器；
- PC 专项逻辑。

## 近期路线

推荐顺序：

```text
core/indexes
  -> integration/apk
  -> apk/data-baseline
  -> apk/url-adapters
  -> apk/probe-adapters
  -> apk/registry-integration
  -> APK 真实联网验收
  -> integration/v5
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
