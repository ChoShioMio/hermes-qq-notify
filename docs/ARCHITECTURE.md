# 架构与事件处理

## 运行环境

项目已在 Windows 10/11、Python 3.11 验证。服务与 Hermes 独立运行；绑定时会临时连接 QQ 网关，日常通知通过 QQ 官方 HTTPS API 发送。

## 组件

| 文件 | 职责 |
| --- | --- |
| `notifier.py` | 配置、签名验证、事件筛选、去重、摘要和 QQ 发送。 |
| `message_card.py` | 在本机将 Markdown 排版为 PNG。 |
| `pair_bot.py` | 绑定 Bot，获取当前 Bot/环境的接收者 OpenID。 |
| `configure.py` | 首次创建本机 `.env` 和随机 webhook 密钥。 |
| `supervisor.py` | 看门狗与本目录进程锁。 |
| `manage_autostart.py` | 管理当前 Windows 用户的登录自启。 |
| `integrations/hermes/` | Hermes outbound 模板和可选桌面注册插件。 |

## 数据流

```text
Hermes outbound
  → POST /event（127.0.0.1，HMAC-SHA256）
  → 校验与事件筛选
  → 内存队列、只读会话元信息、去重
  → 本机生成 PNG 或短文字
  → QQ 官方 API
```

Webhook 可能包含完整对话历史。通知可能带有会话标题、提问、回复、命令、错误和工作目录等信息；图片生成于内存，再上传至 QQ。服务只读查询 `HERMES_HOME/state.db` 中的会话元信息。

服务 `.env` 的 `NOTIFY_SECRET` 必须与 Hermes `.env` 的 `HERMES_NOTIFY_SECRET` 一致。HMAC 验证请求来源，不加密正文。

## 事件

- **`post_llm_call`**：有最终回复时生成完成摘要。默认只发已知包含工具调用的轮次；纯聊天跳过。历史不足时无法判断，可能仍发通知。
- **`pre_approval_request`**：提醒用户回到 Hermes 审批；`surface=smart` 的自动判断阶段不通知。审批仍在 Hermes 中完成。
- **`pre_tool_call` / `clarify`**：发送调用前的问题与选项，兼容批量 `questions[]` 和旧格式。问题后续可能已回答或校验失败，通知不会撤回。
- **`api_request_error`**：显示模型 API 错误摘要。
- **`on_session_end`**：默认关闭；须同时订阅事件并设置 `NOTIFY_SESSION_END=1`。

客户端和 Hermes 版本会影响事件是否触发。升级后应从实际使用的客户端检查关键事件。

## 排队与去重

`POST /event` 验证后返回 `202`，事件由后台线程处理。队列最多 512 项，仅在内存中；服务停止或崩溃会丢失待处理事件，队列满时会丢弃新事件。系统没有持久 outbox 或失败补发机制。

`state.json` 保存 90 秒去重标记，不保存消息正文。标记在发送前写入；发送失败后仍会保留到窗口结束。因此可能漏发或重复，不适合作为审批记录或唯一告警渠道。

图片准备或上传失败时可降级为短文字。图片发送请求超时后不会自动补发文字，以免重复。`/health` 显示进程和队列状态，不代表用户已收到消息。

## 内容格式

支持标题、粗体、列表、引用和简化表格；代码块会省略，正文和图片有长度上限，超限时会截断或降级文字。通知应作为提醒；完整内容以 Hermes 会话为准。

## 生命周期

`start-hidden.cmd` 和 `start.cmd` 清除 `.stopped` 并启动看门狗；`stop.cmd` 停止本目录进程并保留停用标记。登录自启只在当前 Windows 用户登录后启动，目录移动后需重新注册。

安装与测试见 [README](../README.md)，迁移与回滚见 [迁移指南](MIGRATION.md)。
