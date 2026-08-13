# Spells Battle 下一阶段优化进度

实施依据：`docs/next_optimization_plan.md`

当前阶段：本地代码优化与自动验证已完成；部署和双设备人工验收按用户要求延期

最近更新：2026-08-13

## 概念边界

本阶段没有训练神经网络或监督学习分类模型。当前系统由规则特征、非参数
DTW 模板匹配、融合规则和 k-medoids 代表模板选择组成。现有轨迹用于回归
比较、代表模板选择和阈值观察，不能证明跨用户或跨设备泛化。

## Phase 0：基线与护栏

### 完成内容

- 新增 canonical sample registry，统一读取模板 Bank、人工审核日志和旧会话日志；
- 身份合并优先使用 `sample_id`，其次使用规范化来源与 attempt，最后才使用轨迹摘要；
- 修复 Bank 与 reviewed accepted 被重复计权的问题；
- 同一真实轨迹的跨视图副本会合并，同一来源中的独立录制不会仅因轨迹相同而误合并；
- 最后一次人工审核生效，discarded/skipped 样本不会进入 canonical 语料；
- 兼容审核日志的 `label` 和旧日志的 `intended_spell`；
- 模板包构建器改为读取 canonical 语料，并统一使用“代表模板选择/模板包”术语；
- 评价器可输出 manifest、metrics、Markdown 报告、混淆矩阵和逐条错误记录；
- 评价器缓存成对 DTW 距离，同一评价运行中每对轨迹最多计算一次；
- manifest 记录 Git commit、分类器版本、模板包版本与哈希、语料版本与命令；
- 基线报告明确标注同源重代入、未按会话分组和 legacy 元数据缺失限制。

### Canonical 语料审计

输入文件：

- `models/gesture_template_bank.json`
- `models/gesture_reviewed_samples.jsonl`

审计结果：

- 输入候选视图：104；
- canonical 真实轨迹：77；
- 合并重复视图：27；
- 最新人工审核：86，其中 accepted 27、discarded 59；
- 标签冲突：0；
- 缺失可靠来源字段：11；
- 类别分布：Incendio 28、Circle 11、Glacius 12、Lumos 14、Overload 12。

语料版本记录在基线 `manifest.json` 中，由 canonical sample ID、标签和轨迹摘要
生成稳定 SHA-256。重复运行的单元测试验证该版本值稳定。

### Phase 0 基线

运行命令：

```powershell
python tools/evaluate_gesture_templates.py `
  --bank models/gesture_template_bank.json `
  --reviewed models/gesture_reviewed_samples.jsonl `
  --output-dir artifacts/cv_evaluation/phase0_baseline_31958d2
```

主要结果：

| 方法 | 正确数 | Accuracy | Macro-F1 | 解释限制 |
| --- | ---: | ---: | ---: | --- |
| logged primary | 43/77 | 55.8% | 71.0% | 历史运行时记录，不等同于当前代码 |
| current heuristic | 45/77 | 58.4% | 73.3% | 当前规则基线 |
| logged shadow | 16/19 | 84.2% | 52.4% | 只有 19 条带历史 shadow 结果 |
| sample leave-one-out DTW | 70/77 | 90.9% | 89.8% | 未按 session 隔离，不能证明泛化 |
| current template pack | 75/77 | 97.4% | 97.7% | 模板包来自同一 Bank，是重代入结果 |
| current fused | 73/77 | 94.8% | 95.0% | 正式融合行为的当前样本回归基线 |

特别关注：

- 当前 heuristic 的 Circle Recall 为 7/11（63.6%）；
- 当前 fused 的 Circle Recall 为 9/11（81.8%）；
- 样本留一 DTW 的 Circle Recall 为 11/11，但尚未做 session-grouped 评价；
- Circle 只有 11 条真实轨迹，足以验证循环位移算法，不足以声称泛化；
- 样本留一 DTW 的 Overload Recall 只有 7/12（58.3%），说明循环/旋转不变不能无条件扩展到方向型法术。

基线产物：

- `artifacts/cv_evaluation/phase0_baseline_31958d2/manifest.json`
- `artifacts/cv_evaluation/phase0_baseline_31958d2/metrics.json`
- `artifacts/cv_evaluation/phase0_baseline_31958d2/report.md`
- `artifacts/cv_evaluation/phase0_baseline_31958d2/confusion_matrix.csv`
- 本地另有 `misses.jsonl`；该逐条大文件默认不提交，可由上述命令重建。

### 测试证据

修改前完整基线：451 tests passed。

Phase 0 修改后：

```text
python -m compileall -q main.py cv game network server tools
python -m unittest discover -s tests -v
Ran 460 tests in 19.497s
OK
```

相关专项测试共 30 项通过，覆盖 canonical 去重、最后审核覆盖、标签兼容、
同来源独立录制、评价产物和 DTW 缓存。

### 架构影响与回退

- 正式游戏分类和战斗逻辑没有切换；本阶段只改离线语料、模板包构建和评价工具；
- 旧命令行单 JSONL 评价入口继续兼容；
- 回退时可恢复旧的两个工具文件并删除 `tools/gesture_corpus.py`；现有模板包未被重写；
- 当前没有任何候选算法晋升，Shadow/正式边界保持不变。

## Phase 1：Schema v2 与评价体系

### 完成内容

- 新采集日志使用 Schema v2，并为 session 和 sample 生成稳定 ID；
- 支持匿名 `user_id`、匿名 `device_id`、`input_mode`、分辨率、估计 FPS、
  `palm_scale`、评价分区、审核状态和分类器版本；
- 匿名 user/device 标签只能由 `SPELLS_CV_USER_ID` 和 `SPELLS_CV_DEVICE_ID`
  显式提供，不读取姓名、硬件序列号、摄像头图像或其他设备身份；
- Mode 4 Bank、人工审核和代表模板包重建流程保留 Schema v2 元数据；
- 旧 v1 日志继续兼容，缺失字段保持缺失或使用明确的 legacy 标记；
- 评价器支持 sample leave-one-out、session/user/device grouped CV，并拒绝在
  元数据不足或分组数不足时伪造 user/device grouped 结果；
- 派生样本沿用原样本的 group/fold，防止数据泄漏；
- `development` 与 `locked` 分区隔离，代表模板选择和阈值观察不能读取
  locked 样本；当前语料尚无 locked 样本，因此不能完成独立锁定评价；
- 输出 Accuracy、Macro Precision/Recall/F1、每法术指标、拒识率、错误接受率、
  混淆矩阵、Top-1/Top-2 margin、分类耗时 p50/p95 和输入来源分解；
- manifest 增加确定性指标指纹，耗时抖动不影响回归指标版本。

### Session-grouped 评价

运行命令：

```powershell
python tools/evaluate_gesture_templates.py `
  --bank models/gesture_template_bank.json `
  --reviewed models/gesture_reviewed_samples.jsonl `
  --split-mode session_grouped_cv `
  --folds 5 `
  --partition development `
  --baseline-metrics artifacts/cv_evaluation/phase0_baseline_31958d2/metrics.json `
  --output-dir artifacts/cv_evaluation/phase1_session_grouped_b35783b
```

语料仍为 77 条 canonical 轨迹，只能形成 8 个 session group，其中 11 条缺失
可靠来源并统一归入 `legacy` group。五折测试集大小为 27、19、11、10、10；
各 session 的类别分布高度不平衡。当前没有可靠 user/device 元数据，因此不能
运行或宣称 user/device grouped 泛化结果。

主要结果：

| 方法 | Accuracy | Macro-F1 | 拒识率 | 错误接受率 | p95 | 解释限制 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| current heuristic | 58.4% | 73.3% | 33.8% | 7.8% | 0.28ms | 当前规则基线 |
| current template pack | 97.4% | 97.7% | 0.0% | 2.6% | 465.81ms | 同源 Bank 重代入，不是泛化结果 |
| current fused | 94.8% | 95.0% | 1.3% | 3.9% | 503.86ms | 同源 Bank 回归，且远超 10ms 目标 |
| session-grouped representative templates | 53.2% | 53.1% | 0.0% | 46.8% | 未采集 | 训练 fold 选代表模板、隔离 session 测试 |

session-grouped 结果按法术为：Glacius 12/12、Incendio 10/28、Lumos 13/14、
Overload 3/12、Stupefy（语料内部旧标签 `circle`）3/11。Stupefy Recall 只有
27.3%，说明现有普通 DTW 对录制会话和圆形起点非常敏感；也证明 Phase 0 的
留一和模板包重代入高分不能代表跨会话效果。

正式产物：

- `artifacts/cv_evaluation/phase1_session_grouped_b35783b/manifest.json`
- `artifacts/cv_evaluation/phase1_session_grouped_b35783b/metrics.json`
- `artifacts/cv_evaluation/phase1_session_grouped_b35783b/report.md`
- `artifacts/cv_evaluation/phase1_session_grouped_b35783b/confusion_matrix.csv`
- `misses.jsonl` 可由命令重建，默认不提交。

### 测试、晋升与回退

Phase 1 完整测试证据：

```text
python -m compileall -q main.py cv game network server tools
python -m unittest discover -s tests -v
Ran 474 tests in 21.237s
OK
```

覆盖 v1/v2 兼容、稳定 ID、匿名标签、元数据保存、分组 fold 无泄漏、派生样本
同 fold、locked 分区隔离、确定性指标和报告限制说明。

- 正式识别算法没有切换；本阶段仅增加日志 Schema 和离线评价能力；
- 当前没有 locked 语料，且 session-grouped 指标很低，因此任何新识别方法都未
  达到正式启用门槛；
- 回退时可继续读取 v1 日志，并关闭匿名环境标签；旧模板包和正式分类路径不受影响。

## Phase 2：尺度归一化 Shadow 与统一 pipeline

### 完成内容

- pipeline 版本升级为 `gesture-pipeline-v2-normalized-shadow`；
- 新增 `GestureClassificationContext`，预览、最终分类和离线回放共享
  `palm_scale`、分辨率、FPS、输入模式和用途字段；
- 新增 `normalized-heuristic-shadow-v1`，只产生诊断结果，不改变 primary 或施法；
- 尺度优先使用 `palm_scale`；缺失时依次使用画面对角线和轨迹跨度 fallback；
- fallback 来源、缩放系数、基于实际 FPS 的时长和归一化速度写入 Shadow 日志；
- 归一化只做正比例缩放，不平移方向含义、不旋转轨迹；
- 预览和停止后的最终判定统一调用同一个 pipeline 对象和版本，预览不再绕过
  pipeline 直接调用裸 heuristic；
- `CVTrack` 记录最后 pipeline 版本和 Shadow 候选，Schema v2 日志记录 primary、
  normalized Shadow、agreement 和 pipeline 版本；
- Mode 4 Bank 与审核链保留 pipeline 版本，但仍不会把 Shadow 预测当成人工标签；
- DTW 动态规划改为按反对角线和 prototype batch 精确向量化；随机轨迹测试逐格
  对照旧 recurrence，距离和正式分类结果保持一致。

### Phase 2 评价

实现提交：`ce7d7aa feat: evaluate normalized gesture features in shadow mode`

运行命令：

```powershell
python tools/evaluate_gesture_templates.py `
  --bank models/gesture_template_bank.json `
  --reviewed models/gesture_reviewed_samples.jsonl `
  --split-mode session_grouped_cv `
  --folds 5 `
  --partition development `
  --baseline-metrics artifacts/cv_evaluation/phase1_session_grouped_b35783b/metrics.json `
  --output-dir artifacts/cv_evaluation/phase2_normalized_shadow_ce7d7aa
```

主要结果：

| 方法 | Accuracy | Macro-F1 | 拒识率 | 错误接受率 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| current heuristic | 58.4% | 73.3% | 33.8% | 7.8% | 0.44ms |
| normalized heuristic Shadow | 61.0% | 75.8% | 32.5% | 6.5% | 0.63ms |
| current template pack | 97.4% | 97.7% | 0.0% | 2.6% | 10.68ms |
| current fused | 94.8% | 95.0% | 1.3% | 3.9% | 12.08ms |
| session-grouped representative templates | 53.2% | 53.1% | 0.0% | 46.8% | 未采集 |

与 Phase 1 对比，current heuristic、template、fused 和 grouped template 的 Accuracy、
Macro-F1、拒识率、错误接受率全部零变化。DTW 等价加速使 template p95 从
465.81ms 降到 10.68ms，fused p95 从 503.86ms 降到 12.08ms；提升明显，但
最终 fused 仍未达到 `<10ms` 的晋升目标。

normalized Shadow 在当前样本上多正确 2 条，但其 Stupefy Recall 仍为 7/11
（63.6%，与 baseline 相同），Overload Recall 从 12/12 降到 11/12。更重要的是，
77 条 legacy 轨迹全部缺少 palm scale 和分辨率，只能使用
`trajectory_span_fallback`。因此该结果只能说明 fallback 回归表现，不能证明
palm-scale 归一化的跨距离、跨分辨率或跨设备效果。

正式产物：

- `artifacts/cv_evaluation/phase2_normalized_shadow_ce7d7aa/manifest.json`
- `artifacts/cv_evaluation/phase2_normalized_shadow_ce7d7aa/metrics.json`
- `artifacts/cv_evaluation/phase2_normalized_shadow_ce7d7aa/report.md`
- `artifacts/cv_evaluation/phase2_normalized_shadow_ce7d7aa/confusion_matrix.csv`
- `misses.jsonl` 可由命令重建，默认不提交。

### 测试、晋升与回退

```text
python -m compileall -q main.py cv game network server tools
python -m unittest discover -s tests -v
Ran 481 tests in 12.405s
OK
```

- 测试覆盖不同分辨率/手掌尺度等价、fallback 标记、方向保持、FPS 时长、
  Shadow 不影响 primary、预览/最终 pipeline 版本一致、日志元数据和批量 DTW
  与旧 recurrence 等价；
- normalized Shadow 未达到按法术晋升条件，继续保持 Shadow；
- 回退可将 pipeline 版本切回 v1、恢复预览 heuristic 入口和旧 DTW；模板包、
  日志 Schema、协议和战斗逻辑均未发生不兼容变更。

## Phase 3：循环 DTW 与 Schema v2 代表模板包

- DTW 结果新增 Top-1/Top-2、独立距离、归一化 margin、ambiguous、prototype ID、
  algorithm version、最佳循环 shift 和 cyclic-used 标记；
- 仅对通过闭合门的 Stupefy 运行 32 个起点位移；反向序列默认关闭且写入 manifest；
- Incendio、Glacius、Lumos、Overload 继续使用普通方向型 DTW；
- `models/gesture_templates_shadow_v2.json` 由 k-medoids 选择可追踪 medoid，包含来源
  sample/session、每法术阈值、margin 阈值、聚类摘要和 outlier；这不是监督模型；
- runtime 同时记录正式结果与循环 Shadow；`CV_CYCLIC_STUPEFY_PRIMARY=False`，正式
  施法、旧模板包、服务器协议和战斗逻辑均未改变。

实现提交：

- `338d79e feat: add cyclic Stupefy template shadow`
- `ff1c6e6 test: isolate cyclic templates by session fold`

## Phase 4：评价与晋升结论

正式产物：

- `artifacts/cv_evaluation/phase4_grouped_cyclic_shadow_ff1c6e6/manifest.json`
- `artifacts/cv_evaluation/phase4_grouped_cyclic_shadow_ff1c6e6/metrics.json`
- `artifacts/cv_evaluation/phase4_grouped_cyclic_shadow_ff1c6e6/report.md`
- `artifacts/cv_evaluation/phase4_grouped_cyclic_shadow_ff1c6e6/confusion_matrix.csv`

开发集重代入结果仅作诊断：循环候选 Stupefy Recall 为 9/11（81.8%），Macro-F1
95.7%，错误接受率 2.6%，但 p95 为 49.22ms，超过 `<10ms` 预算。它不能作为晋升
证据，因为 v2 模板包来自同一批开发轨迹。

严格 session-grouped 评价会在每个训练 fold 内重新选择 medoid 和校准阈值，禁止
测试 session 进入模板包。结果为明确的 `unavailable`：11 条 Stupefy 轨迹集中在
少数 session，fold 3 的训练侧不足 3 条，无法覆盖全部测试样本。当前也没有 locked、
独立 user 或独立 device 语料。因此 Phase 4 的正确结论是：

- 不晋升循环候选，保持 Shadow 与 `CV_CYCLIC_STUPEFY_PRIMARY=False`；
- 不根据重代入高分继续调参；
- 需要补采分散到多个独立 session 的 Stupefy 轨迹后重新评价；
- 即便数据门槛满足，仍需把最终分类 p95 优化到 10ms 内并通过人工冒烟。

完整回归：`python -m unittest discover -s tests -q`，492 tests，OK；compileall 通过。

## Phase 5：服务器 Tick 与 WebSocket 发送解耦

实现提交：`e3160be refactor: decouple server ticks from websocket sends`

- 每连接使用有界可靠 FIFO、`battle_snapshot` 最新值单槽、wakeup event 和独立 sender task；
- 可靠消息保持 FIFO 顺序；sender 每发送最多 8 条可靠消息便检查一次快照，避免快照饥饿；
- 新快照覆盖尚未发送的旧快照并累计 `coalesced_snapshot_count`，快照积压不超过 1；
- `_tick_loop()` 只同步入队，不再等待任何真实 `websocket.send()`；
- 发送超时、发送异常或可靠队列满会明确关闭该连接，不静默丢弃可靠事件；
- 默认可靠队列上限从 64 调整为 256，并增加 5 秒发送超时与 reliable burst 环境配置；
- `/health` 新增 Tick p50/p95、Tick lag、队列深度、快照合并、发送耗时、超时、失败和
  背压断开指标；日志不包含重连 token、摄像头或轨迹数据。

异步测试覆盖可靠顺序、快照覆盖、队列溢出、发送超时、sender 取消、两个房间隔离，
以及 100Hz 测试 Tick 面对永久阻塞 `send()` 仍能推进。服务器集成、房间、重连、部署
配置和双 WebSocket 探针回归均通过。

完整回归：

```text
python -m compileall -q main.py cv game network server tools
python -m unittest discover -s tests -q
Ran 497 tests in 13.776s
OK
```

## 本地代码收尾（2026-08-13）

用户明确要求当前只完成代码修改，暂不操作 ECS 部署。对 Phase 0–5 做完成度复审后，
补充提交：

- `fd1cada fix: retain server sender failure metrics`
- `cd63c9a fix: make sender backpressure terminal`

修复内容：

- 已断开连接的快照合并数、发送耗时、超时、失败和背压断开数现在汇总到服务器生命周期
  累计值，不会因连接从活动表移除而从 `/health.metrics` 消失；
- 可靠队列溢出会立即把 sender 标为 closing，后续投递统一拒绝，避免关闭任务执行前继续
  接受消息并重复累计背压断开；
- 发送超时不重试同一可靠帧，因为超时发生时无法证明对端未收到消息；服务端明确断开，
  由现有重连与权威快照恢复状态，避免重复事件；
- 新增真实服务器停机测试，验证两个活动 WebSocket 的 sender 和 close task 均被清理；
- 新增发送异常、历史指标保留和终止性背压测试。

最终本地回归：

```text
python -m compileall -q main.py cv game network server tools
python -m unittest discover -s tests -q
Ran 500 tests in 10.205s
OK
```

固定 77 条 canonical 轨迹重新评价相对 Phase 4 的所有确定性指标均为零变化：current
heuristic 45/77、normalized Shadow 47/77、data template 75/77、fused 73/77、
session-grouped representative template 41/77。严格 grouped cyclic 仍因 fold 3 的
Stupefy 训练样本不足而 `unavailable`；循环候选继续保持 Shadow，配置仍为
`CV_CYCLIC_STUPEFY_PRIMARY=False`。本机本轮循环候选 p95 为 25.21ms，仍高于
`<10ms` 晋升预算。

## 延期的部署与人工验收（不属于当前代码修改）

2026-08-10 对 `ws://101.132.63.248:8765` 运行完整公网探针：健康检查、两个真实
WebSocket、建房/加入、ready、权威施法、完整一局、胜者和最终快照一致性全部通过，
耗时 10.069 秒。

2026-08-13 复查公网 `/health` 仍只返回 `status/rooms/connections`，没有本地新版本的
`metrics`，可判定 ECS 当前仍运行旧代码。用户已明确暂不部署，因此以下事项延期，
不应阻塞“本地代码已完成”的结论，也不得被描述为已经通过：

1. 将 `cd63c9a` 或后续交付提交部署到 ECS 的 systemd Python 服务；
2. 再跑完整公网探针，并确认 `/health.metrics` 存在；
3. 两台不同网络 Windows 设备人工完成 keyboard、finger/bright-wand CV、断线重连和
   至少三局 rematch；
4. 人工验收完成前，不以自动探针替代真实设备结论。
