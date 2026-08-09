# Spells Battle 下一阶段优化 Goal

以下代码块可直接发布为 Codex Goal。实施依据为 `docs/next_optimization_plan.md`，不得使用聊天记录中的旧版本替代仓库文件。

```text
在项目 C:\Users\15261\Desktop\magic_spale_refactor 中，严格依据 docs/next_optimization_plan.md，实施 Spells Battle 下一阶段优化。

开始编码前必须完整阅读：

1. docs/next_optimization_plan.md
2. docs/project_status_and_roadmap.md
3. docs/cv_shadow_dtw_v2_plan.md
4. docs/remote_duel_refactor_architecture.md
5. 当前相关源代码与测试

其中 docs/next_optimization_plan.md 是本 Goal 的最高优先级实施依据。旧文档或旧聊天指令与其冲突时，以该文件为准。

当前策划案基线提交：2015501 docs: clarify template clustering scope

一、概念边界

本项目当前使用规则特征、非参数模板匹配、DTW 和 k-medoids 代表模板选择，不训练神经网络，也不把现有少量轨迹包装成监督学习模型。

必须统一使用以下含义：

- “评价语料”：用于算法前后比较和回归的真实轨迹；
- “代表模板选择”：k-medoids 从同类轨迹中选择代表样本；
- “模板包”：代表轨迹、距离阈值、来源与版本信息的序列化产物；
- “阈值校准”：在开发 fold 中观察距离分布并选择接受规则；
- “Shadow”：记录候选算法结果，但不改变正式施法。

不得将 k-medoids 描述成训练分类模型。不得声称现有 77 条有效轨迹能够证明跨用户或跨设备泛化。

二、总体目标

完成三个工作包：

1. 建立可复现的手势识别测量与回归体系；
2. 改进 Stupefy 圆形轨迹和 DTW 模板匹配；
3. 解耦服务器固定 Tick 与 WebSocket 网络发送。

三、架构硬约束

- MediaPipe、手势轨迹、魔杖跟踪和法术分类继续在客户端本地执行；
- 客户端只向服务器发送法术意图；
- 服务器继续权威处理房间、身份、魔力、冷却、序列号、弹道、碰撞和战斗结果；
- 不上传摄像头画面、MediaPipe 关键点或原始轨迹；
- 不实现反作弊；
- 不增加法术，不修改战斗数值、角色平衡或 PVE 难度；
- 不重做 UI、美术、音频或魔杖颜色检测；
- 不引入神经网络分类器；
- 新的尺度归一化和循环 DTW 必须先以 Shadow 运行；
- 评价不足或指标不达标时不得强行影响正式施法；
- 服务器发送队列必须有界，禁止无限队列；
- 服务器 Tick 不得等待真实 websocket.send() 完成；
- 可靠事件不得静默丢失；
- 旧 battle_snapshot 允许被更新快照覆盖；
- 保持旧日志、旧模板包、现有协议和部署方式兼容；
- 所有正式算法切换必须支持配置回退。

四、现有数据的使用规则

仓库当前约有：

- 178 个原始 CV JSONL 会话文件；
- 2869 条日志记录；
- 75 条带 intended_spell 的 Mode 4 标注记录；
- 模板 Bank 中 77 条有效轨迹；
- 86 条人工审核记录，其中 27 条 accepted、59 条 discarded；
- 27 条 accepted 审核记录已全部存在于模板 Bank。

这些数据只用于：

- 锁定当前 heuristic/template/fused 基线；
- 选择代表模板；
- 比较普通 DTW 与循环 DTW；
- 检查 Circle 起点敏感、margin 和混淆情况；
- 建立固定回归夹具。

不得把 Bank 和 reviewed accepted 简单拼接。必须先建立 canonical sample registry，并确保一条真实轨迹只出现一次。

去重优先级：

1. 显式 sample_id；
2. 规范化 source_file + source_attempt_id；
3. 来源、标签和归一化轨迹摘要生成的稳定 legacy ID。

gesture_templates.json 是生成的模板包，不是原始评价语料，不能反向加入样本集合。

现有 legacy 数据缺少可靠 user_id、device_id 和 palm_scale，只能用于当前样本上的回归比较。可以按 source_file 做会话分组，但不能据此声称跨用户或跨设备泛化。

五、实施阶段

Phase 0：基线与护栏

- 检查 Git 状态并保留用户已有修改；
- 运行完整测试并记录结果；
- 建立 canonical sample registry；
- 修复 Bank 与 reviewed accepted 重复计数；
- 兼容 reviewed 文件使用 label、旧日志使用 intended_spell 的差异；
- 对去重后的现有语料运行 heuristic、template、fused 基线；
- 输出包含 Git commit、分类器版本、模板包版本、语料版本和命令的基线报告；
- 增加测试锁定当前正式分类行为。

Phase 1：Schema v2 与评价体系

- 在兼容 v1 的前提下实现评价样本 Schema v2；
- 支持 sample_id、session_id、匿名 user_id、匿名 device_id、input_mode、分辨率、FPS、palm_scale、标签、审核状态和分类器版本；
- 不采集姓名、硬件序列号或摄像头图像；
- 支持 session_grouped_cv、user_grouped_cv、device_grouped_cv；
- legacy 数据默认采用按会话分组的交叉验证；
- 允许保留少量锁定评价语料；
- 不得根据锁定评价结果反复调阈值；
- 派生轨迹必须和原轨迹处于同一 fold，不能当作独立样本扩大数量；
- 输出 Accuracy、Macro Precision/Recall/F1、每法术指标、拒识率、错误接受率、混淆矩阵、Top-1/Top-2 margin 和推理耗时 p50/p95；
- 输出 manifest.json、metrics.json、report.md、confusion_matrix.csv 和 misses.jsonl；
- 数据不足时明确写出“只适合回归比较，不足以证明泛化”。

Phase 2：尺度归一化 Shadow 与分类接口统一

- 在不改变正式施法结果的前提下增加尺度归一化候选特征；
- 距离和跨度优先按 palm_scale 归一化；
- 缺少 palm_scale 的 legacy 轨迹使用明确标记的 fallback；
- 时间特征使用真实时间戳或 FPS；
- 保留方向语义，不对所有法术做旋转不变处理；
- Baseline 与 Normalized Shadow 同时运行；
- 预览和最终识别共享同一 pipeline 接口与模板包版本；
- 预览可以降低计算频率或缓存，但不得继续显示 heuristic、最终却使用另一个分类器判定；
- Shadow 阶段不得改变正式施法。

Phase 3：Stupefy 循环 DTW

- 将模板分类结果结构化，至少包含 spell、confidence、best_distance、second_spell、second_distance、margin、ambiguous、matched_prototype_id 和 algorithm_version；
- 融合层不得从 reason 字符串反解析算法数据；
- 实现闭合轨迹门；
- 只有满足闭合条件的 Stupefy 才能使用循环 DTW；
- 对 32 点 Stupefy 模板检查全部循环位移并选择最小距离；
- 返回最佳 shift；
- 顺时针/逆时针策略必须由显式配置控制；
- Incendio、Glacius、Lumos 和 Overload 不得无条件使用循环 DTW；
- 增加 Top-1/Top-2 margin 和 ambiguous 拒绝；
- k-medoids 只选择代表模板，不训练参数分类器；
- 模板包记录 schema、prototype ID、来源、构建命令和 Git commit；
- 阈值只在开发 fold 中校准；
- 锁定评价语料不能用于选择 k、距离阈值或 margin；
- 增加距离缓存，避免聚类、校准和报告重复计算同一 DTW。

Phase 4：数据评价与按法术启用

循环 DTW 只有同时满足以下条件才允许影响正式 Stupefy 判定：

- 锁定评价或分组交叉验证中的 Stupefy Recall 至少提高 5 个百分点，或者错误接受数量至少下降 20%；
- 整体 Macro-F1 下降不超过 1 个百分点；
- 其他任一法术 Recall 下降不超过 2 个百分点；
- 最终分类推理 p95 满足实时预算，目标低于 10ms；
- 数据至少来自多个录制会话；
- 自动测试、日志回放和人工冒烟通过。

如果样本不足或指标不达标：

- 保留 Shadow 实现和报告；
- 明确记录未启用原因；
- 不降低门槛、不伪造数据；
- 继续完成服务器工作包，不将数据不足当作整个 Goal 的阻塞。

Phase 5：服务器 Tick 与发送解耦

- 为每个连接实现有界可靠 FIFO、最新快照单槽位、唤醒机制、独立 sender task、关闭状态和发送统计；
- room_created、room_joined、room_state、battle_event、error、pong 和控制消息属于可靠有序消息；
- battle_snapshot 属于可合并状态消息；
- 新快照覆盖尚未发送的旧快照，最多积压一份；
- 可靠消息保持顺序且不得静默丢失；
- sender 每处理有限数量可靠消息后检查快照，避免快照永久饥饿；
- WebSocket 发送必须有超时；
- 可靠队列满或连续超时时记录原因并断开慢连接；
- 慢连接断开后沿用现有暂停和重连流程；
- 慢连接不得影响其他房间；
- 关闭连接和停服时正确取消 sender task；
- BattleServer._tick_loop() 只能推进战斗、生成消息、投递内存队列和记录 Tick 延迟；
- Tick 中不得等待真实网络发送；
- 增加 tick_duration_ms、tick_lag_ms、队列深度、快照合并数、发送耗时、超时、失败和背压断开统计；
- 日志不得输出 reconnect_token、摄像头信息或轨迹内容。

Phase 6：整体验收与文档

- 运行完整自动化测试和 compileall；
- 运行固定评价语料并保存报告；
- 完成本地双客户端联机测试；
- 模拟慢客户端验证 Tick 不被阻塞；
- 验证快照最多积压一份；
- 验证可靠事件顺序、队列溢出、发送异常和 sender task 清理；
- 验证一个房间的慢连接不影响另一个房间；
- 验证断线暂停和重连兼容；
- 保持阿里云公网 IP 部署方式可用；
- 持续更新 docs/next_optimization_progress.md；
- 更新运行手册和项目状态；
- 真实公网双设备验收需要用户操作时，提供精确命令，不得伪称已完成。

六、测试要求

至少覆盖：

- v1/v2 日志兼容；
- canonical sample 去重和冲突报告；
- reviewed label 与 intended_spell 兼容；
- 分组 fold 无 sample_id、session 或用户泄漏；
- 模板选择和阈值校准不读取锁定评价语料；
- 不同分辨率下归一化特征近似一致；
- 圆形不同起点得到接近的循环 DTW 距离；
- 派生圆形与原始轨迹处于同一 fold；
- 方向型法术不使用循环 DTW；
- 顺/逆时针配置；
- Top-2 margin 和 ambiguous；
- 预览与最终识别使用同一 pipeline 与模板包版本；
- 固定小型评价语料指标回归；
- 慢 send() 不阻塞 Tick；
- 快照覆盖；
- 可靠队列顺序和溢出；
- sender task 生命周期；
- WebSocket 发送异常；
- 多房间慢连接隔离；
- 现有断线暂停和重连。

最终必须运行：

python -m unittest discover -s tests -v
python -m compileall -q main.py cv game network server tools

七、工作方式

- 先检查现有实现，不重复已有日志、回放、k-medoids 和评价能力；
- 优先扩展现有模块，不创建功能重复的平行实现；
- 保留用户已有修改；
- 每个 Phase 保持独立、清晰的提交；
- 发现范围内明确缺陷时直接修复并补测试；
- 普通实现细节自行作出合理决定；
- 涉及范围扩大、协议不兼容或用户数据迁移风险时再请求确认；
- 不以代码写完或测试数量增加作为完成标准。

八、每阶段交付内容

每个 Phase 完成后报告：

1. 完成内容；
2. 修改文件；
3. 架构影响；
4. 评价语料、Schema 和模板包版本；
5. 指标或服务器压力测试结果；
6. 测试命令和结果；
7. 是否达到正式启用门槛；
8. 剩余风险；
9. 回退方式；
10. 下一阶段计划。

九、完成条件

只有满足 docs/next_optimization_plan.md 的完成定义以及以下条件，才能宣称 Goal 完成：

- 可复现评价和回归体系已经落地；
- 现有样本被正确去重，没有把审核记录重复加入 Bank；
- 没有把少量轨迹包装成监督学习模型；
- 圆形循环 DTW 有自动测试和真实轨迹对照；
- 未达到门槛的算法保持 Shadow；
- 服务器 Tick 不等待真实 WebSocket 发送；
- 慢连接不会造成无限积压或拖慢其他房间；
- 完整测试通过；
- 工作区无意外生成文件；
- 文档记录指标、验收、风险和回退；
- 需要用户完成的公网验收明确列为待验收，不能虚假标记完成。
```
