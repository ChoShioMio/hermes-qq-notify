# hermes-qq-notify

将 Hermes 会话事件转发到 **QQ 官方机器人单聊**的本地通知桥。默认把摘要在本机排版为 PNG，再通过 QQ 官方 API 上传、发送；也可使用短文字。QQ 只接收提醒，审批和回答仍在 Hermes 中完成。

**验证范围仅限 Windows 10/11 + Python 3.11。** HTTP 收发使用 Python 标准库，不代表整个服务支持 Linux/macOS：启停、自启、进程管理和字体选择都包含 Windows 假设。本项目不是 Windows 系统服务，登录自启不等于登录前运行。

## 功能与边界

- 接收带 HMAC-SHA256 签名的 Hermes outbound webhook，仅监听 `127.0.0.1`。
- 提醒工具轮次完成、人工审批、`clarify` 提问和模型 API 错误；可选会话结束提醒。
- 本地 Markdown 排版：标题、粗体、列表、引用、简化表格；代码块省略，回复正文默认最多 1400 字，图片最高 6000 像素，超限标记截断。
- 不下载正文中的图片或链接，不使用第三方图床；业务 PNG 只在内存生成，但会上传到 QQ。
- 图片准备或上传失败时降级短文字；图片发送请求发出后若失败或超时，不再补发文字，以降低重复风险。
- 独立虚拟环境、看门狗、隐藏启动和可选当前用户登录自启；不修改 Hermes 源码，也不依赖其他聊天机器人项目。

**不承诺可靠送达或恰好一次。** 队列在内存中，HTTP `202` 不代表 QQ 已收到；90 秒去重在发送前标记，失败没有持久补偿。详见 [架构与事件语义](docs/ARCHITECTURE.md)。

```text
Hermes outbound hooks
  → HMAC 签名 POST /event（本机）
  → 内存队列 → 事件筛选 / 会话元信息 / 去重
  → 本机 Markdown → PNG（或短文字）
  → QQ 官方 API → 绑定的 QQ 单聊
```

## 事件语义

| 事件 | 通知行为与限制 |
| --- | --- |
| `post_llm_call` | 有最终回复时生成轮次完成摘要；默认只推已知包含工具调用的轮次，已知纯聊天跳过。缺少历史时无法判断，可能仍推送。不是独立任务调度器的成功证明。 |
| `pre_approval_request` | 提醒返回 Hermes 审批；`surface=smart` 的自动判断阶段跳过，避免将自动放行误报成人工等待。 |
| `pre_tool_call`，`tool_name=clarify` | 调用前提问提醒，兼容批量 `questions[]` 与旧格式；不是实时 pending 状态，已回答或后续校验失败后仍可能收到。 |
| `api_request_error` | 摘要显示模型 API 错误，不代表所有工具或应用错误都会被捕获。 |
| `on_session_end` | 默认关闭；启用需同时订阅此事件并设置 `NOTIFY_SESSION_END=1`。 |

事件是否产生、桌面/CLI/网关覆盖范围与字段格式取决于安装的 Hermes 版本。升级后应重新验收；QQ 不提供回复、审批按钮或消息自动撤回。

## 安装

以下命令在 **Windows 命令提示符（cmd）** 中、仓库根目录执行；需已安装 Git、uv、Hermes，并能使用 `hermes` CLI。

```bat
git clone https://github.com/ChoShioMio/hermes-qq-notify.git
cd hermes-qq-notify
```

### 1. 创建独立环境

仅在 `.venv` 不存在时创建；已有环境先确认归属和 Python 版本，**不要覆盖**。

```bat
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

依赖由 `requirements.txt` 固定：Pillow、markdown-it-py 用于图片；websocket-client 只用于一次性绑定，常态通知不维持 QQ WebSocket。

### 2. 初始化本地配置

```bat
.venv\Scripts\python.exe configure.py
```

仅当 `.env` 不存在时，从 `.env.example` 创建配置并生成随机 `NOTIFY_SECRET`；已有文件保持不变。此步骤不写入 Hermes 配置、不绑定 Bot、不启动服务。

本地编辑服务 `.env`，确认 `HERMES_HOME` 指向实际使用的 Hermes 数据目录/profile，并核对以下配置。不要将配置值或截图放进公开 Issue。

| 键 | 含义 |
| --- | --- |
| `QQ_APPID` / `QQ_SECRET` | 当前 Bot 凭证，由绑定程序写入。 |
| `QQ_OPENID` | 当前 Bot、当前环境下重新获得的接收者身份，不是 QQ 号。 |
| `QQ_SANDBOX` | `1` 沙箱、`0` 正式；切换必须重新绑定。 |
| `QQ_BOUND_APPID` / `QQ_BOUND_SANDBOX` | 绑定作用域；不匹配时拒绝启动，不要手工伪造。 |
| `NOTIFY_HOST` / `NOTIFY_PORT` | 默认 `127.0.0.1:8787`；必须保持回环监听。 |
| `NOTIFY_SECRET` | 本地 webhook 共享密钥，不可留空。 |
| `NOTIFY_FORMAT` | 默认 `image`；设为 `text` 使用短文字。 |
| `SUMMARY_CHARS` | 默认 `1400`；图片仍有独立高度上限。 |
| `ONLY_TOOL_TURNS` | 默认 `1`；设为 `0` 可推送所有有回复的完成轮次。 |
| `NOTIFY_SESSION_END` | 默认 `0`；设为 `1` 还需在 Hermes 中订阅相应事件。 |
| `HERMES_HOME` | 显式配置优先；未配置时 Windows 默认 `%LOCALAPPDATA%\hermes`，其他系统回退 `~/.hermes`，不构成其他系统服务支持承诺。 |

`state.db` 仅用于只读查询会话标题、来源等元信息；缺失只警告，标题可退化为会话 ID。使用多 profile 时不要只依赖默认目录。

### 3. 绑定新 Bot

先在 QQ 官方机器人管理平台确认应用、接收者与所选环境具备所需单聊权限。平台资格、用户主动消息开关和频控以当时官方规则及错误码为准，不提供固定额度保证。

在**仓库外**准备本机凭证文件，内容为两行（第一行 AppID、第二行 AppSecret），或 `QQ_APPID=...`、`QQ_SECRET=...` 两个键值。不要把密钥放到命令行参数中，也不要提交该文件。

```bat
.venv\Scripts\python.exe pair_bot.py --credentials "<仓库外的本机凭证文件>" --environment production
```

需要沙箱时改用 `--environment sandbox`。`production` 只是正式 API 环境，不等于应用已公开上架。

等待终端出现 `READY`，再向**目标 Bot 单聊**发送终端给出的完整随机绑定短语。程序只匹配该短语，其他事件丢弃；成功后原子写入新凭证、新 OpenID 和绑定作用域，显示 `PAIRED`，不自动发送通知。超时或失败不要靠复制旧 OpenID 绕过绑定。

替换已有 Bot 前，先停止旧发送端，避免重复推送；详见 [迁移指南](docs/MIGRATION.md)。

### 4. 配置 Hermes 接入

`integrations/hermes/hooks.json` 是 **`hooks.outbound` 完整列表模板**，不是整个 Hermes 配置文件。

**先检查现有 outbound 目标并合并，不能直接覆盖其他通知或集成。** 在本地准备保留原有条目的合并后 JSON 数组；只有确认原来没有其他目标时，才能直接使用仓库模板。合并时避免重复添加 `qq-notify`，并使 URL 端口与本服务一致。

通过 CLI 写入，不手工拼接或覆盖 `config.yaml`。Windows 可使用 Python `subprocess` 传递 JSON 原文，避免 shell 引号损坏。下例**仅适用于已确认没有其他 outbound 目标**的情况；否则将路径换成仓库外的合并后 JSON 文件：

```bat
.venv\Scripts\python.exe -c "import pathlib,subprocess; raw=pathlib.Path('integrations/hermes/hooks.json').read_text(encoding='utf-8'); subprocess.run(['hermes','config','set','hooks.outbound',raw],check=True)"
```

在实际使用的 Hermes 数据目录 `.env` 中，**本地编辑** `HERMES_NOTIFY_SECRET`，使它与服务 `.env` 的 `NOTIFY_SECRET` 完全一致。不要在终端打印密钥，不把密钥写进 hooks JSON 或提交到仓库。变更后按安装版本要求重新加载/重启对应 Hermes 客户端。

若当前桌面版本还需要补充 outbound 注册，可选使用 `integrations/hermes/qq-notify/` 中的插件模板：将整个目录复制到实际 Hermes 数据目录的 `plugins/qq-notify/` 下，再通过 CLI 启用（多 profile 时须在对应 profile 下操作）：

```bat
hermes plugins enable qq-notify
```

然后重新加载/重启相应客户端。仅复制目录不代表插件已启用。模板用于注册，不替代 outbound 配置或共享密钥；不要在未核实版本行为时叠加多个发送来源。

## 检查、启动与自启

先进行无发送配置检查：

```bat
.venv\Scripts\python.exe notifier.py --check
```

此检查不联网、不建库、不发送消息；不会验证 QQ 权限、网络可达性或 Hermes 实际派发行为。

| 操作 | 命令 | 说明 |
| --- | --- | --- |
| 隐藏启动/恢复 | `start-hidden.cmd` | 清除 `.stopped` 并通过看门狗启动。 |
| 前台调试 | `start.cmd` | 前台看门狗，清除停用标记；不要同时启动多个副本。 |
| 健康检查 | `curl http://127.0.0.1:8787/health` | 使用实际端口；核对 JSON 中 `service` 为 `hermes-qq-notify`，健康不等于消息已送达。 |
| 停止 | `stop.cmd` | 停止本目录看门狗和通知进程；保留 `.stopped`，跨重启停用，直到显式恢复。 |
| 查看登录自启 | `.venv\Scripts\python.exe manage_autostart.py status` | 查询当前用户注册状态。 |
| 安装登录自启 | `.venv\Scripts\python.exe manage_autostart.py install` | 只注册，不立即启动服务。 |
| 移除登录自启 | `.venv\Scripts\python.exe manage_autostart.py remove` | 只移除注册，不停止已运行服务。 |

看门狗在通知进程退出后重启，快速失败采用退避；这不是消息重试或持久队列。关闭 Hermes 不会自动停止独立通知进程。登录自启使用 Windows 当前用户启动文件夹；注销期间、登录前不运行。直接运行 `autostart.vbs` 不清除 `.stopped`。

运行日志位于本地 `logs/`；不要公开上传原始日志。端口冲突、解释器缺失、签名不一致、作用域不一致应分别排查，不要通过关闭签名或改为公网监听来绕过。

## 测试与验收

离线回归使用假配置和内存图片，不发送真实 QQ 通知：

```bat
.venv\Scripts\python.exe scripts/check.py
uv pip check --python .venv\Scripts\python.exe
```

以下是**主动的真实发送测试**，只在已获授权、确认接收者后手动执行：

```bat
.venv\Scripts\python.exe notifier.py --test
.venv\Scripts\python.exe notifier.py --selftest-event
```

`--test` 检查发送路径；`--selftest-event` 在本进程构造完成事件并经过格式化/QQ 发送，**不经 HTTP webhook，也不能证明 Hermes 自动触发事件**。端到端验收需从目标 Hermes 客户端产生工具轮次、人工审批或 `clarify`，并由接收者确认 QQ 到达。`pre_tool_call` 的实际提问触发尤其需要客户端验收，不能用模拟载荷代替。

## 保密与非目标

服务会处理会话正文、提问、命令及元信息；摘要、省略代码块和截断**不是脱敏器**，敏感文本仍可能发往 QQ。仅将允许离开本机的数据用于通知。HMAC 用于认证，不提供正文加密，也不抵御已经控制本机的进程。

不提交 `.env`、凭证文件、OpenID、Hermes 数据、日志、去重状态、通知图片或本地环境；不要把公开 Git 当私人数据备份。发布前复核暂存区，而不是只依赖忽略规则。安全边界和问题报告要求见 [SECURITY.md](SECURITY.md)。

本项目不提供 QQ 对话代理、远程审批/回答、公网 webhook、多租户网关、历史会话同步、持久 outbox、离线补发、跨平台服务管理或平台权限绕过。

卸载时先 `stop.cmd`，再移除登录自启；通过 Hermes CLI 读取、筛选并写回 outbound 列表，仅删除本项目条目，保留其他目标。共享密钥仅在确认没有其他引用后从对应 Hermes `.env` 移除。目录移动、换 Bot/环境、换电脑和回滚见 [迁移指南](docs/MIGRATION.md)。

## 许可证

[MIT](LICENSE)。QQ 平台使用资格、消息规则与第三方依赖的许可不由本项目授予。
