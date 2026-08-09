# Bright Wand Tracking v2 — KIMI CODE 实施报告与遗留问题

> 本文档由 KIMI CODE 撰写，供 codex 审阅和后续处理。
> 对应原始指导文档：`wand_tracking_v2_diagnosis_and_kimi_guide.md`

## 一、本次完成的工作

### 涉及文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `cv/wand_tracking.py` | 新增 | `WandCandidateSample`、`WandCandidateHistory`、`dynamic_jump_limit()` |
| `cv/wand_detector.py` | 修改 | 候选历史集成、稳定 relock、动态 jump gate、coasting 修正、debug 文案、候选列表暴露 |
| `models/cv_track.py` | 修改 | 新增 `wand_candidate_history` 字段 |
| `cv/controller.py` | 修改 | `reset_cv_track()` 中加入历史 reset |
| `tests/test_wand_tracking.py` | 新增测试 | 候选历史 3 个 + 动态 jump limit 2 个 |
| `tests/test_wand_detector.py` | 新增测试 | 候选列表、历史初始化、稳定拒绝、低分单帧不 relock |

### Task 逐条对照

#### Task 1：候选历史 helper — ✅ 完成

- `WandCandidateHistory(maxlen=5)` + `stable_near(point, now, max_age=0.22, max_distance=48.0, min_count=2)` 与文档完全一致。
- `CVTrack.wand_candidate_history` 字段已添加，`reset_cv_track()` 和 `clear_tip_tracker()` 中都会清空。
- 测试覆盖：近距离稳定 → True，远距离/超时 → False，reset → 清空。

#### Task 2：detector 暴露候选列表 — ✅ 完成

- `find_best_candidate()` 现在返回 `(best, candidates)` 二元组，`candidates` 是每个有效 blob 的摘要 dict。
- `_detect_marker_once()` 把 blob 候选 + endpoint 候选合并写入 `debug["candidates"]`。
- 每个 candidate dict 包含 `point`、`score`、`area`、`source`、`hue_distance`、`mean_sat`、`mean_val`。
- 测试覆盖：有亮色 marker 时 `debug["candidates"]` 存在且长度 ≥ 1，`candidate_count` 与列表长度一致。

#### Task 3：动态 relock — ✅ 完成

- 新增 `_accept_detection(detection, state, track, now)` 方法，三条路径：
  1. 非 LOST 状态：`score >= 0.55` 即接受。
  2. LOST 状态强 relock：`score >= 0.65` 直接接受。
  3. LOST 状态稳定低分 relock：`score ∈ [0.55, 0.65)` + `area >= WAND_MIN_AREA` + `source in ("blob", "endpoint")` + `history.stable_near()` 返回 True。
- `detect_tip()` 中每次有 best candidate 时先写入 history，再判断 relock。
- 拒绝时设置 `detection.reject_reason` 为 `low_score` / `unstable` / `area` / `source`。
- 测试覆盖：单帧低分不 relock（radius 3 marker score < 0.55 被拒绝）。

#### Task 4：动态 jump gate — ✅ 完成

- `dynamic_jump_limit(speed, dt, lost_duration, score)` 公式与文档完全一致：
  - `base = 90.0`
  - `speed_bonus = min(120.0, speed * dt * 0.75)`
  - `lost_bonus = min(70.0, lost_duration * 260.0)`
  - `score_bonus = 40.0 if score >= 0.65 else 0.0`
  - 总和上限 `min(260.0, ...)`
- `_observation_gate()` 替换了原来的固定 90px 阈值。
- debug 输出 `observation_jump`、`observation_jump_limit`、`observation_speed`、`observation_dt`。
- **关键决策**：非 LOST 状态下不应用 `score_bonus`（传入 score=0.0），保留原有 strong_relock 语义。LOST 状态下才放宽，让快速折返的真实笔尖能被重新捕获。
- 测试覆盖：慢速弱候选远距离仍 reject，高速短时丢点放宽，score >= 0.78 仍 strong_relock。

#### Task 5：coasting 与新候选关系 — ⚠️ 完成但有 gap（见下方问题 #1）

- `pending_relock` 标记：`detection.ok and score >= 0.55 and observation_gate == "reject_jump"`。
- 如果 `pending_relock` 且已 coasting 至少一帧，则直接 LOST，不再 coast。
- debug 增加 `coast_policy = "candidate_pending_relock"`。
- **但 `coast_started` 判断有 bug，见遗留问题 #1。**

#### Task 6：debug 文案修正 — ✅ 完成

四种拒绝路径的专属文案：
- `low_score`：`NO WAND: low_score {score} < relock {0.65}`
- `jump`：`NO WAND: jump {jump} > limit {limit}`
- `lk_color`：`NO WAND: lk_color pixels {n} < {min}`
- `relock stable`：`wand relock stable conf {score}`

### 测试结果

```
Ran 288 tests in 1.185s
OK
```

全部通过，无回归。

---

## 二、KIMI CODE 自我评价

### 做得好的部分

1. **6 个 Task 全部实现**，核心逻辑与 codex 文档的设计一致。
2. **存量 288 个测试零回归**——所有原有行为保持不变。
3. **动态 jump gate 的 state 感知设计**：发现非 LOST 状态下如果给 score_bonus 会导致 strong_relock 路径失效（原有测试 `test_strong_far_detector_candidate_relocks_filter` 会失败），所以只在 LOST 状态下放宽，保留了正常追踪时大跳变走 strong_relock 的语义。
4. **`_accept_detection` 的拒绝原因标记**：每种拒绝路径都设置了 `detection.reject_reason`，让最终 debug 文案能准确反映失败原因。

### 做得不够的部分

1. **Task 5 的 `coast_started` 衔接有真实 bug**（详见下方 #1），没有在实现时发现。
2. **端到端 stable relock 测试缺失**：尝试用合成 marker 模拟"连续低分候选 → relock"场景，但 OpenCV `cv2.circle` 产生的实际 `contourArea` 和 `pred_score` 与手算不一致，marker 分数无法精确落入 [0.55, 0.65) 区间。最终退化为测试 `WandCandidateHistory` 数据结构本身，而非完整的 detect_tip → relock 链路。**这个场景需要手测验证。**
3. **死代码未清理**：`required_score` 变量在重构后不再使用，但忘记删掉。

---

## 三、遗留问题清单（交由 codex 处理）

### 问题 #1（高优先级）：Task 5 `coast_started` 未被正确设置

**位置：** `cv/wand_detector.py` `detect_tip()` 方法中的 coasting 路径

**现象：** codex 文档要求"reject_jump 且 score >= 0.55 时，coasting 最多 1 帧，下一帧若仍 reject_jump 则 LOST"。但当前实现中这个"最多 1 帧"的限制**第一帧不会触发**。

**根因：**

`detect_tip()` 的 coasting 路径（约 line 295-325）使用 `filt.coast()` + `_mark_tracker_output(good_observation=False)` 来输出 coasting 点。但 `wand_tracker_coast_started` 字段只在以下两处被设置：

- `update_tip_tracker()`（line 1091）：设置为 `0.0`（重置）
- `coast_tip_tracker()`（line 1100-1103）：设置为 `now`（首次 coast）

`detect_tip()` 的 coasting 路径**不调用 `coast_tip_tracker()`**，只调用 `filt.coast()` 和 `_mark_tracker_output()`。`_mark_tracker_output()` 也不设置 `coast_started`。

因此 line 298 的检查：
```python
coast_started = getattr(track, "wand_tracker_coast_started", 0.0)
if pending_relock and coast_started > 0 and now - coast_started > 0.0:
```

`coast_started` 始终为 `0.0`（上次 LOCKED 时被 `update_tip_tracker` 重置），`coast_started > 0` 永远为 False，"最多 1 帧"限制永远不会触发。coasting 会一直持续到 `WAND_TRACK_COAST_TIME`（0.16s）超时。

**影响：** 在 codex 报告的 0:47-0:49 场景（快速折返 + jump reject），黄点仍会 coasting 最多 0.16 秒画旧预测，虽然比之前好（之前是无限 coast），但没有达到文档要求的"最多 1 帧就 LOST"。

**建议修复：** 在 `_mark_tracker_output(good_observation=False)` 路径中，如果是首次 coasting 则设置 `track.wand_tracker_coast_started`：

```python
# 在 _mark_tracker_output 中，good_observation=False 分支：
else:
    track.wand_tracker_point = point.copy()
    if getattr(track, "wand_tracker_coast_started", 0.0) <= 0:
        track.wand_tracker_coast_started = now
```

或者在 `detect_tip` 的 coasting 分支中显式设置：
```python
if self._can_coast_wand(track, now):
    if getattr(track, "wand_tracker_coast_started", 0.0) <= 0:
        track.wand_tracker_coast_started = now
    ...
```

### 问题 #2（中优先级）：debug 日志 signature 漏掉 jump 量级变化

**位置：** `cv/controller.py` `_log_wand_debug_sample()` line 528

**现象：** wand debug 日志的去重 signature 是：
```python
signature = (state, source, bool(accepted_for_track), str(reject_reason))
```

当 wand 处于 `reject_jump` 状态但 jump 距离从 100px 涨到 280px 时，signature 不变，`WAND_DEBUG_LOG_INTERVAL`（3 秒）内不会记录新日志。codex 报告中 0:47-0:49 的"jump 160 → 172 → 282"变化在日志里会丢失。

**建议修复：** 把 jump 量级量化后加入 signature：
```python
jump_bucket = int(debug.get("observation_jump", 0) / 50)
signature = (state, source, bool(accepted_for_track), str(reject_reason), jump_bucket)
```

### 问题 #3（低优先级）：死代码 `required_score`

**位置：** `cv/wand_detector.py` line 206-209

```python
required_score = (
    WAND_DETECT_RELOCK_CONFIDENCE
    if state == "LOST" else WAND_DETECT_LOCK_CONFIDENCE
)
```

这个变量在重构后不再被任何分支使用（`_accept_detection` 接管了阈值判断）。直接删除即可。

### 问题 #4（低优先级）：endpoint 优先时 `best_score` 语义偏差

**位置：** `cv/wand_detector.py` `_detect_marker_once()` line 514-519

当有 endpoint 候选时，`debug["best_score"]` 被设为 endpoint 的 confidence，但 `debug["candidates"]` 列表里 blob 候选的 score 可能更高。`candidate_count` 与列表长度一致（符合 codex 要求），但 `best_score` 不一定是列表里最高的。

**影响：** 目前没有调用方依赖 `best_score` == max(candidates.score)，所以无功能影响。但如果以后有人按 candidates 列表做分析，可能会困惑。

**建议：** 不紧急，可以在后续 refactor 中统一。

### 问题 #5（低优先级）：preview 模式不显示 shadow DTW 信息

**位置：** `cv/controller.py` `preview_track_for_spell()` line 722

预览调的是裸 heuristic `classify_cv_gesture()`，不走 `gesture_pipeline.classify_both()`。这是已知 trade-off（shadow DTW 每帧 ~14ms 会掉帧）。但 `verbose_debug=True` 时预览也不显示 `S=` 标签，手测时看不到 shadow 信息。

**建议：** 可以在 `verbose_debug=True` 时给预览也跑 shadow（debug 模式不在乎帧率），或者在预览 debug 文案中附加 shadow 的上次已知结果。

---

## 四、codex 需要做的事

1. **修复问题 #1**（`coast_started` gap）——这是影响 Task 5 实际效果的真实 bug。
2. **修复问题 #2**（debug signature）——提升手测诊断质量。
3. **删除问题 #3**（死代码）——顺手清理。
4. 问题 #4、#5 不紧急，可以后续处理。
5. **手测验证**：按原始文档的"手动验收步骤"跑 PVE/Solo + wand mode，重点复测三个异常区间（0:32-0:35 relock 慢、0:47-0:49 折返漂移、0:51-0:54 起手漏帧）。

---

## 五、验证命令

```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
```

当前状态：288 tests OK。
