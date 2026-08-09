# Spells Battle 阿里云公网 IP 部署

首版直接使用 ECS 公网 IPv4，不需要申请域名、配置 DNS、申请证书或运行 Caddy。

## 前提

- 一台带公网 IPv4 的 Linux ECS；
- Docker Engine 和 Docker Compose Plugin；
- 阿里云安全组入方向开放 `8765/TCP`；
- `22/TCP` 仅允许管理员当前公网 IP；
- 服务器不需要摄像头、OpenCV、MediaPipe、Pygame 或角色图片。

`8765/TCP` 优先只允许两位玩家的公网 IP。如果玩家网络 IP 不固定，可以在短期验收窗口允许 `0.0.0.0/0`，测试完成后再收紧。

## 默认部署

```bash
git clone <your-repository-url> spells-battle
cd spells-battle
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8765/health
```

默认 `compose.yaml` 只运行权威服务端，并将 ECS 的 `8765` 映射到容器端口。外部设备使用下面的地址检查；请把示例 IP 替换成 ECS 控制台显示的公网 IPv4：

```bash
curl http://47.100.20.30:8765/health
```

返回结果应包含：

```json
{"status":"ok","rooms":0}
```

## 公网自动探针

在任意外部客户端仓库中运行：

```powershell
python tools/remote_duel_probe.py --url ws://47.100.20.30:8765
```

探针会检查健康状态，并通过两个真实 WebSocket 连接完成建房、加入、ready、施法、胜负和最终快照一致性验证。

## 两台 Windows 客户端

两台设备启动游戏前都设置相同的服务地址：

```powershell
$env:SPELLS_SERVER_URL = "ws://47.100.20.30:8765"
python main.py
```

进入菜单 `5 Remote Duel`。一端按 `C` 创建房间，另一端按 `J` 输入六位房间码；双方选择角色后按 `R` ready。

## 运维检查

```bash
docker compose ps
docker compose logs --tail=200 spells-server
curl -fsS http://127.0.0.1:8765/health
```

应用容器以非 root 用户运行，带有健康检查、`unless-stopped` 自动重启和 Docker JSON 日志轮转。房间只保存在内存中，服务重启会结束当前对局。

更新前先确认没有正在运行的房间：

```bash
git pull
docker compose up -d --build
```

需要回退时，切换到上一个已验证 Git commit 后重新构建；不要在正在运行的房间上进行无提示更新。

## 故障定位

- 外网 `/health` 不通：依次检查 ECS 公网 IP、安全组 `8765/TCP`、系统防火墙、容器状态和端口映射。
- ECS 本机 `/health` 不通：运行 `docker compose ps` 和 `docker compose logs --tail=200 spells-server`。
- WebSocket 可连接但无法开局：确认两端代码和协议版本一致，检查 `version_mismatch` 或房间错误。
- 客户端反复重连：确认 `SPELLS_SERVER_URL` 使用公网 `ws://IP:8765`，不能写容器名、`127.0.0.1` 或 ECS 私网 IP。
- 公网 IP 发生变化：更新两端环境变量即可，无需修改代码。

## 明文连接风险

`ws://` 不加密。链路上的第三方理论上可以观察或篡改游戏命令、房间码和重连信息。当前首版不传视频、图像、账户、聊天或支付数据，因此仅将此方案用于熟人之间的受控测试。面向陌生玩家公开运营或增加敏感数据前，必须升级 `wss://`。

## 可选域名/TLS 升级

以后需要 TLS 时，先把域名解析到 ECS，在 `.env` 中设置 `SPELLS_DOMAIN`，再使用可选配置：

```bash
docker compose -f compose.tls.yaml up -d --build
curl https://你的域名/health
```

客户端相应改为：

```powershell
$env:SPELLS_SERVER_URL = "wss://你的域名"
```

此升级只改变接入层，不改变战斗引擎、房间、协议或客户端模式。
