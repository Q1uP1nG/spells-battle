# Spells Battle 阿里云部署

## 前提

- 一台安装了 Docker Engine 与 Docker Compose Plugin 的 Linux ECS。
- 一个已备案/可用域名，A 记录指向 ECS 公网 IP。
- 阿里云安全组入方向仅开放：`443/TCP`、`443/UDP`，以及限定管理来源 IP 的 `22/TCP`。Caddy 可通过 443 的 TLS-ALPN 完成证书签发和续期。
- 服务器不需要摄像头、OpenCV、MediaPipe、Pygame 或角色图片。

## 部署

```bash
git clone <your-repository-url> spells-battle
cd spells-battle
cp .env.example .env
# 编辑 .env，把 SPELLS_DOMAIN 改成真实域名
docker compose up -d --build
docker compose ps
curl https://你的域名/health
```

Caddy 自动申请并续期 TLS 证书，将 HTTPS/WSS 流量转发给只在 Compose 内网暴露的权威服务。应用容器使用非 root 用户运行，并带有健康检查；两个服务均设置 `unless-stopped` 自动重启与 Docker JSON 日志轮转。

## 客户端

在两台 Windows 设备启动游戏前配置同一地址：

```powershell
$env:SPELLS_SERVER_URL = "wss://duel.example.com"
python main.py
```

进入菜单 `5 Remote Duel`。一端按 `C` 创建房间，另一端按 `J` 输入六位房间码；双方选择角色后按 `R` ready。

## 运维检查

```bash
docker compose ps
docker compose logs --tail=200 spells-server
docker compose logs --tail=200 caddy
curl -fsS https://你的域名/health
```

`/health` 返回 `{"status":"ok","rooms":N}`。房间只在内存中保存，服务重启会结束当前对局，这是首版的设计边界。

升级前先在本机运行完整测试。更新时执行 `git pull` 和 `docker compose up -d --build`。若需要回退，切回上一个已验证 Git commit 后重新 build；不要在正在运行的房间上做无提示热更新。

## 故障定位

- 证书失败：检查域名解析、443 安全组、ECS 防火墙和 TLS-ALPN 是否被上游代理拦截。
- `/health` 不通：先用 `docker compose ps` 查看容器健康状态，再查两个服务日志。
- WebSocket 能连接但无法开局：确认两端协议版本一致，并查看服务端是否返回 `version_mismatch` 或房间错误。
- 客户端反复重连：检查 `SPELLS_SERVER_URL` 必须使用公网 `wss://` 域名，不能写容器名或 ECS 私网地址。
