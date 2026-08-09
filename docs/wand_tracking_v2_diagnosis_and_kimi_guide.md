# Bright Wand Tracking v2 诊断报告与 KIMI CODE 实施指南

## 目标

本文件用于指导 KIMI CODE 在当前代码基础上继续优化 bright marker wand tracking。重点解决：

- 蓝色贴片肉眼可见，但系统长时间 `NO WAND`，形成隐性 CD。
- 快速折返时黄色追踪点滞后、漂移、和真实笔尖脱节。
- 起手动作被漏掉，导致轨迹过短或分类依据错误。

本轮不要重写分类器，不要改 PVE 难度，不要恢复 plain wand，不要引入深度学习模型。

## 改动成本评估

这不是三五行小修，属于中等规模 CV 稳定化。

预计会涉及：

- `cv/wand_detector.py`：主要修改。增加多候选、动态 relock、动态 jump gate、debug 字段。
- `cv/wand_tracking.py`：新增轻量 helper，例如候选历史、动态 jump 计算、可选 patch reacquire。
- `models/cv_track.py`：增加少量 wand tracking 状态字段。
- `cv/controller.py`：只做小改，最多处理 debug 展示或后续输入缓冲。
- `tests/test_wand_detector.py`、`tests/test_wand_tracking.py`、`tests/test_cv_controller.py`：必须补测试。

第一轮建议只做 tracker 修复，不做输入缓冲。输入缓冲可以作为第二轮，因为它会改变游戏施法手感。

## 现状代码入口

当前 bright wand 主链路：

- `cv/wand_detector.py::detect_tip()`
  - HSV detector
  - LK optical flow
  - alpha-beta filter
  - short coasting
  - LOST

- `cv/wand_tracking.py`
  - `AlphaBetaFilter2D`
  - `SparseLKTracker`
  - ROI helpers

- `cv/controller.py`
  - `_gate_wand_point()`
  - `hold_missing_point()`
  - `_wand_missing_track_ready_to_classify()`

当前关键阈值：

```python
WAND_DETECT_LOCK_CONFIDENCE = 0.55
WAND_DETECT_RELOCK_CONFIDENCE = 0.65
WAND_OBSERVATION_JUMP_DISTANCE = 90.0
WAND_OBSERVATION_RELOCK_CONFIDENCE = 0.78
WAND_LK_MIN_CONFIDENCE = 0.45
WAND_COAST_OUTPUT_CONFIDENCE = 0.32
```

## 录屏与日志诊断

分析对象：

- 录屏：`20260619-0459-02.6660254.mp4`
- wand debug：`logs/wand_debug/session_20260619_125552.jsonl`

整体统计：

```text
LOST:     1075
LOCKED:    270
COASTING:   49
FLOW:        9
```

这说明 LK 光流实际救场极少，大多数问题发生在 detector/reacquire 层。

### 异常区间 1：0:32 - 0:35

现象：

- 蓝色贴片肉眼可见。
- 黄色锁点长期没有跟上。
- debug 长时间 `LOST`。

日志特征：

```text
candidate_count = 1
best_score ~= 0.50 - 0.58
required relock = 0.65
detail = no bright tip in hand roi
```

判断：

系统不是完全没看见蓝色，而是看见了低分候选但不敢 relock。这里的失败属于重捕获过慢。

### 异常区间 2：0:47 - 0:49

现象：

- 真实蓝贴片快速折返。
- 黄色点留在头顶附近，明显滞后。
- 轨迹和物理笔尖脱节。

日志特征：

```text
jump ~= 160px
jump ~= 172px
jump ~= 282px
gate = reject_jump
state = COASTING / LOST
```

判断：

固定 jump gate 对快速折返过严。真实笔尖因为速度和转向离预测点很远，却被当作跳点拒绝，之后 coasting 继续画旧预测，导致视觉漂移。

### 异常区间 3：0:51 - 0:54

现象：

- 向上起手和后续向前推的起始帧被漏掉。
- 画面上黄点慢半拍，甚至出现在额头附近。
- 用户感觉像存在隐性 CD。

日志特征：

```text
lk_color
reject_jump
best_score ~= 0.57 - 0.61
53.84s 才重新 LOCKED
```

判断：

这是重捕获慢和 jump gate 过严叠加。实际输入已经开始，但系统仍处于 LOST / weak candidate 阶段，导致动作前半段没有进入轨迹。

## 根因总结

当前最大问题不是 DTW，也不是手势分类器，而是：

1. `LOST` 后 relock 阈值过于单帧化。
   - 候选连续稳定出现，但只要单帧分数低于 `0.65` 就不锁。

2. `jump gate` 是固定阈值。
   - 快速运动和锐角折返时，真实笔尖本来就会远离预测点。

3. `COASTING` 有时掩盖真实观测。
   - 有新候选出现但被 jump 拒绝时，coasting 继续输出旧预测，视觉上就是黄点漂移。

4. debug 文案不够具体。
   - 当前经常显示 `no bright tip`，但真实原因可能是 `low_score 0.58 < relock 0.65`。

## 推荐方案

第一轮只做 Bright Wand Tracking v2，不做输入缓冲。

### 核心方法

从当前：

```text
single best candidate -> fixed threshold -> fixed jump gate
```

升级为：

```text
multi candidates
-> candidate history
-> dynamic relock
-> dynamic jump gate
-> clearer debug
```

### 设计原则

- 保留 `WandDetector.detect_tip(frame, hand_landmarks, track, now, width, height) -> (point, detail)` 外部接口。
- `finger` mode 完全不改。
- 不改 spell classifier。
- 不改 PVE AI、伤害、冷却。
- 不把 coasting 时间无限延长。
- 不用 KCF/CSRT/MOSSE 作为主方案。
- 不引入训练模型。

## 实施任务

### Task 1：新增候选历史 helper

**文件：**

- 修改：`cv/wand_tracking.py`
- 修改：`models/cv_track.py`
- 测试：`tests/test_wand_tracking.py`

**目标：**

保存最近几帧的候选点，用于判断低分候选是否稳定。

建议新增数据结构：

```python
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class WandCandidateSample:
    point: np.ndarray
    score: float
    area: float
    source: str
    timestamp: float


class WandCandidateHistory:
    def __init__(self, maxlen=5):
        self.samples = deque(maxlen=maxlen)

    def reset(self):
        self.samples.clear()

    def add(self, point, score, area, source, timestamp):
        self.samples.append(
            WandCandidateSample(
                point=np.asarray(point, dtype=np.float32),
                score=float(score),
                area=float(area),
                source=str(source),
                timestamp=float(timestamp),
            )
        )

    def stable_near(self, point, now, max_age=0.22, max_distance=48.0, min_count=2):
        point = np.asarray(point, dtype=np.float32)
        hits = []
        for sample in self.samples:
            if now - sample.timestamp > max_age:
                continue
            if float(np.linalg.norm(sample.point - point)) <= max_distance:
                hits.append(sample)
        return len(hits) >= min_count
```

在 `models/cv_track.py` 增加字段：

```python
wand_candidate_history: object = None
```

在 reset 逻辑中清空它。

**测试要求：**

- `stable_near()` 对连续 2 个近距离候选返回 True。
- 对距离过远候选返回 False。
- 对超过 `max_age` 的候选返回 False。

### Task 2：让 detector 暴露候选列表

**文件：**

- 修改：`cv/wand_detector.py`
- 测试：`tests/test_wand_detector.py`

**目标：**

`_detect_marker_once()` 不只保存 best candidate，还要在 `DetectionResult.debug` 中保存候选摘要。

建议 debug 字段：

```python
debug["candidates"] = [
    {
        "point": [float(cx), float(cy)],
        "score": float(score),
        "area": float(area),
        "source": source,
        "hue_distance": float(hue_distance),
        "mean_sat": float(mean_sat),
        "mean_val": float(mean_val),
    },
    ...
]
```

保留 `DetectionResult.ok` 的现有语义，不要破坏原调用方。

**测试要求：**

- 有亮色 marker 时，debug 里存在 `candidates`。
- 多个 blob 时，`candidate_count` 与 `candidates` 长度一致。
- `best_score` 仍然是最高候选分数。

### Task 3：动态 relock

**文件：**

- 修改：`cv/wand_detector.py`
- 修改：`cv/wand_tracking.py`
- 测试：`tests/test_wand_detector.py`

**目标：**

解决 0:32-0:35 和 0:51-0:54 中“候选连续出现但低于 0.65 不敢锁”的问题。

建议策略：

```text
正常 LOCK:
  score >= 0.55

LOST 后强 relock:
  score >= 0.65

LOST 后稳定低分 relock:
  score >= 0.55
  且最近 0.22s 内有至少 2 帧候选落在 48px 内
  且 area >= WAND_MIN_AREA
  且 source in ("blob", "endpoint")
```

实现建议：

```python
def _candidate_is_stable_for_relock(self, track, detection, now):
    if not detection.ok or detection.point is None:
        return False
    if detection.score < WAND_DETECT_LOCK_CONFIDENCE:
        return False
    history = self._get_candidate_history(track)
    area = float(detection.debug.get("area", 0.0))
    return history.stable_near(detection.point, now, max_age=0.22, max_distance=48.0, min_count=2)
```

`detect_tip()` 中应在每次有 best candidate 时先写入 history，再判断 relock。

debug 文案要区分：

```text
wand relock stable conf 0.58
NO WAND: low_score 0.54 < relock 0.65
```

**测试要求：**

- LOST 状态下单帧 `score=0.58` 不 relock。
- LOST 状态下连续两帧相近 `score=0.58` relock。
- 相隔太远的两帧低分候选不 relock。

### Task 4：动态 jump gate

**文件：**

- 修改：`cv/wand_tracking.py`
- 修改：`cv/wand_detector.py`
- 测试：`tests/test_wand_tracking.py`
- 测试：`tests/test_wand_detector.py`

**目标：**

解决快速折返时真实笔尖被 `reject_jump` 拒掉的问题。

建议新增 helper：

```python
def dynamic_jump_limit(speed, dt, lost_duration, score):
    base = 90.0
    speed_bonus = min(120.0, max(0.0, float(speed)) * max(float(dt), 0.0) * 0.75)
    lost_bonus = min(70.0, max(0.0, float(lost_duration)) * 260.0)
    score_bonus = 40.0 if float(score) >= 0.65 else 0.0
    return min(260.0, base + speed_bonus + lost_bonus + score_bonus)
```

`_observation_gate()` 当前使用固定 `WAND_OBSERVATION_JUMP_DISTANCE = 90.0`。改为：

```text
allowed_jump = dynamic_jump_limit(track_speed, dt, lost_duration, detection.score)
if jump <= allowed_jump:
    accept
elif detection.score >= WAND_OBSERVATION_RELOCK_CONFIDENCE:
    strong_relock
else:
    reject_jump
```

需要从 `track.wand_tracker_velocity` 或 filter velocity 估算 speed。没有速度时使用 0。

debug 增加：

```python
debug["observation_jump_limit"] = allowed_jump
debug["observation_speed"] = speed
debug["observation_dt"] = dt
```

**测试要求：**

- 慢速、弱候选、远距离仍然 reject。
- 高速、短时丢点、可靠候选允许 accept。
- score >= 0.78 的远候选仍然 strong relock。

### Task 5：coasting 与新候选的关系

**文件：**

- 修改：`cv/wand_detector.py`
- 测试：`tests/test_wand_detector.py`

**目标：**

避免有新候选出现但被 jump gate 拒掉时，coasting 继续画旧预测，导致黄点漂移。

建议策略：

```text
如果 detection 有候选，但因 jump 被拒绝：
  - 如果 candidate score >= 0.55 且 jump 不超过 dynamic_limit * 1.35：
      优先输出 COASTING，但 debug 标记 "candidate_pending_relock"
  - 如果 jump 极大或 candidate score 很低：
      不继续长期 coasting，尽快 LOST
```

更简单的第一版：

```text
reject_jump 且 detection.score >= 0.55:
  coasting 最多 1 帧
  下一帧若仍 reject_jump，则 LOST，不再继续用旧预测画线
```

debug 增加：

```python
debug["coast_policy"] = "candidate_pending_relock" | "hard_lost" | "normal"
```

**测试要求：**

- 有高分但远距离候选时，不会无限 coasting。
- 第二帧仍 reject_jump 时进入 LOST。
- 正常 detector/LK 成功路径不受影响。

### Task 6：debug 文案修正

**文件：**

- 修改：`cv/wand_detector.py`
- 测试：`tests/test_wand_detector.py`

**目标：**

让手测时能直接看出是低分、跳点、颜色失败还是 relock 失败。

建议 detail：

```text
NO WAND: low_score 0.58 < relock 0.65
NO WAND: jump 172 > limit 128
NO WAND: lk_color pixels 1 < 3
WAND RELOCK stable conf 0.58
WAND LOCKED detector conf 0.72
WAND COAST pending relock conf 0.32
```

**测试要求：**

- low score 路径 detail 包含 `low_score`。
- jump 路径 detail 包含 `jump` 和 `limit`。
- stable relock 路径 detail 包含 `relock stable`。

## 第二轮可选：CV 输入缓冲

这部分不建议和 tracker v2 同时做。只有 tracker v2 后仍然明显有“我画了但 GCD 还差 0.2s”的挫败感，再做。

### 目标

如果 CV 已经成功分类，但因为 GCD 很短时间未结束被挡住，则缓存 0.25-0.35 秒，GCD 结束后释放。

### 规则

允许缓存：

- `GCD <= 0.35s`
- `spell cooldown <= 0.20s`

不允许缓存：

- `SILENCE`
- `NO MANA`
- `ROUND OVER`
- player dead
- confidence < cast threshold

### 涉及文件

- `models/cv_track.py`
- `cv/controller.py`
- `tests/test_cv_controller.py`

### 风险

输入缓冲会改变游戏手感，可能让 PVE 更公平，也可能让误触更容易出技能。所以必须放在 tracker v2 后单独手测。

## 不要做的事

KIMI CODE 不应做以下事项：

- 不改 `cv/gesture_classifier.py`。
- 不改 `cv/hybrid_classifier.py`。
- 不改 `cv/template_classifier.py`。
- 不改 PVE AI 伤害、冷却、HP、MP。
- 不恢复 `plain_wand`。
- 不引入 YOLO、深度学习训练、KCF/CSRT/MOSSE 主跟踪器。
- 不把 `WAND_LOST_HOLD_TIME` 简单拉长到很大。
- 不让 coasting 长时间输出预测点。

## 验证命令

每个任务后至少运行相关测试：

```powershell
python -m unittest tests.test_wand_tracking -v
python -m unittest tests.test_wand_detector -v
python -m unittest tests.test_cv_controller -v
```

最后运行全量：

```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
```

## 手动验收步骤

运行：

```powershell
python main.py
```

进入 PVE 或 Solo，切到 wand mode，校准蓝色贴片。

重点复测：

```text
1. 快速下划/上划各 10 次。
2. zigzag 快速折返 10 次。
3. Lumos 上挑接 Incendio 前推 10 次。
4. Protego 张手与 wand mode 共存路径 10 次。
```

观察目标：

```text
LOCKED 比例明显上升。
FLOW 少也可以，但不能长期 LOST。
NO WAND 不应持续 1 秒以上。
快速折返时黄点不能长期留在旧位置。
debug 能显示 low_score / jump / relock stable。
```

成功标准不是“永不丢点”，而是：

- 0:32-0:35 类似场景中，蓝贴片可见时应在 0.2-0.4 秒内 relock。
- 0:47-0:49 类似快速折返时，不能让旧预测点连续漂移超过 2-3 帧。
- 0:51-0:54 类似连续施法时，起手帧不能整段漏掉。

## 推荐执行顺序

1. 候选历史 helper。
2. detector 暴露候选列表。
3. 稳定低分 relock。
4. 动态 jump gate。
5. coasting 与新候选关系修正。
6. debug 文案修正。
7. 全量测试。
8. 手测录屏。
9. 根据新日志决定是否做 CV 输入缓冲。

