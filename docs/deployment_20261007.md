# 公网部署记录（2026-10-07）

- 服务器：`101.132.63.248:8765`。
- 部署运行代码：`a29dfcb04f0d00f51cdad58f89487131243e45e4`，协议 3。
- 运行方式：现有 `spells-battle.service`，用户 `spells`，目录 `/opt/spells-battle`。
- 代码包：38 个运行文件；SHA256
  `fd0100f4254be900362973430e740e02fa5c8320b4ef0e0b088a949d5facfe77`。
- 回退备份：`/opt/spells-releases/pre-a29dfcb-20261007-120619.tar.gz`。

部署前确认无房间及连接，校验代码包并在临时目录验证服务端导入。
保留 `.env`、`.venv`、systemd unit 和端口设置，更新运行代码后重启。

## 实测结果

- 健康接口返回 `status=ok` 并包含 metrics。
- systemd 为 `active/running`，`NRestarts=0`；部署后 warning 及以上日志无记录。
- 公网完整双客户端对局通过，协议 3，双方最终快照及胜者一致，探针耗时 19.405 秒。
- 玩家准备后断线、另一方准备、前者重连时，对局自动进入 `RUNNING`。
- 对手断线后等待 48 秒，在线客户端收到 `CLOSED`；在同一 WebSocket 连接上重新建房成功。

本次没有执行两台真实 Windows 设备的摄像头/CV、网络切换及多局重赛人工验收。
旧协议 2 客户端会收到 `version_mismatch`，玩家必须配套更新客户端。
此记录及 README 的后续提交仅更新文档，服务器运行代码仍对应上方部署提交。
