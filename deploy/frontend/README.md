# 独立托管前端

这是当前唯一的正式前端入口：运行在 `10.0.0.213:8080`，由用户自己的反向代理转发到 `gmi.yeque.top`，域名和外层反代不由本配置管理。原 Cloudflare Pages 站点与 9000 端口公网 API 已停用，推送 `main` 不会更新线上前端。

## 构建

在项目根目录执行 `npm ci`、`npm run build:selfhost`。输出位于 `.cache/selfhost/dist/`，使用 `.env.selfhost` 中的同域 `/api/v1`；不读取 `.env.production` 中已停用的公网 API 地址。发布线上前端只用这个构建；`npm run build` 的产物仍指向已停用的 API，不能用于部署。

## 目录与服务

| 路径 | 内容 |
| --- | --- |
| `/opt/gmi-web/site/` | 构建完成的静态文件，不放源码、数据或凭证 |
| `/opt/gmi-web/nginx.conf` | 本目录提供的 Nginx 配置 |
| `/opt/gmi-web/bin/nginx`、`mime.types` | Debian 官方包中的 Nginx 二进制和 MIME 类型表 |
| `/etc/systemd/system/gmi-web.service` | 独立前端服务，以 `www-data` 身份运行 |

这里使用独立的 `gmi-web.service`，不安装或启动发行版的默认站点，不改其他项目的服务。确认 8080 未被占用，将 Debian 官方 `nginx`、`nginx-common` 包解包后，只取 `usr/sbin/nginx` 和 `etc/nginx/mime.types` 放到表中位置，并用 `ldd /opt/gmi-web/bin/nginx` 确认运行库齐全。安装包和解包临时目录在验证通过后删除。

上传静态文件及配置后，设置目录和文件可供 `www-data` 读取，执行：

```sh
systemctl daemon-reload
systemctl enable --now gmi-web
curl -fsS http://127.0.0.1:8080/api/v1/health
```

`gmi-web` 提供 HTML history 回退，刷新 `/games/...` 和 `/admin` 返回前端；`/assets/` 缺失文件返回 404；`/api/` 保留原路径转发到 `127.0.0.1:8000`，包括流式下载。浏览器只访问同一个入口，无需额外配置 CORS。外层反向代理需支持流式传输；HTTPS、安全上下文及域名由外层提供，目录保存等浏览器功能依赖安全上下文。

## 更新和验证

上传新的构建产物即可更新页面，不需要重启 GMI 后端。发布新 HTML 前先上传全部对应的 assets；确认新入口健康后再清理本次替换的旧构建文件。修改 Nginx 配置后先校验，再 reload：

```sh
runuser -u www-data -- /opt/gmi-web/bin/nginx -e stderr -t -p /opt/gmi-web/ -c /opt/gmi-web/nginx.conf
systemctl reload gmi-web
systemctl is-active gmi-web
journalctl -u gmi-web -n 30 --no-pager
curl -fsS http://127.0.0.1:8080/games/nap/pc/3.2.0/files >/dev/null
curl -fsS http://127.0.0.1:8080/api/v1/health
```

仅部署静态产物和上述运行配置；不改 `/opt/GMI/data`、`.cache`、后端环境文件和管理计划。未发布的本地后端功能也不随前端部署上传。
