# Spells Battle 下一阶段优化进度

实施依据：`docs/next_optimization_plan.md`

当前阶段：Phase 0、Phase 1 已完成，Phase 2 待开始

最近更新：2026-08-10

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

## 后续阶段

Phase 2 将在不改变正式施法结果的前提下运行尺度归一化 Shadow，并统一预览与
最终识别 pipeline。重点是先给缺少 `palm_scale` 的 legacy 数据建立明确 fallback，
复用同一分类入口和版本信息，同时避免让当前约 500ms 的模板路径进入逐帧预览。
