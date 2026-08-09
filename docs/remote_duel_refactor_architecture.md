# Spells Battle 远程对战重构架构设计

状态：待实施  
目标平台：Windows 客户端 + 阿里云 Linux 服务端  
基线：保留 Solo、PVE、本地 Duel、CV Training，以及当前 374 个自动化测试

## 1. 重构目标

本次重构的目标不是改进手势识别精度，而是在不破坏现有玩法的前提下，将项目演进为支持两台异地设备实时对战的客户端/服务器系统。

目标体验：

1. 玩家 A 与玩家 B 分别在自己的设备上运行完整客户端。
2. 摄像头、MediaPipe、finger/wand 轨迹和手势分类全部留在本机。
3. 客户端只向服务器发送施法意图、准备状态和房间操作，不上传视频、图像或手部关键点。
4. 阿里云服务端维护唯一权威战局，计算法力、冷却、状态、弹体、克制、碰撞、伤害和胜负。
5. 客户端接收战斗快照和领域事件，并在本地完成画面、音效、粒子和提示渲染。
6. 网络不可用时，现有 Solo、PVE、本地 Duel 和 CV Training 仍然可以离线运行。

## 2. 明确不做的内容

第一版不包含：

- 摄像头视频传输、语音或文字聊天；
- 全球匹配、排行榜、好友系统和完整账户系统；
- 客户端预测弹体、回滚网络代码或帧级确定性同步；
- 迁移或重新训练现有 CV 分类器；
- 为了联网而重写渲染系统；
- 在第一阶段引入数据库、Redis、消息队列或微服务。

房间和战局第一版保存在服务器内存中。先完成可靠的双人房间码对战，再评估持久化需求。

## 3. 核心架构决策

### 3.1 权威服务器，而不是消息转发器

服务器不只是把 A 的消息转给 B。客户端发送“我想做什么”，服务器决定“实际发生了什么”。

```text
Client A                         Authoritative Server                         Client B
Camera -> CV -> CastIntent  ---> Room + BattleSession <--- CastIntent <- CV <- Camera
Render <- Snapshot/Event    <--- Battle simulation   ---> Snapshot/Event -> Render
```

若客户端各自运行完整战斗并仅互相转发法术，两边的时钟、帧率、丢包和消息顺序会造成状态分叉。权威服务器可以保证双方 HP、MP、冷却、弹体和胜负完全一致，也为后续防作弊和断线恢复留下空间。

### 3.2 不传视频，只传低频命令

远程对战网络层不接触 OpenCV 图像。识别完成后只发送类似下面的消息：

```json
{
  "type": "cast_intent",
  "protocol_version": 1,
  "match_id": "M7K2Q9",
  "sequence": 42,
  "spell": "incendio",
  "client_time_ms": 18452
}
```

服务器根据连接身份确定玩家编号，不能信任客户端传入的 `player_index`。

### 3.3 WebSocket + JSON 作为第一版协议

首版使用 WebSocket：

- 输入事件频率低，JSON 的调试便利性比二进制节省更重要；
- 同一连接支持双向主动推送；
- 可以通过 Nginx 或 Caddy 使用 `wss://`；
- 浏览器工具、Python 测试客户端和日志都容易接入。

第一版建议服务器 30 Hz 固定步进，10-15 Hz 广播状态快照。客户端以现有 60 FPS 渲染，并对远端弹体位置做插值。实际参数必须放入配置，不能散落为魔法数字。

### 3.4 命令、领域事件、状态快照三类消息分离

- Command：客户端请求，例如创建房间、加入、准备、选择角色、施法、重开。
- Domain Event：已经发生的离散事实，例如施法接受、施法拒绝、命中、格挡、克制、治疗完成、回合结束。
- Snapshot：某个服务器 tick 的完整可恢复状态，例如玩家属性、状态剩余时间、弹体和胜者。

事件保证及时反馈，快照用于纠偏、重连和消除丢事件后的状态偏差。

## 4. 目标模块结构

采用增量新增结构，不在第一阶段大规模改名或搬迁已有模块：

```text
magic_spale_refactor/
  main.py                         # 现有客户端入口，保留
  client_main.py                  # 可选：后期提取出的客户端入口

  game/
    battle.py                     # BattleGame 兼容外壳
    battle_engine.py              # 纯权威规则与固定世界坐标
    commands.py                   # CastIntent、ReadyCommand 等
    events.py                     # BattleEvent 及事件类型
    snapshots.py                  # BattleSnapshot DTO 与转换
    session.py                    # LocalBattleSession 接口与实现
    presentation.py               # 本地粒子、音效、flash、震动派生
    mode.py                       # 现有离线模式；后续接入 Remote Duel

  network/
    protocol.py                   # 消息 schema、编码、解码、版本校验
    client.py                     # WebSocket 客户端、发送队列、接收线程/任务
    remote_session.py             # RemoteBattleSession，向 UI 暴露统一接口
    clock.py                      # 服务器时钟偏移和快照插值时间
    errors.py                     # 可展示的连接/协议错误

  server/
    app.py                        # WebSocket 与 health check 入口
    room.py                       # Room、座位、ready、重连令牌
    room_manager.py               # 创建/加入/销毁房间
    battle_session.py             # 固定 tick，持有权威 BattleEngine
    connection.py                 # 连接生命周期、心跳和发送
    config.py                     # 环境变量与服务端配置
    logging.py                    # 结构化日志和关联 ID

  tests/
    test_battle_engine.py
    test_battle_snapshots.py
    test_protocol.py
    test_local_battle_session.py
    test_remote_battle_session.py
    test_server_rooms.py
    test_server_integration.py

  deploy/
    Dockerfile.server
    compose.yaml
    Caddyfile.example             # 或 nginx.conf.example，二选一
    env.example
```

文件名可以在实施时小幅调整，但职责边界不得改变。

## 5. 核心接口设计

### 5.1 输入命令

```python
@dataclass(frozen=True)
class CastIntent:
    spell: str
    sequence: int
    client_time_ms: int
    source: str  # "cv" or "keyboard"
```

CV 控制器不再直接调用 `game.cast_spell()`。它返回或通过回调发布 `CastIntent`。键盘输入也使用同一个入口。

为了保持兼容，第一阶段可以提供适配器：

```python
class LocalBattleSession:
    def submit_cast(self, player_index: int, intent: CastIntent, now: float):
        return self.game.cast_spell(player_index, intent.spell, now)
```

联网实现只发送命令：

```python
class RemoteBattleSession:
    def submit_cast(self, player_index: int, intent: CastIntent, now: float):
        self.client.send_cast(intent)
        return PendingCast(intent.sequence)
```

CV 不需要知道命令最终交给本地游戏还是远端服务器。

### 5.2 权威战斗引擎

目标接口：

```python
class BattleEngine:
    def submit(self, player_id: int, command, now: float) -> list[BattleEvent]: ...
    def step(self, dt: float, now: float) -> list[BattleEvent]: ...
    def snapshot(self, tick: int, now: float) -> BattleSnapshot: ...
    def reset(self, character_ids: tuple[str, str], now: float) -> list[BattleEvent]: ...
```

约束：

- 不读取摄像头、键盘、网络、音频或渲染模块；
- 不调用 `time.monotonic()`，所有时间由调用方注入；
- 权威规则不生成粒子；
- 不把 `sound_events`、`flash_messages` 或屏幕震动作为权威状态；
- 权威世界继续使用固定的 1280x720 逻辑坐标，客户端按窗口尺寸缩放；
- 弹体必须有稳定的 `projectile_id`，便于快照插值和事件关联；
- 对同一个连接的重复 `sequence` 必须幂等拒绝或忽略。

### 5.3 领域事件

建议的基础事件：

```text
CAST_ACCEPTED
CAST_REJECTED
PROJECTILE_SPAWNED
PROJECTILE_REMOVED
SPELL_CLASHED
PLAYER_HIT
SHIELD_HIT
HEAL_STARTED
HEAL_COMPLETED
STATUS_APPLIED
ROUND_ENDED
ROUND_RESET
```

事件包含 `event_id`、`server_tick`、`match_time` 和必要载荷。客户端使用事件触发音效和一次性特效，使用快照显示最终数值。

### 5.4 状态快照

快照只包含恢复战局所需的权威数据：

```python
@dataclass(frozen=True)
class BattleSnapshot:
    protocol_version: int
    match_id: str
    server_tick: int
    match_time: float
    players: tuple[PlayerSnapshot, PlayerSnapshot]
    projectiles: tuple[ProjectileSnapshot, ...]
    winner: int | None
```

状态持续时间应使用比赛相对时间，或在 DTO 中转为 `remaining_seconds`。不能把某台机器的 `time.monotonic()` 绝对值发送给另一台机器直接比较。

## 6. 服务端房间模型

### 6.1 房间状态机

```text
WAITING_FOR_PLAYER
  -> CHARACTER_SELECT
  -> READY_CHECK
  -> RUNNING
  -> ROUND_OVER
  -> REMATCH_READY / CLOSED
```

房间字段至少包括：

- `room_code`、`match_id`；
- 两个座位及其连接、角色和 ready 状态；
- 每个座位的重连令牌；
- `BattleSession`；
- 创建时间、最后活跃时间；
- 房间状态和协议版本。

### 6.2 连接和重连

- 创建房间后返回短房间码和不可猜测的重连令牌；
- 断线后保留座位 30-60 秒，具体时长配置化；
- 重连成功立即发送完整快照；
- 一名玩家断线时战局暂停，第一版比继续模拟更公平；
- 超时后结束房间并明确通知仍在线玩家。

### 6.3 基础安全

- 服务端根据 WebSocket 连接绑定的座位确定玩家身份；
- spell 必须在服务端允许列表内；
- sequence 必须单调递增；
- 每连接施法请求需要速率限制；
- 消息大小设置上限；
- 非法 JSON、未知消息类型和协议版本不匹配要返回明确错误并记录；
- 正式环境仅开放 443，通过 `wss://` 接入；
- 服务端日志不得包含摄像头内容、重连令牌全文或其他敏感数据。

## 7. 客户端运行模型

第一版不应把现有 OpenCV 主循环整体改写为 asyncio。建议网络客户端在独立线程或后台事件循环中运行，并通过线程安全队列与主循环通信：

```text
OpenCV/UI main thread
  - camera capture
  - CV classification
  - rendering
  - drain incoming queue
  - enqueue outgoing commands

Network worker
  - websocket connect/reconnect
  - heartbeat
  - send outgoing queue
  - decode into incoming queue
```

OpenCV、MediaPipe 和渲染继续留在主线程，网络线程禁止直接修改 `BattleGame` 或绘制画面。

### 7.1 远端渲染和插值

客户端保存最近两个服务器快照：

- HP、MP、护盾和状态可使用最新快照；
- 弹体位置按 `projectile_id` 在两个快照之间线性插值；
- 新生成或已销毁弹体由事件和快照共同校正；
- 本地手势识别后立即显示“识别到法术/等待服务器确认”，但不提前结算伤害；
- 收到 `CAST_REJECTED` 时展示服务器给出的原因。

第一版不做客户端权威预测。若实测公网延迟导致施法反馈迟钝，可只预测无规则影响的视觉前摇，不能预测伤害和命中。

## 8. 当前代码的迁移映射

| 当前职责 | 当前位置 | 迁移目标 |
| --- | --- | --- |
| CV 识别后直接施法 | `cv/controller.py` | 发布 `CastIntent` 给 session |
| 键盘直接施法 | `main.py` | 与 CV 共用 command/session 入口 |
| 法力、冷却、状态、弹体 | `game/battle.py` | `BattleEngine` 权威逻辑 |
| 粒子、音效、flash、震动 | `game/battle.py` | `BattlePresentation` 消费领域事件 |
| 本地双玩家模式 | `game/mode.py` | 保留并使用 `LocalBattleSession` |
| 远程模式 | 不存在 | `RemoteBattleSession` + `GameMode.REMOTE_DUEL` |
| NumPy 玩家/弹体对象 | `models/` | 保留内部结构，DTO 显式转为基础 JSON 类型 |
| 本地 `time.monotonic()` | `main.py`、`battle.py` | 客户端时钟与服务器比赛时钟分离 |

迁移时优先包裹现有 API。除非对应阶段的兼容测试已覆盖，否则不要一次性删除 `BattleGame.cast_spell()` 或移动整个目录。

## 9. 分阶段实施计划

### Phase 0：建立重构护栏

目标：确保后续每一步可验证、可回退。

- 确认 Git 仓库可用；当前工作目录中的 `.git` 未被识别为有效仓库，应先修复或建立新基线。
- 记录 `python -m compileall -q .` 与 374 测试通过基线。
- 增加联网架构决策文档，不改运行逻辑。
- 测试日志写入临时目录，避免运行测试污染 `logs/cv_sessions/`。

验收：工作树可追踪，现有测试全部通过，测试不新增运行日志。

### Phase 1：统一输入命令和本地 Session

目标：CV 与键盘不再了解 `BattleGame` 的具体调用方式。

- 新增 `CastIntent`；
- 新增 `BattleSession` Protocol/ABC；
- 新增 `LocalBattleSession`；
- CV 通过回调或 session 提交意图；
- 键盘走相同入口；
- Solo、PVE、本地 Duel 行为完全不变。

验收：现有测试全部通过；新增 CV/键盘命令等价测试；无网络依赖也能运行。

### Phase 2：提取权威 BattleEngine 和表现事件

目标：服务器可以在没有 OpenCV、Pygame 和渲染模块的环境中运行战斗。

- 从 `BattleGame` 提取纯规则；
- 所有时间依赖注入；
- 为弹体分配稳定 ID；
- 用 `BattleEvent` 替代权威逻辑中对粒子和音效的直接操作；
- `BattleGame` 暂时作为兼容外壳，内部组合 engine + presentation；
- 明确随机数只用于表现；角色随机选择由房间层决定。

验收：给定相同命令和时间序列，两次运行产生相同权威快照；现有玩法和测试不回归。

### Phase 3：协议和快照

目标：权威状态可以稳定跨进程传递。

- 实现 JSON 编解码和 schema/version 校验；
- 实现 Player/Projectile/BattleSnapshot；
- NumPy 数值转为 Python `float`/`int`；
- 增加命令、事件和快照 round-trip 测试；
- 增加未知字段兼容策略：忽略可选未知字段，拒绝缺少必填字段。

验收：协议测试覆盖合法、非法、重复和版本不匹配消息。

### Phase 4：本机权威服务端原型

目标：一个服务端进程和两个无摄像头测试客户端完成整局战斗。

- WebSocket 服务；
- 房间码创建/加入；
- 两人 ready；
- 30 Hz 服务器 tick；
- 快照广播和事件广播；
- 心跳、断线和房间清理；
- 集成测试启动随机端口服务，模拟两个客户端。

验收：两个测试客户端看到相同 HP、MP、弹体和 winner；重复施法 sequence 不会重复结算。

### Phase 5：接入真实客户端 Remote Duel

目标：两台同一局域网设备可用键盘和 CV 对战。

- 菜单新增 Remote Duel；
- 创建/加入房间 UI；
- 网络后台线程和队列；
- 本地角色只控制服务器分配的座位；
- 快照渲染、弹体插值、事件音效；
- 明确 CONNECTING、WAITING、READY、RUNNING、RECONNECTING、DISCONNECTED 状态。

验收：现有四种模式仍可用；两台机器连续完成多局对战，无双方状态分叉。

### Phase 6：阿里云部署

目标：公网通过 `wss://` 连接。

- 服务端 Dockerfile；
- `/health` 健康检查；
- 环境变量配置 host、port、tick、snapshot rate、日志级别和重连时限；
- Caddy/Nginx TLS 反向代理；
- 阿里云安全组仅开放 22（限制来源）和 443；
- 进程自动重启、日志轮转和基础监控；
- 客户端服务器地址可配置，不硬编码。

验收：不同网络下的两台设备可以使用房间码完成对战；服务重启和断网给出可理解错误。

### Phase 7：体验与鲁棒性优化

根据实测而不是猜测增加：

- RTT 和丢连接指标；
- 弹体插值缓冲；
- Protego 可配置的小幅输入宽限；
- 重连恢复；
- 协议压缩或 MessagePack，仅在 JSON 成为瓶颈时考虑；
- 房间容量、速率限制和资源上限。

## 10. 测试策略

### 10.1 必须保留的回归测试

- 当前 374 个测试持续通过；
- Solo、PVE、本地 Duel、CV Training 的公开行为不变；
- keyboard 与 CV 的施法结果仍遵循同一套规则。

### 10.2 新增测试层次

1. 领域单元测试：命令、冷却、碰撞、状态、确定性。
2. 协议测试：编码解码、版本、非法输入、幂等 sequence。
3. 房间测试：加入、座位、ready、断线、重连、超时。
4. 双客户端集成测试：真实 WebSocket、随机本地端口、整局一致性。
5. 慢网模拟：延迟、消息积压、短暂断线；第一版可在测试适配器中实现。
6. 手动验收：两台 Windows 设备分别用 finger/wand 完成多局。

测试不得依赖公网阿里云，也不得默认打开摄像头、音频设备或 GUI。

## 11. 可顺带完成的工程优化

在不扩大阶段范围的前提下，允许顺带完成：

- 消除测试运行时写入真实 `logs/` 的副作用；
- 统一注入 clock 和 random source，提高确定性；
- 将权威规则配置与客户端视觉配置分开；
- 为弹体、事件、房间和连接增加稳定 ID；
- 用结构化日志替代难以关联的 print；
- 增加配置校验和启动时的依赖/版本提示；
- 更新报告中的过时说明，例如测试文件数和角色资源状态。

不得借联网重构顺便大幅修改手势阈值、玩法数值、美术风格或音频系统。这些应作为独立任务，以免网络回归无法定位。

## 12. Vibe Coding 施工规则

每次工作只推进一个可独立验收的小目标：

1. 开始前阅读本设计和涉及模块的现有测试。
2. 先写或更新测试，再修改实现；纯机械迁移可同时完成。
3. 优先适配和组合，避免一次性移动大量文件。
4. 每次修改后至少运行相关测试；阶段结束运行完整 374+ 测试。
5. 不允许为了通过测试降低断言质量、跳过测试或吞掉异常。
6. 不允许客户端直接修改远端权威状态。
7. 不允许网络线程直接调用 OpenCV 绘制或修改主线程对象。
8. 不允许在协议里传 NumPy 对象、摄像头帧或 Python pickle。
9. 协议变化必须更新 `protocol_version`、协议测试和文档。
10. 遇到会改变玩法、公平性、部署成本或用户交互的选择时暂停并向用户确认。

## 13. 需要用户确认的决策点

以下事项不阻塞 Phase 0-4，但进入对应阶段前应确认：

1. 第一版是否只支持房间码邀请，不做公开匹配。建议：是。
2. 一名玩家断线时暂停还是继续。建议：暂停并保留 45 秒。
3. Remote Duel 是否允许 keyboard 与 CV 混用。建议：允许，服务器只关心合法 CastIntent。
4. 第一版是否需要注册登录。建议：不需要，使用临时玩家名和重连令牌。
5. 部署采用 Docker Compose + Caddy，还是现有运维偏好的 Nginx/systemd。建议：Docker Compose + Caddy。
6. 是否保留本地同屏 Duel。建议：永久保留，作为离线回归和演示模式。

## 14. 完成定义

本次远程对战重构完成，需要同时满足：

- 两台异地设备通过阿里云 `wss://` 服务和房间码进入同一战局；
- 双方看到一致的角色、HP、MP、状态、弹体、碰撞和胜负；
- 摄像头图像不离开客户端；
- 服务端不依赖 OpenCV、MediaPipe、Pygame 或显示设备；
- 断线、非法消息和版本不匹配都有明确处理；
- Solo、PVE、本地 Duel、CV Training 保持可用；
- 所有旧测试和新增网络测试通过；
- 提供本地启动、双客户端测试和阿里云部署文档。

