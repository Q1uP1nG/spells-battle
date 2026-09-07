# Remote Duel 本地运行与验收手册

## 架构边界

- 客户端：摄像头、MediaPipe/CV、键盘、渲染、声音和粒子。
- 服务端：房间、身份、法力、冷却、状态、弹体、碰撞、伤害、胜负和重连。
- 网络：仅 JSON 命令、领域事件和完整快照；不发送视频、图像、手部关键点、NumPy 对象或 pickle。
- 离线模式不连接服务器，Solo、PVE、本地 Duel、CV Training 保持原入口。

## 安装

客户端完整依赖：

```powershell
python -m pip install -r requirements.txt
```

纯服务端依赖：

```powershell
python -m pip install -r requirements-server.txt
```

客户端默认服务器地址由仓库根目录的 `client_config.json` 提供。环境变量
`SPELLS_SERVER_URL` 优先级更高，可用于临时切换本地或其他服务器；不设置环境变量时，
当前配置会直接连接 `ws://101.132.63.248:8765`。

## 本机启动

终端 1：

```powershell
$env:SPELLS_SERVER_HOST = "127.0.0.1"
$env:SPELLS_SERVER_PORT = "8765"
python -m server.app
```

终端 2 和终端 3：

```powershell
$env:SPELLS_SERVER_URL = "ws://127.0.0.1:8765"
python main.py
```

双方进入菜单 `5 Remote Duel`：

1. 设备 A 按 `C` 创建房间，并把六位房间码告诉设备 B。
2. 设备 B 按 `J`，输入房间码并按 Enter。
3. 双方用 `A/F` 选择自己的角色，再按 `R` ready。
4. 战斗中本机使用 `Q/W/E/R/T` 或 CV；服务器只接受本机被分配座位的输入。
5. 回合结束双方按 Space 请求 rematch；只有双方都确认才开始新回合。

## 自动验证

```powershell
python -m compileall -q .
python -m unittest discover -s tests
```

网络集成测试在随机本地端口启动真实 WebSocket 服务，覆盖两个客户端、相同快照、完整回合、重复 sequence、心跳、断线暂停、重连和 rematch，不依赖公网、摄像头、音频或 GUI。

部署后可直接运行无摄像头双客户端探针：

```powershell
python tools/remote_duel_probe.py --url ws://ECS_PUBLIC_IP:8765
```

它会先检查 `/health`，再创建两个真实 WebSocket 客户端，完成建房、加入、
ready、心跳、连续权威施法、胜负和双方最终快照一致性检查。只想快速检查握手与
一次施法时可增加 `--quick`。

## 公网验收清单

当前仓库代码已经通过本地自动化验收；公网更新和两台真实设备测试按用户要求延期。
以下清单保留供恢复部署时使用，未执行项不能标记为通过。

无域名公网部署步骤见 `docs/remote_duel_direct_ip_route.md` 和 `deploy/README.md`。发布前必须在两台不同网络的 Windows 设备上确认：

- `http://ECS_PUBLIC_IP:8765/health` 返回 ok；
- 两端可使用房间码进入同一局；
- 角色、HP、MP、状态、弹体、碰撞、胜负一致；
- finger 与 bright-wand CV 至少各完成一局，keyboard/CV 混用正常；
- 主动断网后双方暂停，45 秒内恢复网络可继续；
- 超过重连时限、版本不匹配和非法房间码均显示可理解错误；
- 连续完成至少三局 rematch；
- Solo、PVE、本地 Duel、CV Training 在服务器关闭时仍可运行。

## 首版边界

- 房间在单进程内存中，服务重启会结束当前对局。
- 没有账户、公开匹配、排行榜、聊天、数据库或 Redis。
- 不做伤害/命中的客户端预测；本地只立即显示“等待服务器确认”。
- Protego 网络输入宽限保持为 0。只有真实公网 RTT 数据证明需要时，才应把它做成服务端配置并重新评估公平性。
- JSON/Deflate 已足够首版；未证明是瓶颈前不引入 MessagePack。

当前线协议版本为 `2`。版本 2 要求回合内命令和领域事件携带
`match_id`，并在施法接受/拒绝事件中回传原始 `sequence`，用于隔离 rematch
前后的延迟消息和关联客户端 pending 状态。不同协议版本会被服务端明确拒绝。
