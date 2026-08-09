# 可直接发布的 Goal 指令

以下内容可直接作为 Codex Goal 使用：

```text
在 C:\Users\15261\Desktop\magic_spale_refactor 中，依据 docs/remote_duel_refactor_architecture.md，以渐进、可测试、可回退的方式，将 Spells Battle 重构为支持阿里云权威服务器和两台异地设备远程对战的客户端/服务器系统。

必须保留并持续验证现有 Solo、PVE、本地 Duel、CV Training、finger/wand 输入、角色、音效和渲染功能。摄像头、MediaPipe 和手势识别必须始终留在客户端；网络只传命令、领域事件和战斗快照。客户端只发送施法意图，服务端负责唯一权威的法力、冷却、状态、弹体、克制、碰撞、伤害和胜负计算。

严格按架构文档中的 Phase 0 到 Phase 7 顺序推进。一次只实施一个可独立验收的小阶段或子阶段；优先增加兼容适配层，禁止未经验证的大规模文件移动或一次性重写。每次变更前检查相关代码和测试，每次变更后运行相关测试，阶段结束运行完整测试套件。不得通过删除断言、跳过测试、吞掉异常或修改无关玩法来获得通过。

首要工作：
1. 完成 Phase 0，修复或明确 Git 基线，确认当前 compileall 和 374 测试基线，并消除测试写入真实 logs/cv_sessions 的副作用。
2. 完成 Phase 1，引入 CastIntent、BattleSession 和 LocalBattleSession，让 CV 与键盘通过统一命令入口施法，同时保持所有现有模式行为不变。
3. 在 Phase 1 全部测试通过后再进入 Phase 2，提取无摄像头、无渲染、无音频依赖的权威 BattleEngine，并以 BattleEvent 驱动本地表现。

架构硬约束：
- 服务端权威，不采用双方客户端各自模拟后仅转发消息的方案。
- 第一版使用 WebSocket + JSON，消息具有 protocol_version、match_id、sequence、server_tick 和必要的关联 ID。
- 不传视频、图像、关键点、NumPy 对象或 pickle。
- 服务端根据连接绑定身份，不能信任客户端提交的 player_index。
- 所有权威时间由调用方注入并使用比赛相对时间；权威规则不得直接调用 time.monotonic()。
- 权威状态和粒子、音效、flash、震动等表现状态分离。
- 网络线程通过队列与 OpenCV/UI 主线程通信，不能直接绘制或修改主线程对象。
- Solo、PVE、本地 Duel 和 CV Training 永远可以无服务器运行。

允许在当前阶段范围内顺带优化确定性、结构化日志、配置校验、稳定 ID、协议测试和测试隔离。不得顺带重调 CV 阈值、玩法数值或重做美术。

当遇到以下情况时暂停并向用户确认：
- 需要改变玩法、公平性或现有操作方式；
- 需要删除兼容 API 或迁移用户数据；
- 需要新增付费云服务、数据库或第三方平台；
- 架构文档与实际代码存在无法兼容的重大差异；
- 同一问题存在两种会显著影响后续成本的方案。

每个阶段的交付必须包含：实现摘要、修改文件、架构影响、测试命令与结果、尚存风险、下一阶段建议。最终完成标准以 docs/remote_duel_refactor_architecture.md 的“完成定义”为准。
```

