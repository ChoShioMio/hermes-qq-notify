# 迁移与回滚

适用于更换 Bot、切换环境、移动目录或更换电脑。先停旧发送端，再启用新发送端，避免重复通知。

## 更换 Bot 或环境

1. 停止旧服务并移除旧登录自启。若旧端来自其他插件或脚本，按其自身方式停用。

   ```bat
   stop.cmd
   .venv\Scripts\python.exe manage_autostart.py remove
   ```

2. 在仓库外准备新 Bot 凭证文件（两行 AppID、AppSecret，或对应键值）。
3. 重新配对；等待 `READY` 后按提示向目标 Bot 单聊发送随机短语，看到 `PAIRED` 才完成。

   ```bat
   .venv\Scripts\python.exe pair_bot.py --credentials "<本机凭证文件路径>" --environment production
   ```

   沙箱使用 `--environment sandbox`。配对会更新 Bot 凭证、OpenID 与绑定范围，并保留通知样式和摘要长度。

4. 检查配置并启动新服务：

   ```bat
   .venv\Scripts\python.exe notifier.py --check
   start-hidden.cmd
   curl http://127.0.0.1:8787/health
   ```

5. 需要登录自启时，重新注册并检查：

   ```bat
   .venv\Scripts\python.exe manage_autostart.py install
   .venv\Scripts\python.exe manage_autostart.py status
   ```

AppID、环境和 OpenID 必须来自同一次绑定。OpenID 是 Bot 环境内的接收者标识，不是 QQ 号；切换 Bot 或环境需重新配对。不要手改 `QQ_BOUND_*`。

如果端口和 HMAC 密钥未变，通常无需改 Hermes outbound。若更换密钥，服务 `.env` 的 `NOTIFY_SECRET` 与 Hermes `.env` 的 `HERMES_NOTIFY_SECRET` 必须同步。

## 移动目录或更换电脑

1. 在旧目录执行 `stop.cmd`，移除旧自启。
2. 在新位置获取源码，不复制 `.venv`。只有环境不存在时才创建：

   ```bat
   uv venv --python 3.11 .venv
   uv pip install --python .venv\Scripts\python.exe -r requirements.txt
   .venv\Scripts\python.exe configure.py
   ```

3. 编辑新位置的 `.env`，设置实际 `HERMES_HOME`。多 profile 时确认对应数据目录。
4. 重新配对 Bot，并配置 Hermes outbound。保留其他 outbound 目标；将本项目条目合并到完整列表后，通过 `hermes config set hooks.outbound` 写入。
5. 如需插件注册，将 `integrations/hermes/qq-notify/` 复制到目标 profile 的 `plugins/qq-notify/`，再运行 `hermes plugins enable qq-notify` 并重新加载客户端。
6. 运行检查和测试，完成授权的端到端验收后再启用登录自启。

配置模板不会迁移私有资料。不要把 `.env`、凭证、OpenID、日志、`state.json`、Hermes 会话数据库、通知图片或 `.venv` 上传到仓库。需要迁移旧配置时，通过受限的本地渠道处理。

## Hermes outbound 合并

`integrations/hermes/hooks.json` 是完整 outbound 数组。先读取现有列表并保留其他目标；确认列表为空后才可直接使用模板。不要覆盖整个 `config.yaml`。更改后核对目标列表及对应客户端加载状态。

## 验收

| 检查 | 作用 |
| --- | --- |
| `scripts/check.py` | 离线回归，使用测试配置。 |
| `notifier.py --check` | 检查本地配置，不发送消息。 |
| `/health` | 查看服务状态和队列信息。 |
| `notifier.py --test` | 经授权后发送真实测试消息。 |
| 实际客户端事件 | 从目标 Hermes 客户端触发工具轮次、审批或 `clarify`，并确认 QQ 收到通知。 |

## 回滚与卸载

1. 停止新服务并移除新目录的登录自启。
2. 恢复旧配置或重新绑定旧 Bot，确认 AppID 和环境匹配。
3. 通过 Hermes CLI 修改 outbound 列表，只撤回本次变更并保留其他目标；密钥变更时同步两端。
4. 确认只剩一个发送端后再启动并验收。

卸载时先 `stop.cmd`，再移除自启；从 outbound 列表删除本项目目标。确认共享密钥没有其他用途后再从本机 Hermes 配置中移除。
