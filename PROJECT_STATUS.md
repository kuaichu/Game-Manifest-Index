# GMI V5 项目状态

## 项目作用

GMI V5 是 Game Manifest Index 的干净重建版本。

这个项目的目标是从官方或已验证来源采集游戏版本资源，整理成稳定的版本记录格式，
再通过后端 API 提供给前端使用。前端负责浏览版本、比较资源、复制链接、查看状态，
以及后续的后台管理操作。

项目需要同时支持两类资源：

- Android APK 资源；
- PC 资源，包括 packages、patches、voice、chunks、manifest 等。

APK 迁移从已经验证可用的 V4 工作现场开始。PC 数据基线在格式和适配器稳定后，按固定
历史快照与官方 current discovery 建立，避免把未定型数据混入可信主线。

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

- 当前可信指针：以 Git 中 `integration/v5` 的实际分支指针为准。
- PHASE 8 起始父提交：`639b117 Merge validated PC platform`。
- 定位：V5 开发期当前最新可信基线。
- 当前已包含：
  - `.gitignore`
  - `BRANCHING.md`
  - `PROJECT_STATUS.md`
  - 已晋级的前端基线
  - 已晋级的 `core/schema`
  - 已晋级的 `core/version-store`
  - 已晋级的 `core/indexes`
  - 已通过 normal merge 晋级的完整 APK 与 PC 平台基线

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
- 当前包含已同步的 shared core、8 款 PC collector/registry/probe、173 条 canonical records、
  157 份独立 manifests 和 8 个 indexes。
- 当前平台验收：191 项 Python 测试通过；8/8 官方 discovery、8 款代表 probe、历史/Android
  隔离、artifact identity、manifest/reference 和 index 重建检查通过。
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

### PC URL probe adapters

`probe_adapters/pc/` 已覆盖米哈游四款 archive/segment/patch/voice candidates、Kuro
`wuwa` index candidates 和 Perfect World 三款 ResList candidates；复用有限 Range transport，
严格按 platform/vendor/game/host/path dispatch。写回只更新精确
`artifacts[].urls[].current`，不会触碰 artifact identity、其他 candidates、references、
provenance 或 `manifest.base_urls`。

真实代表 URL 验收：`hkrpg`、`nap`、Kuro 和三款 Perfect World 为 available；`hk4e`
当前 archive endpoint 返回 404，BH3 当前对象为未恢复的 OSS Archive，两者按证据写为
unavailable。八款结果均通过 schema 和 current 白名单检查，未下载完整包体。

### Perfect World PC PatcherSDK file manifests

`url_adapters/pc/perfectworld_patcher.py` 已选择性适配成熟 PatcherSDK 协议，支持 `nte`、
`p5x`、`tof` 的官方 Windows `config.xml` 与 `ResList.bin.zip`：有限请求、AES/zlib
解码、ZIP/XML/path/object 严格校验，并为每款当前版本生成一个 canonical
`package/full/file_manifest` artifact 和独立 `files.json`。PatchList 文件级对象只保存在
文档中，不伪造成缺少版本路由的 patch；不猜测 voice 或 segment。

真实官方临时验收：`nte 1.3.13` 为 73 files/397 patch objects，`p5x 1.0.74` 为
3/833，`tof 6.3.3` 为 95/660；三款 schema、对象相对路径、provenance、artifact
identity 与临时持久化均通过，未下载游戏对象。

### Kuro Wuthering Waves PC file manifests

`url_adapters/pc/kuro_manifests.py` 已实现 Kuro GameStarter 官方 `wuwa` Windows
launcher/index manifest 采集：严格校验 launcher 与 file index、按官方 CDN 顺序做
MD5 fallback、生成 schema v2 file-manifest artifacts，并以原子方式保存外部 manifest
文档。`pns` 和其他游戏明确拒绝；文档只保留规范化 resource/deleteFiles 及官方同步
provenance。真实官方验收得到 `3.6.0`、3 个 CDN、1 个 full 和 46 个 patch manifests；
full 含 699 个 resources，47 份独立文档与 canonical record 引用逐一一致。

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
- 可在同一进程内/跨进程数据锁内显式保留已有 `artifacts`、`references` 或 `provenance`；
- 默认不覆盖、显式覆盖和原子写入；
- 进程内及跨进程数据写锁。

已验证：

```text
python -m unittest backend.test_version_store backend.test_schema_v2
```

结果：43 个测试通过。

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
和 launcher id `jGHBHlcOq1`。纯 package organizer 只读取 `main.major.game_pkgs`；正式持久化
入口已逐阶段扩展为 game packages/patches + voice packages/patches 的 complete record。
pre-download、resource list 和 Sophon chunks 仍明确排除。Amarea/HoyoFiles 没有进入默认链路。

archive basename 的 `.001`、`.002` 等后缀被解析为 canonical `package_type=segment` 和
从 1 开始的 `part`；无分卷后缀的单个 archive 使用 `package_type=full`。如果 full 与
segments 同时出现，两者都会保留。官方响应中的十进制字符串 size 会严格规范化为
canonical integer，MD5 规范化为小写；artifact id 只由共享 schema helper 生成。

真实只读采集 4/4 成功并通过 schema、provenance 和 artifact identity 检查。需要注意：
`getGamePackages` 的 archive 版本可能落后于同游戏当前 Sophon branch tag；本 adapter 只记录
package endpoint 实际返回的版本，不把它冒充 Sophon 当前版本，也不在本任务混入 chunk 数据。
package URL 尚未 probe，留给后续 `pc/probe-adapters`。

### 米哈游 PC patches

同一官方 `getGamePackages` 响应中的 `main.patches[*].game_pkgs` 已整理为 canonical game
patch artifacts：`main.patches[*].version` 是 `route_from`，`main.major.version` 是
`route_to`；artifact 使用 `kind=patch`、`component=game`、`package_type=differential` 和
`delivery_mode=archive`。

真实只读响应当前包含：

- `hk4e`: `5.4.0 -> 5.5.0`、`5.3.0 -> 5.5.0`；
- `hkrpg`: `4.3.0 -> 4.4.0`；
- `nap`: `3.0.0 -> 3.1.0`、`2.8.0 -> 3.1.0`；
- `bh3`: 当前没有 game patch。

每个 `game_pkgs` 文件独立成为 patch artifact；patch 不使用 `part`，即使未来同一路由出现
多个文件，也由 `name + route_from + route_to` 保持稳定 identity。同一路由的重复 basename
会被阻断。

`VersionStore` 对同 identity 的记录执行整体替换而不是 artifact 合并，因此正常持久化入口
使用单次 combined record，同时保留 packages 和 patches。纯 package organizer 的解析契约
保持不变；没有为此修改 core store。voice 任务也必须继续扩展 combined record，不能写入
voice-only record 覆盖已有 artifacts。

### 米哈游 PC voice

官方 `main.major.audio_pkgs` 已映射为 canonical optional voice packages；
`main.patches[*].audio_pkgs` 已映射为带 language 和 route 的 differential voice patches。
官方语言严格限定为响应实证的 `zh-cn`、`en-us`、`ja-jp`、`ko-kr`，未知值不会被静默猜测。

当前真实只读响应：

- `hk4e`: 4 个 major voice packages，2 条 route 各 4 个 voice patches；
- `hkrpg`: 4 个 major voice packages，1 条 route 含 4 个 voice patches；
- `nap`: 4 个 major voice packages，2 条 route 各 4 个 voice patches；
- `bh3`: 当前无 major voice 或 voice patch。

当前官方 voice URL 全部是单 archive，没有分卷。organizer 仍只在 basename 明确出现 `.001` 等
连续后缀时才为 voice package 写 `segment + part`；voice patch 永不写 `part`。同语言、同 route
多文件依靠 basename + language + routes 区分 identity。

正常持久化入口现在一次写入 game packages、game patches、voice packages 和 voice patches；
package-only 与 game-only combined organizer 继续保留各自纯解析契约。真实 4/4 完整记录已通过
schema、provenance、artifact identity 和临时持久化检查，package/patch artifacts 未丢失。

### 米哈游 PC Sophon chunks

实现覆盖四款中国服（`hk4e`、`hkrpg`、`nap`、`bh3`）的 HoYoPlay/Sophon 两步官方同步：
`getGameBranches` 严格选择对应 game id/biz 的唯一 `main`，再以 branch/package/password/tag
请求 `getBuild`。输出为 `chunk-manifests/<tag>.json` 外部文档及 canonical v2
`chunk_manifest` reference；现有 archive artifacts/provenance 会被保留。

manifest 只保存规范化 metadata、recipe URL 和统计字段，不下载或展开 manifest/chunks，recipe
password 不写入任何 collection、文档、record、日志或输出。若第二步或 record 持久化失败，旧
record 不变；官方文档可能作为 orphan manifest 留存，需后续人工处理。

四款真实只读验收均成功，未下载 manifest/chunk：

- `hk4e 7.0.0`: build `K75N8sBHhKJk`，5 个 manifests；
- `hkrpg 4.5.0`: build `rGIV4WEtxMWi`，5 个 manifests；
- `nap 3.1.0`: build `K6kIJzryVWIq`，116 个 manifests；
- `bh3 9.0.0`: build `FMryTs1shKAC`，2 个 manifests。

绝区零 `3.1.0` 实际按 archive -> chunk -> archive refresh 顺序验收：24 个 archive artifacts
全程保留，chunk reference 从 0 增至 1 后继续保留，artifact ids 和 archive provenance 不变。

### PC registry integration 与平台验收

内部 discovery registry 与 Android registry 分离，精确注册 8 款 Windows 游戏：米哈游
`hk4e/hkrpg/nap/bh3` 按 packages -> chunks 串行执行，Kuro `wuwa` 和 Perfect World
`tof/p5x/nte` 各执行一个官方 manifest/package stage；不同游戏之间有限并发。公开 API、
batch probe、scheduler、CLI 和 index rebuild 仍留给 PHASE 8 调用方，没有提前进入 registry。

每个 stage 返回后都会重新检查 schema、请求 identity 与 canonical 路径；米哈游同版本的后续
chunk stage 必须保留已有 artifact IDs 和 references。单个预期采集失败会记录到对应 stage 并
继续其他 stage/游戏，意外 `RuntimeError` 仍向调用方传播。Android 默认 scope、12 款注册关系和
原结果契约保持不变。

在全新系统临时目录完成 8 款官方 metadata 平台验收：8/8 discovery 成功，生成 11 份
canonical records、118 个唯一 artifact IDs、4 份 Mihoyo chunk manifests、47 份 Kuro
manifests（full 699 resources）和 3 份 Perfect World files 文档；NAP `3.1.0` 同一记录同时
保留 24 个 archive artifacts 与 chunk reference。全部记录通过 schema、identity、provenance、
manifest/reference 路径和 canonical 禁止字段检查，并重建 8 个 Windows indexes。

每款抽取一个实际 artifact URL 做有限 Range/metadata probe：`hkrpg`、`nap`、`wuwa`、
`nte/p5x/tof` 为 available/HTTP 206；`hk4e` 当前 archive 为 404，`bh3` 当前对象仍是未恢复的
OSS Archive，按官方证据标 unavailable 且不伪造 HTTP code。probe 写回只改变精确 candidate
的 `current`，其余 record 深比较保持不变。

### PC 数据基线

`pc/data-baseline` 已从旧仓库固定 commit
`85e92d5b7f8868bb5c28901606c50132fe4705bf`（tree
`7e64fddb974324b3aca39f1d50d31b20336bea81`）选择性迁移 PC 历史数据，并在迁移后执行一次
8 款官方 bounded discovery（timeout 30 秒、workers 4）。迁移脚本只从 Git object 读取固定
tree，不依赖 dirty worktree，也不下载资源正文。

最终基线包含 173 个 canonical schema-v2 records、1,499 个唯一 artifacts、157 个独立
schema-1 manifest 文档和 8 个可重建 PC indexes：`hk4e 56/697`、`hkrpg 18/244`、
`nap 19/437`、`bh3 32/27`、`wuwa 45/91`、`tof 1/1`、`p5x 1/1`、`nte 1/1`（records/artifacts）。
历史迁移阶段写入 168 records、1,449 artifacts、106 manifests；4 条 `official_launcher`、
12 条 hkrpg `zh-tw`、1 条 `official_api` chunk-only 空记录和 648 个没有 Kuro local
manifest 配对的 route artifacts 均在审计排除清单中。官方 current records 只保留 V5
collector 产生的 `official_sync` provenance；历史 record 只使用真实
`third_party_history` / `legacy_migration` provenance。

相关文件：`scripts/migrate_pc_data_baseline.py`、同名 audit 文档/JSON、
`backend/test_pc_data_baseline.py`。
测试覆盖固定 snapshot inventory/排除原因、canonical validation/artifact identity、来源与
manifest/reference 安全、8 个 index 无差异重建、Android data 与 `integration/pc` 无差异及
Git-object migration rerun。

### Backend public API contract

`backend/api-contract` 已实现 FastAPI 只读 public contract，覆盖当前前端实际调用的 games、
domains、versions、version detail、artifacts/tree、compare、leads、chunk manifests、文件列表/
详情和 bounded chunk content 共 16 个 GET routes。所有响应由显式 mapper 从 canonical v2、
indexes 和独立 manifest 文档投影，不直接暴露 `schema_version`、仓库路径或 Sophon secret。

Android 与 PC 均继续使用同一 flat `VersionRecord` 前端契约；只含 chunk reference 的合法 PC
历史记录使用明确空 package 字段，不伪造下载 URL。Kuro 与 Perfect World file manifests 从
checked-in 文档只读加载；Perfect World 下载地址按已验证 `object` identity 生成，没有可证明
base URL 的历史 Kuro 文档仍可浏览文件元数据但不补造下载链接。Mihoyo Sophon manifest/Chunk
读取使用官方 HTTPS host allowlist、有限 timeout/redirect/响应大小、checksum/protobuf/stat
校验和无隐式 retry；recipe secret 不进入响应、日志或错误。

API 专项 37 项与 schema/index/version-store 55 项回归通过；另核验 12 games/20 domains、442
records/1,768 artifacts、63 chunk documents/1,410 public entries、48 个 checked-in file-manifest
版本均可按对应 contract 读取。该 API contract 任务没有提前迁入 sync/probe、version admin 或
retention；后续 `backend/sync-operations` 在同一个 app factory 上独立注册受保护 admin routes。

### Backend sync / probe operations

`backend/sync-operations` 已实现受 Bearer token 保护的 discovery / probe 运维契约：生产 app
注册 14 个 frontend 已使用的 admin routes，但只有配置至少 16 字符且无空白的
`GMI_ADMIN_TOKEN` 后才启用；未配置返回 503，错误 token 返回 401。schedule 与 operation
snapshot 写入可配置的非数据 `state_root`，使用有界、原子 JSON 文件；默认 `.cache/` 与
VersionStore 的 `data/.cache/` 已显式忽略。运维任务保持单活动任务、daemon worker、协作取消、
重启中断转 failed 和增量日志游标语义。

手动 operation 支持 `discover`、`probe` 或固定的 discover→probe 顺序，并按 `all/android/pc`
scope 精确调用现有 official registries；同一 game id 在 all scope 下分别运行 Android 与 PC。
discovery 成功后每个受影响 domain 只重建一次 index。批量探活仅处理路径/identity/schema 均
有效的 canonical v2 Android / Windows 记录：逐 record 串行更新 candidates、records 间有限
并发，通过现有 probe/apply/VersionStore 与共享写锁保留 artifact identity、非 probe 字段和
`is_visible`，最后重建受影响 index。单 URL 无 public stable URL id 时只读；携带 id 时才精确
定位、持久化并重建索引。job snapshot 和日志不保存 URL、token 或 canonical record。

sync schedule 只保存 `{enabled,times}`，probe schedule 只保存
`{enabled,interval_hours,mode}`。前端现有文案和旧项目都只定义“保存配置，由系统计划任务触发”，
没有定义内部 timer；因此本阶段没有发明 daemon scheduler。外部 scheduler 的部署方式、时区、
漏跑补偿以及 sync schedule 应触发 discover 还是 discover+probe 仍为 **UNKNOWN**。

sync/probe 专项 36 项、public API 37 项、schema/index/version-store 55 项、registry 20 项和
probe service/registry 17 项通过；所有联网和写入边界均使用临时 data/state root 与 fakes，未对
checked-in baseline 做真实写入。

## 暂未迁移内容

以下内容还没有进入 V5 的可信基线：

- backend version admin；
- retention policy。
- 外部 scheduler 部署与上述 UNKNOWN 调度语义。

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

APK 平台模块，以及米哈游、Kuro、Perfect World 的当前 PC 采集、URL probe 与内部 registry
已完成验证。`pc/data-baseline` 已完成数据迁移、官方 current discovery、基线审计与
`integration/pc` 平台验收；PHASE 7 已 normal merge 到 `integration/v5@639b117`，当前
`backend/api-contract` 公开只读 API contract 已晋级；`backend/sync-operations` 已实现并通过
任务级验证，下一任务是 `backend/version-admin`。

分支路径：

```text
integration/pc
  -> pc/registry-integration
  -> validation
  -> squash merge -> integration/pc
  -> platform validation
  -> pc/data-baseline
  -> validation
  -> squash merge -> integration/pc
  -> platform validation
  -> normal merge -> integration/v5
```

数据基线任务没有修改 Android collector、organizer 或 probe，也没有修改 API route、frontend
或已完成的 PC collector/organizer/probe 语义。

## 近期路线

当前推进顺序：

```text
integration/pc
  -> normal merge -> integration/v5@639b117（已完成）
  -> backend/api-contract（已完成）
  -> backend/sync-operations（任务验证完成）
  -> backend/version-admin
```

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
