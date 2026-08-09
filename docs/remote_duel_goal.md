# 可直接发布的 Goal 指令

以下代码块可以直接作为 Codex Goal 发布。它以当前已经完成的重构为基线，不重复实施已通过的阶段。

```text
在 C:\Users\15261\Desktop\magic_spale_refactor 中，继续完成 Spells Battle 的异地双设备对战项目。

开始任何修改前，必须完整阅读并遵守：
1. docs/remote_duel_refactor_architecture.md（总体架构与完成定义）；
2. docs/remote_duel_direct_ip_route.md（当前确定的无域名公网路线）；
3. docs/remote_duel_progress.md（已完成工作、测试基线和剩余验收）；
4. docs/remote_duel_runbook.md 与 deploy/README.md（运行、部署和验收步骤）。

当前仓库已经实现权威 BattleEngine、房间码、WebSocket + JSON 协议 v2、客户端 Remote Duel、断线暂停与重连、rematch、部署探针和服务器运行加固。先检查 Git 状态并运行相关测试，确认现有实现后继续；不要重做已经完成并通过测试的 Phase 0-7，也不要用一次性重写替代现有模块。

最终目标：在不申请域名、不配置 DNS、不申请 TLS 证书的前提下，把权威服务器部署到带公网 IPv4 的阿里云 Linux ECS，使两台处于不同网络的 Windows 设备通过 `ws://ECS_PUBLIC_IP:8765`、房间码和现有客户端完成远程对战。

部署路线硬约束：
- 默认使用根目录 compose.yaml，只运行 spells-server 并发布 8765/TCP。
- 阿里云安全组开放 8765/TCP；优先限制为玩家公网 IP，无法固定时只在短期验收窗口允许 0.0.0.0/0。22/TCP 只允许管理员来源 IP。
- 域名、Caddy、TLS 和 wss:// 不是首版完成前置条件。compose.tls.yaml 只能作为未来可选升级，不得阻塞当前路线。
- 客户端服务器地址来自 SPELLS_SERVER_URL，不把真实公网 IP 写死进 Python 代码。
- 必须明确接受并保留文档中的安全边界：ws:// 是明文，仅适合熟人、小规模、受控测试；面向陌生用户或传输账户、聊天、支付等敏感数据前必须升级 wss://。

架构硬约束：
- 服务端是唯一战斗权威，不退化为仅转发双方消息。
- 摄像头、MediaPipe、finger/wand CV、渲染、声音和粒子始终留在客户端。
- 网络只传命令、领域事件和完整快照；禁止传视频、图像、关键点、NumPy 对象或 pickle。
- 服务端根据连接绑定身份，不信任客户端 player_index。
- 继续要求 protocol_version、match_id、sequence、server_tick 和关联 ID；协议变化必须更新版本、测试和文档。
- 网络线程只能通过线程安全队列与 OpenCV/UI 主线程通信。
- Solo、PVE、本地 Duel 和 CV Training 必须永久支持无服务器运行。

执行顺序：
1. 审计当前仓库和测试结果，保留用户已有修改，不回退无关变更。
2. 运行 compileall、部署/协议/服务器相关测试和完整测试套件；不得通过删断言、跳过测试、吞异常或改变玩法获得通过。
3. 确认 compose.yaml、.env.example、Dockerfile、/health、日志轮转、自动重启、连接/消息/施法限流和重连令牌脱敏符合直连路线。
4. 获得 ECS 公网 IP 和部署访问权限后，按 deploy/README.md 构建并启动服务；依次验证 ECS 本机 health、外网 health 和 tools/remote_duel_probe.py 完整公网探针。
5. 在两台不同网络的真实 Windows 设备上完成房间码加入、角色选择、keyboard/CV 混用、完整胜负、断线恢复和连续三局 rematch，确认双方 HP、MP、状态、弹体、碰撞和胜负一致。
6. 把部署参数、测试命令、真实结果、故障与回退记录追加到 docs/remote_duel_progress.md；不得记录 SSH 密钥、完整重连令牌或其他秘密。

允许在当前工作范围内顺带修复明确发现的缺陷，并优化确定性、配置校验、结构化日志、稳定 ID、协议测试、部署诊断和测试隔离。不得顺带重调 CV 阈值、玩法数值、角色平衡或重做美术。

只有在以下情况暂停向用户确认：需要 ECS 公网 IP/SSH 等外部信息；需要购买新增云资源；需要改变玩法、公平性或操作方式；需要删除兼容 API 或迁移用户数据；发现两种会显著影响长期成本且无法由现有文档裁决的方案。域名缺失本身不是阻塞条件。

每次交付说明：实现摘要、修改文件、架构影响、测试命令与结果、尚存风险、下一步。最终完成必须满足架构文档“完成定义”和无域名路线的“两台异地真实设备验收”，不能仅以本地自动化测试代替公网验收。
```
