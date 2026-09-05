# GMI V5

GMI V5 是一个游戏资源 Manifest 索引与查看项目，提供 Android 与 PC 资源记录、版本归档、来源信息和管理操作的 API 及网页界面。

## 日常入口

唯一日常工作目录是：

```text
E:\Project\Active\GMI V5
```

请从该目录打开 PowerShell、安装依赖、启动服务和运行检查。其他 worktree 可能仍有未提交或暂缓的修改，保留供核对，不作为日常入口，也不要直接整目录覆盖回来。

## 目录概览

| 路径 | 职责 |
| --- | --- |
| `backend/` | FastAPI 应用、API 合约、管理路由和状态操作 |
| `src/` | Vue + TypeScript 前端页面、组件和测试 |
| `url_adapters/` | 官方来源 URL 发现与 Android/PC 适配 |
| `probe_adapters/` | URL 探测与结果应用 |
| `data/` | 正式数据与索引 |
| `.cache/` | 本地状态、临时数据和测试副本 |
| `public/` | 前端静态资源 |
| `scripts/` | 历史数据迁移、恢复工具及审计记录 |
| `dist/` | 前端构建输出 |

## Windows PowerShell 启动

在项目根目录执行：

```powershell
python -m pip install -r backend/requirements.txt
npm ci
```

启动后端（另开一个位于项目根目录的 PowerShell；先将令牌占位符换成自己的本地管理令牌）：

```powershell
$env:GMI_ADMIN_TOKEN = "<local-admin-token>"
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

启动前端开发服务器：

```powershell
npm run dev
```

前台默认为 `http://127.0.0.1:5173/`，后台为 `/admin`；端口被占用时以 Vite 输出为准。后端健康接口为 `http://127.0.0.1:8000/api/v1/health`。

Vite 将 `/api` 请求代理到 `http://127.0.0.1:8000`。需要生产前端文件时运行：

```powershell
npm run build
```

部署时应提供静态前端文件，并由 Web 服务器将 API 请求反向代理到后端。Vite proxy 只用于开发，不是生产部署方案。

## 本地配置

后端支持以下环境变量；路径配置可选，占位符需替换为实际路径。在启动后端的同一个终端设置，已有进程需重启后生效：

```powershell
$env:GMI_ADMIN_TOKEN = "<local-admin-token>"
$env:GMI_DATA_ROOT = "<absolute-path-to-formal-data>"
$env:GMI_STATE_ROOT = "<absolute-path-to-local-state>"
```

真实令牌只在运行环境中设置，不要写入仓库或日志。不设置 `GMI_ADMIN_TOKEN` 时，管理接口不可用。未设置路径时，正式数据默认使用项目根目录下的 `data/`，状态默认使用 `.cache/`。

正式 `data/` 与当前测试副本 `.cache/local-test/20260905-090956/data` 含义不同。后者是临时测试副本，不保证永远存在，也不能被当作正式基线或替代正式数据目录。

测试后台写操作时，将 `GMI_DATA_ROOT` 指向数据副本、`GMI_STATE_ROOT` 指向独立状态目录；默认启动命令会使用正式 `data/`。

## 常用检查

优先运行对应模块测试，例如目录管理：

```powershell
python -m unittest backend.test_admin_version_admin
npm test -- --run src/admin-view-capabilities.test.ts
```

需要完整前端回归时：

```powershell
npm test
```

也可以针对当前改动运行最近的后端测试或前端测试文件。构建不是每次修改都必须运行；根据改动范围执行最小相关检查即可。

## 分支规则

分支、合并和晋级规则以 [`BRANCHING.md`](BRANCHING.md) 为最高权威。

日常不要直接在 `main` 或 `integration/*` 上开发。新任务应从相应的最新集成分支创建临时 task branch，完成验证后再按规则合并。已完成的旧 worktree 不是日常入口；不要因为它们不再使用就擅自删除。

## 当前边界

retention 行为，以及 external scheduler 的部署、触发动作、时区和 missed-run 行为尚未实现或验证，相关语义保持未知。不要把它们当作已实现的自动定时任务，也不要据此推断生产部署行为。
