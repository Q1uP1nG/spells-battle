# 手势分类器对比：提交版 vs Claude 版

## 两个项目的根目录

```
提交版（目标项目，codex 需要修改的）:
  D:\magic spale\magic spale\magic_spale_refactor\

Claude 版（营养来源，只读参考）:
  D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\
```

**下文中「Claude 版」指 Claude 版根目录下的文件，「提交版」指提交版根目录下的文件。**

---

## 一句话总结

提交版是**加权求和**融合（heuristic × 1.0 + DTW × 0.2），DTW 权重太低，基本是陪跑。
Claude 版是**决策树**融合（agree boost / strong heuristic trust / template rescue），DTW 有明确的救场角色。
Claude 版还有**离线 k-medoids 模板训练管线**，让 DTW 从真实数据学习，而不是永远用固定合成模板。

---

## 一、融合策略对比

### 提交版：`HybridTemplateGestureClassifier`（加权求和）

**所在文件：** `D:\magic spale\magic spale\magic_spale_refactor\cv\hybrid_classifier.py`

```
最终分数 = heuristic_score × 1.0 + template_score × 0.2
```

**问题：** template 权重只有 0.2，heuristic 权重 1.0。这意味着：
- heuristic 说 A（分数 0.80），DTW 说 B（分数 0.90）→ 最终 A = 0.80，B = 0.18，A 赢
- 只有 heuristic **完全放弃**（分数为 0）时，DTW 才能通过 `_allow_template_only` 门（需要 t_score ≥ 0.78 + gesture 有足够长度）救场
- DTW 几乎永远无法纠正 heuristic 的错误决策

### Claude 版：`FusedGestureClassifier`（决策树）

**所在文件：** `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\cv\gesture_pipeline.py`（约第 55-110 行，`FusedGestureClassifier` 类）

```
1. 两者一致（same spell） → confidence = max(h.conf, t.conf) + 0.08     ← 奖励一致性
2. heuristic 强 (≥0.85)    → 无条件信任 heuristic
3. heuristic 放弃 + DTW ≥ 0.80 → DTW 救场，confidence 上限 0.95        ← DTW 补位
4. heuristic 弱 (<0.85) + DTW 不同意 → 保留 heuristic（不冒险）          ← 保守策略
```

**优势：**
- 两者一致时额外 +0.08 confidence — 奖励"双保险确认"
- DTW 有明确的救场角色 — heuristic 放弃但 DTW 有信心的轨迹不会浪费
- 不做盲目的加权 — 每个决策分支有清晰的语义

---

## 二、DTW 模板对比

### 提交版：运行时加载原始轨迹

**所在文件：** `D:\magic spale\magic spale\magic_spale_refactor\cv\hybrid_classifier.py`（`HybridTemplateGestureClassifier.load_runtime_templates()` 方法）

```python
# 从 D:\magic spale\magic spale\magic_spale_refactor\logs\cv_sessions\*.jsonl 加载原始轨迹
# 选样本最多的那个 session 文件
# 每条轨迹就是一条模板（没有聚类、没有去噪）
# 用 0.35 作为全局接受距离（所有法术一样）
```

**问题：**
- 原始轨迹有噪声，每个用户画的不一样
- 全局阈值 0.35 对不同法术不公平（incendio 的分布和 stupefy 的分布不同）
- 依赖单个 session 文件，如果那个文件里样本少就退化
- 每次启动都要扫日志加载

### Claude 版：离线 k-medoids 聚类训练

**训练脚本：** `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\tools\train_gesture_templates.py`

**模板加载器：** `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\cv\template_classifier.py`（`DataTemplateClassifier` 类）

**输出产物：** `models/gesture_templates.json`（需在提交版根目录下生成）

```python
# 离线运行 train_gesture_templates.py
# 1. 挖掘 logs/cv_sessions/*.jsonl 中的标注轨迹
# 2. 对每个法术做 k-medoids 聚类（k=3），选代表样本
# 3. 计算每个法术的自适应阈值：
#    intra  = 类内距离 80 百分位
#    cross  = 到其他法术的类间距离 10 百分位
#    threshold = clamp((intra + cross)/2, intra*1.5, cross*0.9)
# 4. 输出 models/gesture_templates.json（静态文件，启动时一次加载）
```

**优势：**
- 聚类去噪 — 3 个代表样本比几十条原始轨迹更稳定
- 每个法术独立阈值 — 不是一刀切 0.35，而是根据数据分布自适应
- 训练一次，永久复用 — 不需要每次启动扫日志
- 支持双标签策略 — 显式标注 + 弱标注（heuristic 高置信度且施法成功的轨迹）

---

## 三、heuristic 分类器本身的差异

| 方面 | 提交版 | Claude 版 |
|------|--------|----------|
| 所在文件 | `cv\gesture_classifier.py` | `cv\gesture_classifier.py` |
| 选择策略 | `select_best_match` — 收集所有匹配，按 `score_gesture_match` 排序 | 优先级顺序 — 第一个匹配就返回（Lumos > Incendio > Glacius > Stupefy） |
| Stupefy 形状规则 | 闭合圆形 / loop | zigzag / 多转弯 |
| Zigzag 归属 | 已拆给 **Overload**，并对非 Overload 施加 zigzag 惩罚 | 仍归 Stupefy |

提交版的 `select_best_match` 确实比 Claude 版的简单优先级更精细，但这不影响融合策略层面的结论——精细化选择 + 低权重融合 = DTW 仍然陪跑。

---

## 四、实际效果差异（从数据看）

**提交版记录：** shadow DTW 的 agreement 比例很低（"heuristic 正解但 DTW 错误" 是主要的不一致来源）。因为 DTW 用固定合成模板，和真实用户的手势差距大。

**Claude 版的设计意图：** `FusedGestureClassifier` 的 rescue 分支就是为这种情况设计的——"我知道 DTW 经常和 heuristic 不一致，但只有在 heuristic 放弃时我才信 DTW"。这是一种务实的融合策略。

**但两版都缺关键一环：** 提交版有 shadow 但没有智能融合；Claude 版有智能融合和数据驱动模板，但 shadow 用的还是固定合成模板，没吃上训练管线的红利。

---

## 五、优越性总结

| Claude 版优于提交版的点 | 具体表现 |
|-------------------------|---------|
| **融合策略** | 决策树每个分支有明确语义，不像加权求和那样让 DTW 形同虚设 |
| **模板来源** | k-medoids 聚类去噪 vs 原始轨迹直接当模板 |
| **阈值调优** | 每个法术独立阈值 vs 全局 0.35 |
| **一致性奖励** | 两者说同一法术 +0.08 confidence |
| **DTW 救场** | heuristic 放弃时 DTW 可以补位（≥0.80） |
| **训练管线** | 跑一次训练生成静态 JSON，不需要每次启动扫日志 |

| 提交版保持优势的点 | 具体表现 |
|-------------------|---------|
| **heuristic 选择策略** | `select_best_match` 比简单优先级更精细 |
| **手势语义拆分** | Stupefy 改为 circle，Overload 接管 zigzag，避免两类动作互相抢判 |
| **shadow 记录能力** | 记录 agreement 用于诊断（这个要保留） |

---

## 六、吸收建议

不是直接覆盖，而是**取长补短**：

### 需要从 Claude 版复制的文件

| Claude 版路径 | 复制到提交版路径 | 用途 |
|:---|:---|:---|
| `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\tools\train_gesture_templates.py` | `D:\magic spale\magic spale\magic_spale_refactor\tools\train_gesture_templates.py` | 离线模板训练管线 |
| `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\tools\eval_classifiers.py` | `D:\magic spale\magic spale\magic_spale_refactor\tools\eval_classifiers.py` | 离线分类器 A/B 对比（可选） |

### 需要从 Claude 版提取代码并移植的部分

**来源文件（只读参考）：** `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\cv\template_classifier.py`

**目标文件（要修改的）：** `D:\magic spale\magic spale\magic_spale_refactor\cv\template_classifier.py`

提取内容：`DataTemplateClassifier` 类（加载 `models/gesture_templates.json`，DTW 匹配，返回 `ClassificationResult`）。该类的 `classify()` 方法：
1. 对输入轨迹做 `_normalize_trajectory`（resample 32 点 + 归一化）
2. 对每个法术的 prototype 做 DTW（包括 x 轴镜像）
3. 找到最小 DTW 距离
4. 用 per-spell 阈值判断置信度
5. 返回 spell / confidence / method="data_template"

**来源文件（只读参考）：** `D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\cv\gesture_pipeline.py`

**目标文件（要修改的）：** `D:\magic spale\magic spale\magic_spale_refactor\cv\gesture_pipeline.py`

提取内容：`FusedGestureClassifier` 类（决策树融合逻辑）。四个分支：
1. 两者 spell 相同 → confidence = max(h.conf, t.conf) + 0.08
2. h.conf ≥ 0.85 → 信 heuristic
3. h 无结果且 t.conf ≥ 0.80 → DTW 救场（confidence 上限 0.95）
4. h 有结果但弱 → 保留 heuristic

### 需要修改的提交版文件

**文件：** `D:\magic spale\magic spale\magic_spale_refactor\cv\gesture_pipeline.py`

`create_default_gesture_pipeline()` 函数改为：
```python
def create_default_gesture_pipeline():
    from cv.gesture_classifier import classify_cv_gesture as heuristic_func
    from cv.template_classifier import DataTemplateClassifier  # 新增导入
    heuristic = HeuristicGestureClassifier(heuristic_func)
    template = DataTemplateClassifier()                       # 代替原来的 Hybrid
    primary = FusedGestureClassifier(heuristic, template)     # 代替原来的 Hybrid
    shadow = ShadowTemplateClassifier()
    return GesturePipeline(primary=primary, shadow=shadow)
```

### 融合后架构

```
提交版 GesturePipeline
  ├── primary = FusedGestureClassifier                  ← Claude 的决策树（新）
  │     ├── heuristic = HeuristicGestureClassifier      ← 保留提交版的 select_best_match
  │     └── template = DataTemplateClassifier           ← Claude 的数据驱动模板（新）
  └── shadow = ShadowTemplateClassifier                 ← 保留提交版，固定合成模板，仅诊断
```

### 生成训练数据

在提交版根目录下运行：
```powershell
cd D:\magic spale\magic spale\magic_spale_refactor
python tools\train_gesture_templates.py
```
这会读取 `logs\cv_sessions\*.jsonl` 并输出 `models\gesture_templates.json`。

如果 `logs` 目录是空的（没有训练日志），可以先用 Claude 版已有的产物：
```
D:\magic spale\magic spale\zjjversion\magic_spale_refactor(1)\magic_spale_refactor\models\gesture_templates.json
```
直接复制到 `D:\magic spale\magic spale\magic_spale_refactor\models\gesture_templates.json`

---

## 七、工作量

| 步骤 | 说明 | 时间 |
|------|------|------|
| 1 | 把 `DataTemplateClassifier` 从 Claude 版移植到提交版 | 30 分钟 |
| 2 | 把 `FusedGestureClassifier` 从 Claude 版移植到提交版 | 45 分钟 |
| 3 | 复制 `tools\train_gesture_templates.py` | 5 分钟 |
| 4 | 复制 `models\gesture_templates.json`（或跑训练生成） | 5 分钟 |
| 5 | 修改 `create_default_gesture_pipeline()` 使用新架构 | 10 分钟 |
| 6 | 跑测试确认不回归 | 15 分钟 |
| **总计** | | **约 2 小时** |
