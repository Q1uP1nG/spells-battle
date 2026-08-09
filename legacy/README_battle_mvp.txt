Spells Battle MVP 运行说明
==========================

文件
----
spells_battle_mvp.py
双人对战 MVP 主程序。当前版本先用键盘模拟施法，摄像头画面作为背景。

requirements.txt
运行依赖。


安装依赖
--------
在你本地可用的 Python 环境里运行：

pip install -r requirements.txt


启动
----
python spells_battle_mvp.py

如果摄像头可用，程序会使用摄像头画面作为背景。
如果摄像头不可用，程序会自动生成一个深色竞技场背景，方便调试战斗逻辑。


入场页面
--------
启动后先进入主菜单：

1 = Solo Spell Showcase
单人术法展示模式。用于练习和展示五个咒语的识别与特效。
左侧会显示 Spell Guide 咒语图鉴，提示每个咒语的动作和冷却状态。

2 = Duel Battle Mode
双人对战模式。使用 HP / Mana / 冷却 / 护盾 / 弹道碰撞进行对战。

M = 回到主菜单


键位
----
P1:
Q = Incendio 火焰咒
W = Stupefy 昏击咒
E = Glacius 冰冻咒
R = Protego 护盾咒
T = Lumos 回血咒

P2:
U = Incendio 火焰咒
I = Stupefy 昏击咒
O = Glacius 冰冻咒
P = Protego 护盾咒
L = Lumos 回血咒

SPACE = 重开一局
ESC = 退出


当前实现内容
------------
1. 主菜单 / 入场页面
2. 单人术法展示模式
3. 双人对战模式
4. 左右双人分区
5. HP / Mana 系统
6. 全局施法冷却
7. 单咒语冷却
8. 5 个咒语冷却 UI
9. Incendio / Stupefy / Glacius 弹道
10. Protego 护盾
11. Lumos 引导回血
12. 回血可被 Incendio / Stupefy 打断
13. Stupefy 沉默
14. Glacius 冻结减速 + 小幅延长对方全局冷却
15. 弹道互相碰撞
16. 护盾命中与破盾
17. HP 归零胜负结算
18. 可选 MediaPipe 双人 CV 手势输入


CV 输入
-------
如果安装了 mediapipe，程序会自动开启 CV 模式。
当前 CV 版本用食指指尖作为“杖尖代理”，按手腕所在半屏分配玩家：

当前版本使用 MediaPipe Tasks API 的 HandLandmarker。
第一次运行时，如果目录下没有 hand_landmarker.task，程序会自动下载模型文件。
如果自动下载失败，可以手动下载 hand_landmarker.task 并放到本项目目录。

左半屏 = P1
右半屏 = P2

手势映射：

向对方方向快速横向推出 = Incendio
向上快速轻挑 = Lumos
大 U 形护盾弧 = Protego
向下冰冻斩 = Glacius
多折返闪电线 = Stupefy

实际操作建议：

Incendio:
P1 从左往右明显推出；P2 从右往左明显推出。
动作尽量直，横向位移大一点，不要上下抖太多。

Glacius:
从上往下明显划一下，像向下劈开冰面。
不要画 Z 了，Z 和闪电太像，容易被识别成 Stupefy。

Stupefy:
画闪电，多折返，比 Z 多一到两次折线。

如果一直触发 Stupefy:
说明轨迹里折返太多。放 Incendio 时尽量只做一条直线横推；放 Glacius 时只向下划一刀；放 Protego 时画成闭合的圈。

Protego:
画一个顺滑的大 U 形，不需要闭合。
动作要宽一点、高一点，像在身前从一侧拉到另一侧撑开一道盾。
两端高度尽量接近，中间明显向下或向上鼓出来。
不要画成来回折线，否则会更像 Stupefy。

Lumos:
明显向上挑，不要只小幅抬手。

画面底部会显示每个玩家的 CV 预测结果：

CV 1: 当前预测 咒语置信度
CV 2: 当前预测 咒语置信度

这版 CV 是快速可演示接入：先证明“视觉轨迹 -> 咒语 -> 对战系统”的闭环。

最终版本不要看手指，而是看笔 / 筷子 / 魔杖道具的杖尖。
MediaPipe Hands 只作为辅助：用手腕、手心和手指方向限制搜索区域。
真正输入轨迹应替换为 HSV + 形态学 / 端点检测得到的真实杖尖坐标。

演示时可以手持一支笔或筷子作为魔杖。


攻击咒语克制
------------
三种攻击咒语是循环克制：

Glacius 克制 Incendio
冰球碰到火球时，火球消失，冰球继续飞行，但伤害和速度略微降低。

Incendio 克制 Stupefy
火球碰到闪电时，闪电消失，火球继续飞行，但伤害和半径略微降低。

Stupefy 克制 Glacius
闪电碰到冰球时，冰球消失，闪电继续飞行，但伤害和速度略微降低。

同种弹道对撞时双方抵消，避免同一种技能刷屏。


Mana 和 Shield
---------------
MANA 是魔力条，所有咒语都会消耗 Mana。
SH 是护盾条，只在 Protego 生效时有数值。

Incendio: 消耗 25 Mana
Stupefy: 消耗 35 Mana
Glacius: 消耗 30 Mana
Protego: 消耗 30 Mana
Lumos: 消耗 40 Mana

当前冷却：

Global: 2.3 秒
Incendio: 3.0 秒
Stupefy: 5.0 秒
Glacius: 4.6 秒
Protego: 6.0 秒
Lumos: 8.0 秒

CV 触发做了防抖：

手势幅度要比较明显才会施法。
成功触发后，CV 本地锁定 1.5 秒，避免同一个手势在连续帧里重复释放。

冷却期间不采样：

如果画面底部显示 CV WAIT，说明该玩家正在全局冷却、CV 锁定、沉默或已经不能施法。
这段时间手指移动不会进入轨迹缓冲区，会被直接忽略。
这样可以避免释放火球后“手指回到原位”的轨迹在冷却结束后又触发一次法术。


特效策略
--------
当前版本不依赖贴图素材，全部用 OpenCV 代码绘制：

Incendio: 发光火球 + 火花尾迹
Stupefy: 红色光束 + 电弧
Glacius: 冰蓝旋转波纹 + 冰粒子
Protego: 半透明护盾弧
Lumos: 引导光环 + 爆发粒子

这样更适合期末项目的第一版，因为不会被素材下载、版权、透明通道、尺寸适配卡住。
后续如果要更华丽，可以再把 spell 命中爆炸、火焰和护盾换成 PNG 序列或 GIF alpha blend。


下一步接 CV
-----------
等战斗系统调通之后，把键盘触发替换成 CV 分类输出即可。

建议接口：

cast_spell(player_index, spell_name, now)

其中 player_index:
0 = 左侧玩家 P1
1 = 右侧玩家 P2

spell_name:
incendio
stupefy
glacius
protego
lumos
