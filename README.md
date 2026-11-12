# hermes-qq-notify

Hermes 通知桥：把 Hermes 的重要事件摘要发到 QQ 官方 Bot 单聊。服务运行在本机，默认监听 `127.0.0.1:8787`；QQ 只接收提醒，审批和回答仍在 Hermes 中完成。

**当前验证环境：Windows 10/11、Python 3.11。** 登录自启在 Windows 用户登录后运行，不是系统服务。

## 功能

- 提醒工具轮次完成、人工审批、`clarify` 提问和模型 API 错误；会话结束提醒可选。
- 支持本地 Markdown 转 PNG，或短文字通知；失败时按情况降级。
- 使用 HMAC 验证本机 webhook，提供配置检查、看门狗和 Windows 登录自启。
- 通知是尽力而为：内存队列在停止或崩溃时会丢待处理事件，没有持久补发。

```text
Hermes outbound → 本机签名 webhook → 筛选与摘要 → QQ 官方 API → Bot 单聊
```

## 安装

在 Windows 命令提示符（cmd）中运行。需要 Git、uv、Hermes CLI。

```bat
git clone https://github.com/ChoShioMio/hermes-qq-notify.git
cd hermes-qq-notify
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe configure.py
```

若 `.venv` 已存在，不要覆盖它；先确认环境归属。`configure.py` 只在 `.env` 不存在时从模板创建配置并生成随机签名密钥。

编辑本机 `.env`，设置实际 Hermes 数据目录 `HERMES_HOME`（多 profile 时尤其要核对）。主要选项：

| 变量 | 用途 |
| --- | --- |
| `QQ_APPID`、`QQ_SECRET`、`QQ_OPENID` | 由配对程序写入的 Bot 凭证与接收者身份。OpenID 不是 QQ 号。 |
| `QQ_SANDBOX` | `1` 为沙箱，`0` 为正式环境；切换环境需重新配对。 |
| `NOTIFY_HOST`、`NOTIFY_PORT` | 默认 `127.0.0.1:8787`，保持回环监听。 |
| `NOTIFY_SECRET` | webhook 共享密钥，需与 Hermes 的 `HERMES_NOTIFY_SECRET` 一致。 |
| `NOTIFY_FORMAT` | `image`（默认）或 `text`。 |
| `SUMMARY_CHARS` | 摘要长度，默认 `1400`。 |
| `ONLY_TOOL_TURNS` | 默认只提醒已知包含工具调用的完成轮次；设为 `0` 可提醒所有完成轮次。 |
| `NOTIFY_SESSION_END` | 默认关闭；启用时还需在 Hermes outbound 订阅该事件。 |

`state.db` 只读用于查询会话标题等信息；缺失时服务可用会话 ID 显示。

## 配对 Bot

在仓库外创建本机凭证文件：两行 AppID、AppSecret，或使用 `QQ_APPID=...` 与 `QQ_SECRET=...`。不要把凭证放进仓库或命令行参数。

```bat
.venv\Scripts\python.exe pair_bot.py --credentials "<本机凭证文件路径>" --environment production
```

沙箱改用 `--environment sandbox`。看到 `READY` 后，向目标 Bot 单聊发送终端显示的随机短语；成功会显示 `PAIRED` 并保存新身份。配对会保留其他通知设置，不会启动服务或发送通知。

## 配置 Hermes

`integrations/hermes/hooks.json` 是 `hooks.outbound` 的完整列表模板。先读取当前列表并合并，保留其他集成；确认原列表为空后才可直接使用模板。用 Hermes CLI 设置合并后的 JSON，不要覆盖整个 `config.yaml`。

无其他 outbound 目标时可运行：

```bat
.venv\Scripts\python.exe -c "import pathlib,subprocess; raw=pathlib.Path('integrations/hermes/hooks.json').read_text(encoding='utf-8'); subprocess.run(['hermes','config','set','hooks.outbound',raw],check=True)"
```

在实际 Hermes 数据目录的 `.env` 中设置 `HERMES_NOTIFY_SECRET`，与服务的 `NOTIFY_SECRET` 完全一致，再按当前客户端要求重新加载。

若桌面版本需要注册插件，将 `integrations/hermes/qq-notify/` 复制到对应 profile 的 `plugins/qq-notify/`，然后启用：

```bat
hermes plugins enable qq-notify
```

重新加载对应客户端。插件用于注册，不替代 outbound 目标或共享密钥；避免重复配置发送来源。

## 检查与运行

配置检查和离线测试不会发送 QQ 通知：

```bat
.venv\Scripts\python.exe notifier.py --check
.venv\Scripts\python.exe scripts/check.py
uv pip check --python .venv\Scripts\python.exe
```

| 操作 | 命令 |
| --- | --- |
| 隐藏启动或恢复 | `start-hidden.cmd` |
| 前台调试 | `start.cmd` |
| 停止并保持停用 | `stop.cmd` |
| 查看健康状态 | `curl http://127.0.0.1:8787/health` |
| 查看登录自启 | `.venv\Scripts\python.exe manage_autostart.py status` |
| 安装/移除登录自启 | `manage_autostart.py install` / `manage_autostart.py remove`，通过 `.venv\Scripts\python.exe` 调用 |

`stop.cmd` 会阻止看门狗重启服务；恢复请运行 `start-hidden.cmd`。关闭 Hermes 不会停止独立服务。登录自启仅在当前 Windows 用户登录后运行。

`notifier.py --test` 和 `notifier.py --selftest-event` 会真实发送 QQ 消息，只在确认接收者并授权后手动运行。端到端测试需从实际 Hermes 客户端触发事件，并确认 QQ 收到提醒。

## 数据与安全

Webhook 可能带有完整会话历史；摘要也可能包含提问、回复、命令和元信息。只转发允许发送到 QQ 的内容。HMAC 验证来源，不加密请求正文；本机生成的图片会上传到 QQ。

不要提交 `.env`、Bot 凭证、OpenID、Hermes 数据库、日志、状态文件或通知图片。更多说明见 [安全说明](SECURITY.md)。

项目不提供 QQ 双向聊天、远程审批、公网 webhook、持久消息队列或跨平台服务管理。

## 文档

- [迁移、换 Bot 与回滚](docs/MIGRATION.md)
- [架构与事件处理](docs/ARCHITECTURE.md)
- [安全与漏洞报告](SECURITY.md)
- [MIT 许可证](LICENSE)
