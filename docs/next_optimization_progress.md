# Spells Battle 下一阶段优化进度

实施依据：`docs/next_optimization_plan.md`

当前阶段：Phase 0 已完成，Phase 1 待开始

最近更新：2026-08-09

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

## 后续阶段

Phase 1 将实现 Schema v2、按 session/user/device 分组的数据划分、锁定评价语料、
完整错误接受率、margin、推理耗时 p50/p95 和分组报告。legacy 数据缺少可靠
user/device 元数据时必须明确拒绝对应泛化结论，不能伪造分组。
