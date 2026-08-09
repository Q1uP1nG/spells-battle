# 两个版本对比与营养吸收方案

## 版本关系

```
D:\magic spale\magic spale\
├── magic_spale_refactor\          ← 提交版（OpenCV 前端，我在改的）
└── zjjversion\
    └── magic_spale_refactor(1)\
        └── magic_spale_refactor\  ← Claude 版（pygame 前端 + OpenCV fallback）
```

两个版本共享同一套 `game/` `cv/` `models/` 核心逻辑，差异主要在渲染层和部分 CV/工具模块。

---

## 两个版本各有什么

### 提交版（OpenCV 前端）独有的

| 特性 | 文件 | 说明 |
|------|------|------|
| **Wand tracking v2** | `cv/wand_tracking.py` `cv/wand_detector.py` | `WandCandidateHistory` + `dynamic_jump_limit`，解决快速折返漂移和 relock 慢 |
| **PVE 暂停/恢复/重启** | `game/mode.py` `main.py` | `pve_paused` / `toggle_pve_pause()` / Backspace 重启 |
| **Wand 调试日志** | `cv/wand_debug_log.py` | `WandDebugLogger`，带自动清理 |
| **ESC 上下文感知** | `main.py` | 菜单内退出，游戏内回菜单 |
| **PIL 字体渲染** | `renderer/text.py` | 中文楷体 + Georgia/Cambria |
| **OpenCV 屏幕反馈** | `renderer/effects.py` | `apply_screen_feedback`（warpAffine 震动）+ `draw_flash_messages` |
| **show_debug 参数贯通** | `renderer/hud.py` `cv/controller.py` | `draw_hud` 和 `draw()` 都接收 `show_debug` |

### Claude 版（zjjversion）独有的

| 特性 | 文件 | 说明 |
|------|------|------|
| **数据驱动 DTW 模板训练** | `tools/train_gesture_templates.py` | 从日志挖掘轨迹 → k-medoids 聚类 → margin-based 阈值 → 输出 `models/gesture_templates.json` |
| **FusedGestureClassifier** | `cv/gesture_pipeline.py` | heuristic miss 时 DTW rescue（≥0.80），一致时 confidence +0.08 |
| **DataTemplateClassifier** | `cv/template_classifier.py` | 加载 JSON 模板，从真实数据学习 |
| **离线分类器对比工具** | `tools/eval_classifiers.py` | heuristic vs fused 的 A/B 准确率对比 |
| **pygame JuiceEngine** | `renderer/fx/engine.py` `renderer/fx/scene.py` `renderer/fx/menus.py` | 屏幕震动 / hitstop / 发光叠加 / 伤害数字 / vignette |
| **双渲染器** | `main.py`（pygame）+ `main_classic.py`（OpenCV） | 同一份逻辑两个前端 |
| **程序化音频合成** | `game/audio.py` | 14 种 NumPy 合成音效，外部文件优先 |
| **外部音频资源** | `assets/audio/` | CC0 wav/ogg |

### 两版都有的

| 特性 | 说明 |
|------|------|
| 20 张透明角色 PNG | 两版都有 `pictures_transparent/`，内容完全相同 |
| `renderer/character_assets.py` | 两版都有，立绘加载 + alpha 混合 |
| Shadow DTW 分类器 | 两版都有 `ShadowTemplateClassifier` |
| JSONL 手势日志 | 两版都有 `cv/gesture_log.py` |
| `tools/replay_cv_logs.py` | 两版都有离线会话统计 |
| CV Training 模式 | 两版都有 `game/cv_training.py` |
| 4 角色系统 | 两版都有 Harry/Hermione/Ron/Snape |
| 角色选择界面 | 两版都有 CHARACTER_SELECT 模式 |

---

## 能从 Claude 版吸收什么

### P0：数据驱动 DTW 模板训练（最核心）

**现状：** 提交版只有固定合成模板（`_gen_incendio_template()` 等硬编码轨迹），不能从用户真实数据学习。

**Claude 版的做法：**
1. 挖掘 `logs/cv_sessions/*.jsonl` 中的标注轨迹
2. 弧长重采样到 32 点
3. DTW 距离矩阵上做 k-medoids 聚类
4. 计算每个法术的 margin-based 接受阈值
5. x 轴镜像，P1/P2 共用一套模板
6. 输出 `models/gesture_templates.json`

**吸收方式：** 复制 `tools/train_gesture_templates.py`，从 Claude 版的 `cv/template_classifier.py` 中提取 `DataTemplateClassifier` 类加入提交版。

### P0：FusedGestureClassifier 融合策略

**现状：** 提交版的 `GesturePipeline` 是 primary + shadow 并行记录，不做融合决策。

**Claude 版的融合规则：**
- heuristic 有信心 → 用 heuristic
- heuristic miss 但 DTW confidence ≥ 0.80 → rescue（救回漏掉的轨迹）
- 两者一致 → confidence +0.08

**吸收方式：** 把 `FusedGestureClassifier` 移植到提交版的 `cv/gesture_pipeline.py`，作为 primary 分类器升级。保留提交版现有的 shadow 记录能力。

### P1：离线分类器对比工具

**吸收方式：** 直接复制 `tools/eval_classifiers.py`。

### P1：程序化音频 + 外部资源

**吸收方式：** 复制 `assets/audio/` 目录。如果提交版的 `AudioManager` 不支持外部文件，参考 Claude 版的 `game/audio.py` 加入双策略（外部优先 + 合成 fallback）。

### P2（可选）：pygame 前端

**吸收方式：** 复制 `renderer/fx/` 子包 + Claude 版的 `main.py`（改名为 `main_pygame.py`），把提交版现有的 `main.py` 保留为 `main_classic.py`。注意要把提交版独有的 ESC 上下文感知、PVE pause 等逻辑 merge 进 pygame 版的 `process_key()`。

---

## 绝对不能被覆盖的（提交版优势）

| 特性 | 原因 |
|------|------|
| `cv/wand_tracking.py` | 提交版有 `WandCandidateHistory` + `dynamic_jump_limit`，Claude 版没有 |
| `cv/wand_detector.py` | 提交版有候选历史 + 动态 jump gate + 稳定 relock，Claude 版没有 |
| `game/mode.py` PVE pause 部分 | 提交版有暂停/恢复，Claude 版没有 |
| `cv/wand_debug_log.py` | 提交版独有 |
| `renderer/text.py` | 提交版独有 PIL 字体 |
| `renderer/effects.py` | 提交版独有 OpenCV 屏幕反馈 |
| `main.py` 的 ESC 逻辑 | 提交版独有上下文感知 |

---

## 迁移步骤

### 步骤 1：复制数据驱动 DTW 管线

```
复制：tools/train_gesture_templates.py
提取：cv/template_classifier.py 中的 DataTemplateClassifier 类
```

跑一次 `python tools/train_gesture_templates.py` 生成 `models/gesture_templates.json`。

### 步骤 2：升级 gesture_pipeline 融合策略

把 `FusedGestureClassifier` 的融合逻辑（rescue + consistency boost）加入提交版的 `cv/gesture_pipeline.py`。

### 步骤 3：复制离线工具

```
复制：tools/eval_classifiers.py
```

### 步骤 4：复制音频资源

```
复制：assets/audio/ 整个目录
```

### 步骤 5（可选）：加 pygame 前端

```
复制：renderer/fx/ 整个子包
复制：Claude 版 main.py → 改名 main_pygame.py
改名：提交版 main.py → main_classic.py
```

Merge 提交版独有的按键逻辑到 pygame 版。

### 步骤 6：跑测试

```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
```

---

## 总结

```
提交版 = wand tracking 最强 + PVE 最完整 + 测试最全
Claude 版 = 数据驱动 DTW 训练 + 融合分类器 + pygame juice + 音频

吸收后 = 两者最优合集
```

核心吸收 3 样东西：
1. **数据驱动 DTW 训练管线**（分类器从固定 → 可学习）
2. **FusedGestureClassifier 融合策略**（rescue + consistency boost）
3. **音频资源**（CC0 wav/ogg + 程序化合成 fallback）

pygame 前端是可选项，看你要不要双渲染器。

工作量：核心 3 样约 3-4 小时，加 pygame 前端再加 3-4 小时。
