# Spells Battle 优化续跑 Goal

> 状态更新（2026-08-13）：用户已明确暂不继续部署。本文件保留为未来恢复部署与
> 双设备验收时的参考，不再作为当前代码修改任务；本地代码状态以
> `docs/next_optimization_progress.md` 为准。

下面代码块只适合未来恢复 Phase 6 部署时发布。它不能重做或篡改已经完成的 Phase
0–5，也不能把旧公网服务的通过记录当作新版本验收结果。

```text
在项目 C:\Users\15261\Desktop\magic_spale_refactor 中，继续完成
docs/next_optimization_plan.md 所定义的 Spells Battle 优化 Goal。

这是“续跑 Goal”，不是重新实施 Goal。开始操作前必须完整阅读并以当前工作树为准：

1. docs/next_optimization_plan.md（最高优先级设计与完成定义）
2. docs/next_optimization_progress.md（已完成工作和当前阻塞点）
3. docs/next_optimization_goal.md（原始完整 Goal 与架构边界）
4. deploy/README.md
5. docs/remote_duel_runbook.md
6. docs/project_status_and_roadmap.md
7. 当前 Git 状态、最近提交、相关源代码和测试

一、已经完成的事实

下列阶段已经落地，不得无理由重做、回滚或用平行实现替换：

- Phase 0–2：canonical corpus、Schema v2、分组评价、尺度归一化 Shadow、统一
  pipeline 和等价 DTW 加速；
- Phase 3–4：结构化模板结果、Stupefy 闭合门与 32-shift 循环 DTW、Schema v2
  代表模板包、严格评价与不晋升结论；
- Phase 5：每连接有界可靠 FIFO、battle_snapshot 最新值单槽、独立 sender task、
  发送超时与背压断开、Tick/发送解耦及健康指标。

关键提交至少包括：

- 338d79e feat: add cyclic Stupefy template shadow
- ff1c6e6 test: isolate cyclic templates by session fold
- ba7f02f docs: record cyclic Stupefy shadow evaluation
- e3160be refactor: decouple server ticks from websocket sends
- 0127913 docs: record server decoupling acceptance

循环 DTW 当前必须保持 Shadow：`CV_CYCLIC_STUPEFY_PRIMARY=False`。现有数据不足以
完成合法的 session-grouped 候选评价，且开发集重代入的循环候选 p95 约 49ms，超过
10ms 预算。不得降低门槛、不得把 k-medoids 描述成监督模型、不得因本 Goal 要收尾而
强行晋升算法。

二、尚未完成的真实目标

只完成 Phase 6 的剩余工作：

1. 审计当前仓库和阿里云公网服务状态；
2. 将包含 e3160be 发送解耦代码的服务端部署到 ECS `101.132.63.248`；
3. 确认实际运行的 systemd Python 服务使用新代码；
4. 验证公网 `/health` 返回新增 `metrics`；
5. 对新部署版本运行完整公网双 WebSocket 对战探针；
6. 指导并记录两台不同网络 Windows 设备的人工验收；
7. 完成最终回归、文档和交付审计。

已生成的候选部署包为（2026-09-06 从提交 51fdf5c 的已验证工作树重新生成；
旧的 e3160be / 74ab478 / 无提交号包已核实过时并删除）：

`C:\Users\15261\Desktop\spells-server-deploy-51fdf5c.tar.gz`

已记录 SHA256：

`5B7926C86595FA7E2AA1EB7AF0C980139E46D93263C650EC4A952D770A735EB4`

包内 46 个文件与仓库 51fdf5c 工作树逐字节一致，包含 Dockerfile、compose.yaml、
.env.example、requirements-server.txt、config.py、game/、models/、network/、
server/（无 __pycache__）。已验证解包后 `import server.app` 无 cv2/pygame 依赖、
compileall 通过，且包含本轮代码审查修复（handler internal_error 兜底、rematch
序列去重重置、日志异常堆栈）。

开始部署前必须重新计算哈希、检查包内至少包含 `server/app.py`、
`server/connection.py`、`server/config.py`、`network/`、`game/` 和
`requirements-server.txt`。若包与当前源码不一致，应从当前已验证工作树重新生成带
新提交号的包，不得继续使用来源不明的旧包。

三、部署安全与执行要求

- 先通过只读命令识别实际 systemd 服务名、WorkingDirectory、ExecStart、运行用户、
  Python 虚拟环境和当前文件布局；不得猜测服务名或目录；
- 部署前确认服务器当前没有进行中的房间，并保留可恢复的旧代码副本或版本目录；
- 不覆盖 `.env`、systemd unit、虚拟环境、日志或运行时秘密；
- 只替换服务端运行所需源码；不向服务器上传摄像头、CV 日志、原始轨迹或完整客户端
  资源；
- 上传、解压、切换版本和重启必须使用明确绝对路径；避免破坏性递归命令；
- 重启后检查 `systemctl status`、最近日志、本机 health 和公网 health；
- 如果新服务启动失败，收集日志并回滚到已保存的旧版本，不让公网服务长时间不可用；
- 不改域名、不引入 TLS、不改端口和现有公网 IP 路线；仍使用
  `ws://101.132.63.248:8765`；
- 不修改协议语义、玩法数值、客户端本地 CV 架构或 Shadow 晋升状态。

如果无法直接登录 ECS，不要停在泛泛说明。应根据用户返回的终端输出逐步给出一次只
包含一个阶段的准确命令，并持续推进：识别服务 → 备份 → 上传/解压 → 权限检查 →
重启 → health → 日志 → 公网探针。涉及密码时让 SSH/SCP 自行安全提示输入，不要求
用户在聊天中粘贴密码。

四、新版本公网自动验收

部署后必须取得以下直接证据：

1. `http://101.132.63.248:8765/health` 返回 `status=ok`；
2. 响应存在 `metrics`，至少包含 Tick duration/lag、可靠队列深度、快照合并、发送
   耗时、发送超时/失败和背压断开相关字段；没有 `metrics` 代表仍是旧版本；
3. 运行：

   `python tools/remote_duel_probe.py --url ws://101.132.63.248:8765 --timeout 20`

4. 完整探针必须验证两个真实 WebSocket 连接、建房、加入、ready、权威施法、完整
   一局、winner 和双方最终快照一致；不得只用 `--quick` 代替完整验收；
5. 探针后重新检查 health、systemd 状态和服务日志，确认无 sender task 异常、队列
   溢出、发送失败或服务重启循环；
6. 把日期、部署版本/提交、health 关键字段、探针结果和耗时写入
   docs/next_optimization_progress.md。

五、两台真实设备人工验收

自动探针通过后，为用户给出可复制的两端启动命令：

`$env:SPELLS_SERVER_URL = "ws://101.132.63.248:8765"`
`python main.py`

要求两台不同网络 Windows 设备依次验证并由用户明确反馈结果：

- A 创建六位房间码，B 使用 J 输入并加入；输入期间字母 hotkey 不得被触发；
- 双方选择角色、ready，角色/HP/MP/状态/弹体/碰撞/胜负保持一致；
- keyboard 对战至少一局；
- finger CV 和 bright-wand CV 至少各完成一局，允许分配到两端验证；
- keyboard 与 CV 混用正常；
- 一端主动断网后对局暂停，45 秒内恢复后能够重连继续；
- 非法房间码、版本不匹配和超过重连时限显示可理解错误；
- 连续完成至少三局 rematch；
- 服务器关闭或不可达时，Solo、PVE、本地 Duel 和 CV Training 仍可运行。

人工步骤不能由单元测试、模拟输入或自动探针冒充。用户没有明确反馈的条目必须写成
“待人工验收”，不能写成通过。若人工测试暴露范围内缺陷，应复现、修复、补自动测试、
重新跑本地和公网验证，再让用户复测受影响条目。

六、最终代码与文档审计

在准备宣称完成前，逐项检查 docs/next_optimization_plan.md 第 13 节完成定义，不得只
依据测试数量判断完成。至少执行：

`python -m compileall -q main.py cv game network server tools`
`python -m unittest discover -s tests -v`

还必须：

- 检查 Git 状态，保留用户改动，清除或忽略意外生成文件；
- 确认 `CV_CYCLIC_STUPEFY_PRIMARY=False`；
- 确认正式评价产物和 v2 模板包仍可读取；
- 确认固定评价的正式基线方法没有意外变化；
- 确认 `_tick_loop()` 中没有等待真实 `websocket.send()`；
- 确认可靠队列有界、快照槽最多一份、sender task 可清理；
- 更新 docs/next_optimization_progress.md、deploy/README.md、
  docs/remote_duel_runbook.md 和 docs/project_status_and_roadmap.md 中已经过时的状态；
- 文档必须分别列出：已自动验证、已公网验证、已人工验证、未通过/未执行；
- 记录最终修改摘要、提交、指标、测试结果、部署版本、风险和回退方式；
- 为最终文档形成清晰提交，例如
  `docs: record final optimization acceptance`。

七、完成与停止条件

只有下面全部具有直接证据时才可宣称 Goal 完成：

- Phase 0–5 的既有实现仍通过完整回归；
- 新发送解耦版本已经实际运行在 ECS，而不只是本地存在部署包；
- 新公网 health 含 `metrics`；
- 新版本完整公网探针通过；
- 两台不同网络真实设备的 keyboard、CV、重连和 rematch 清单得到用户明确确认；
- 文档与当前真实状态一致；
- 工作树没有意外改动或未说明产物。

在等待用户执行 SSH 命令或两台设备人工验收时，保持 Goal 未完成，清楚说明下一条可
执行命令和等待的证据。不得因为代码、单元测试或旧版本公网探针已经通过就提前结束。
```
