# Spells Battle

用键盘、手指轨迹或彩色魔杖尖施放魔法的 Python 对战游戏，支持单人、本地双人、PVE 和远程对战。

## 下载与启动

在 GitHub 点击 **Code → Download ZIP**，解压后进入包含 `main.py` 的文件夹，也可以通过 Git 克隆仓库：

```bash
git clone https://github.com/Q1uP1nG/spells-battle.git
cd spells-battle
```

需要先安装 Python 和依赖。开发机使用 Windows、Python 3.13.13；游戏需要桌面图形环境。

Windows（在解压后的文件夹打开 PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

以后启动时只需运行最后一条命令。若 Windows 找不到 `python`，可使用 Python 启动器执行 `py -3 -m venv .venv`，然后继续后两步。

macOS / Linux（需系统支持 OpenCV 图形窗口）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

首次安装依赖需要联网。仓库包含角色原图 `pictures/`、游戏使用的透明角色图 `pictures_transparent/`、音效 `assets/audio/`、手部识别模型 `hand_landmarker.task` 和手势模板 `models/`，不需要另行拷贝资源。单机模式不需要连接对战服务器。

没有摄像头时，游戏使用生成的竞技场背景，仍可通过键盘游玩。手指识别需要摄像头；魔杖模式还需要在笔尖等物体上放置醒目的彩色标记。

## 基本操作

先点击游戏窗口，让它获得键盘焦点，建议切换到英文输入法。

| 操作 | 按键 |
| --- | --- |
| 菜单选择 | `1` 单人、`2` 本地双人、`3` PVE、`4` 手势训练、`5` 远程对战 |
| 选择角色 | P1：`A` / `F`；P2：`J` / `K`；空格或回车确认 |
| P1 施法 | `Q` 火焰、`W` 昏迷、`E` 冰冻、`R` 护盾、`T` 治疗 |
| P2 施法 | `U` 火焰、`I` 昏迷、`O` 冰冻、`P` 护盾、`L` 治疗 |
| PVE 开始 / 暂停 / 继续 | 空格；退格键重新开始 |
| 单人 / 本地双人重置 | 空格 |
| 切换手指 / 魔杖识别 | `V`；魔杖尖放在中心后按 `C` 校准颜色 |
| 背景音乐 / 音效静音 | `B` / `N` |
| 返回菜单 / 退出 | `Esc` 返回菜单；菜单中 `Esc` 或 `X` 退出 |

## 远程对战

菜单按 `5`，`C` 创建房间或 `J` 加入房间，`A` / `F` 选择角色，`R` 准备。双方客户端和服务器需要使用相同的协议版本，当前为 **3**。

默认服务器地址来自 `client_config.json`。远程对战取决于服务器是否在线；也可以自行运行服务器（Windows）：

```powershell
.\.venv\Scripts\python.exe -m server.app
```

连接本机服务器时，在启动客户端的 PowerShell 中先设置：

```powershell
$env:SPELLS_SERVER_URL = "ws://127.0.0.1:8765"
.\.venv\Scripts\python.exe main.py
```

详见[远程对战运行说明](docs/remote_duel_runbook.md)和[服务器部署说明](deploy/README.md)。

## 开发与检查

安装依赖后运行（Windows）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS / Linux 请将上述 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`。缓存、日志、本地设置和临时预览不包含在仓库里，会按需在本机生成。

项目结构和历史说明见 [README_refactor.md](README_refactor.md)，进展见 [docs/README.md](docs/README.md)。
