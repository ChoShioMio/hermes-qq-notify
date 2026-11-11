# 迁移指南

适用于更换 Bot、切换正式/沙箱环境、移动安装目录、更换电脑/profile，以及从其他通知发送端迁入。验证范围仅限 Windows 10/11 + Python 3.11；HTTP 实现本身不构成跨平台服务支持承诺。

## 不变原则

1. **先停旧发送端，再切换身份或启用新发送端。** 不并行保留旧插件、旧脚本和新服务的同类推送。单目录锁无法阻止不同目录/电脑同时发送。
2. **AppID、环境、OpenID 和绑定 scope 是一组。** OpenID 不是 QQ 号，不能跨 AppID 或跨环境直接复用；本项目不自动合并身份。不通过手改 `QQ_BOUND_*` 绕过检查。
3. **配置迁移不是私有数据入库。** Git 只承载源码与公开模板，不备份 `.env`、凭证、日志、状态、Hermes 会话库、通知图片或虚拟环境。
4. **保留其他 outbound 目标。** `hooks.outbound` 是完整列表；更新或删除本项目条目时先读取现有配置、合并后通过 `hermes config set hooks.outbound` 写回。不要替换整段 `hooks` 或整个配置文件。
5. **不承诺补发。** 迁移期间停止服务会丢失内存队列，发送失败无持久补偿。重要内容应回到 Hermes 核对，不能依赖通知作为唯一记录。

## 迁移前检查

在本地确认，不向公开 Issue 粘贴这些值：

- 旧发送端所在目录、电脑、当前用户自启注册，以及 Hermes 中全部同类发送来源。
- 实际使用的 Hermes 数据目录/profile；服务 `HERMES_HOME` 必须指向它，不能沿用其他 profile 的默认路径。
- Bot 的 AppID、选择的环境和单聊资格，接收者的主动消息开关及平台限制。
- 服务端口是否需要改变；Hermes outbound URL 必须一致，保持 `127.0.0.1`。
- webhook 共享密钥是保留还是轮换；服务 `NOTIFY_SECRET` 与对应 Hermes `.env` 的 `HERMES_NOTIFY_SECRET` 必须同步。
- 是否需要本地受限备份以便回滚。备份应放在仓库外并限制访问，不上传 Git，不把原始日志作为迁移附件。

以下命令在 Windows cmd 中、相应服务目录执行。此文档是操作指南，不表示任何步骤已在当前电脑执行。

## 更换 Bot 或切换环境

### 1. 停止旧发送端

若旧发送端是本项目，在旧目录执行：

```bat
stop.cmd
.venv\Scripts\python.exe manage_autostart.py remove
```

`stop.cmd` 停止本目录进程并保留 `.stopped`，即使重启/重新登录也不恢复。自启 `remove` 本身不停止进程；相反，仅停止而保留旧注册也不是完成迁移。

若旧发送来自其他脚本/插件，按它自己的管理方式停用，并只删除或禁用旧通知来源。不要误删其他机器人或其他 outbound 目标，也不要按端口不加区分地结束无关进程。

### 2. 重新绑定

在仓库外准备新 Bot 凭证文件，两行 AppID/AppSecret，或 `QQ_APPID=...`、`QQ_SECRET=...` 键值。不要将密钥直接放到命令行。

```bat
.venv\Scripts\python.exe pair_bot.py --credentials "<仓库外的本机凭证文件>" --environment production
```

沙箱使用 `--environment sandbox`。等到 `READY` 后，向目标 Bot 单聊发送终端给出的完整随机短语；只有显示 `PAIRED` 才算写入新身份完成。成功时更新凭证、新 OpenID、环境与绑定 scope，保留其他无关配置；它不会启动通知服务或主动发消息。

不能只改 `QQ_SANDBOX` 并沿用旧 OpenID。`production` 表示 API 域名选择，不代表应用已公开上架。配对失败时检查平台权限、订阅与环境，不复制旧身份绕过。

### 3. 配置检查与恢复

```bat
.venv\Scripts\python.exe notifier.py --check
```

检查不联网、不建库、不发消息。缺少 `state.db` 只影响标题/元信息，可警告降级，不应复制其他人的 Hermes 数据来消除警告。

若仍使用同一目录、端口和 HMAC 密钥，换 Bot 通常不需要更改 Hermes webhook 地址或密钥。确认旧发送端停用后，再显式恢复：

```bat
start-hidden.cmd
curl http://127.0.0.1:8787/health
```

`start-hidden.cmd` 清除 `.stopped`。核对健康 JSON 的 `service` 为 `hermes-qq-notify`；健康不证明 QQ 送达。需要登录自启时，最后执行：

```bat
.venv\Scripts\python.exe manage_autostart.py install
.venv\Scripts\python.exe manage_autostart.py status
```

`install` 只注册，不立即启动服务。

## 移动目录或更换电脑

1. 在旧目录停止服务、移除旧登录自启，处理其他同类发送来源。
2. 在新位置获取干净源码，不把运行目录整体打包上传；不要复制 `.venv`，不要把旧去重状态当消息 outbox 迁移。
3. 仅在新位置 `.venv` 不存在时创建环境，再安装依赖：

   ```bat
   uv venv --python 3.11 .venv
   uv pip install --python .venv\Scripts\python.exe -r requirements.txt
   .venv\Scripts\python.exe configure.py
   ```

   已有环境不要覆盖。`configure.py` 只在 `.env` 不存在时创建并生成随机密钥，不会更新已存在配置，也不会配置 Hermes。

4. 本地重建配置。优先新生成密钥并重新绑定；若确需保留同 AppID/环境的既有配置，只能通过受限本地渠道迁移，且旧发送端必须保持停用。不得把「同一接收者」理解为可跨 AppID/环境复用身份。
5. 设置实际 `HERMES_HOME`，Windows 默认 `%LOCALAPPDATA%\hermes` 未必是当前 profile。只需元信息查询，不要求迁移旧 `state.db`。
6. 配置对应电脑上的 Hermes outbound。回环地址指向 Hermes 所在电脑；将通知服务搬到另一台电脑不能继续靠原来的 `127.0.0.1` 跨机访问。本项目不提供公网/远程部署流程。
7. 如果新建或轮换密钥，本地编辑 Hermes `.env` 的 `HERMES_NOTIFY_SECRET` 与服务 `NOTIFY_SECRET` 一致，不打印或上传。保留并合并所有其他 outbound 目标，通过 CLI 写回。
8. 若版本需要桌面补充注册，检查 `integrations/hermes/qq-notify/` 模板与实际插件目录，在对应 profile 下执行 `hermes plugins enable qq-notify`；不要保留多份同类注册。按客户端要求重新加载。
9. 运行无发送配置检查和离线测试，再经授权启动新服务、验收并注册新目录自启。移动目录后不能依赖旧启动项自动修复路径。

`autostart.vbs` 相对自身目录启动，适合随项目移动；但登录启动项仍需移除并重新安装。不要只复制一个 VBS 到别处期待它找到原安装目录。

## Hermes 配置合并

模板 `integrations/hermes/hooks.json` 表示完整的 outbound 数组。先读取已有目标，将本项目条目合入，保留其他条目，并避免重复注册。没有其他目标时可直接使用模板；否则在仓库外准备合并后的 JSON 文件。

Windows shell 对 JSON 引号容易产生歧义，可用 Python 读取原文并将其作为单个参数传给 CLI。以下示例仅用于**已确认没有其他 outbound 目标**时；有其他目标时替换为合并后文件路径：

```bat
.venv\Scripts\python.exe -c "import pathlib,subprocess; raw=pathlib.Path('integrations/hermes/hooks.json').read_text(encoding='utf-8'); subprocess.run(['hermes','config','set','hooks.outbound',raw],check=True)"
```

不要手工覆盖 `config.yaml`。变更后通过当前 Hermes CLI/设置界面核对目标列表；客户端升级或修改设置后也应复核。`HERMES_NOTIFY_SECRET` 是秘密，只在实际 Hermes 数据目录的 `.env` 中本地维护。

## 验收分层

| 层级 | 方法 | 不能证明什么 |
| --- | --- | --- |
| 离线回归 | `.venv\Scripts\python.exe scripts/check.py`，阻断网络、清理业务环境并使用假配置与内存图片 | 不证明 QQ 权限、网络或真实客户端事件覆盖。 |
| 纯配置检查 | `.venv\Scripts\python.exe notifier.py --check`，不联网/建库/发消息 | 不证明远端 API 可用。 |
| 进程健康 | `/health`，核对服务标识、端口和计数 | 不证明客户端已收到通知。 |
| 经授权真实发送 | `notifier.py --test` 或 `--selftest-event` | 两者都会真实发 QQ；后者在进程内构造事件，不经过 HTTP webhook，不证明 Hermes 会触发事件。 |
| 客户端端到端 | 在目标 Hermes 客户端产生工具轮次、人工审批或真实 `clarify`，由接收者确认 QQ 到达 | 一次通过不代表未来不丢消息、所有版本/客户端均覆盖。 |

默认只推工具轮次完成，纯聊天不通知不能直接判定故障。`pre_tool_call` 是调用前提醒，不是问题仍在等待的实时状态；需在真实客户端验收，不能仅发模拟 webhook 宣称支持。

## 回滚

1. 停止新目录服务，移除其自启，避免与旧端并行发送。
2. 从受限本地备份恢复旧端配置或重新绑定旧 Bot；身份必须与 AppID/环境匹配，不把新 OpenID 填到旧 Bot。
3. 通过 Hermes CLI 恢复/合并对应 outbound 条目，仅撤回本次变更，保留其他集成；密钥变更需同步双方。
4. 检查后只恢复一个发送端，再进行经授权验收。不要期待 `state.json` 补发迁移期间的消息。

## 完全卸载

在当前目录执行 `stop.cmd` 后移除登录自启。通过 Hermes CLI 从完整 outbound 列表中仅删除本项目条目；不再需要的可选注册插件可在确认无其他引用后移除。只有确认共享密钥不再被任何目标使用，才本地移除对应 `HERMES_NOTIFY_SECRET`。私有配置、日志与凭证按本地保密策略删除或受限保存，不上传公开仓库。

安装概览见 [README](../README.md)，队列、去重和隐私边界见 [架构说明](ARCHITECTURE.md)。
