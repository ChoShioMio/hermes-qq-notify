"""hermes-qq-notify —— Hermes 会话事件 → QQ 机器人通知。

架构（独立服务，不修改 hermes-agent 源码）：

    hermes-agent  --hooks.outbound-->  本服务(127.0.0.1:8787)  --QQ 官方 API-->  你的 QQ

触发源是 Hermes 自带的 outbound webhook：
    post_llm_call        一轮对话收尾（任务完成，带最终回复）
    pre_approval_request 危险命令等待审批
    pre_tool_call        工具名为 clarify 时 = 等你回答
    api_request_error    模型 API 调用失败
    on_session_end       会话结束（默认关闭，噪音大）

HTTP 接收与发送使用标准库；本机图片排版依赖 Pillow 和 markdown-it-py。
运行：python notifier.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from project_config import hermes_home

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
STATE_PATH = ROOT / "state.json"
LOG_PATH = LOG_DIR / "notify.log"
MAX_BODY = 64 * 1024 * 1024          # 单条 webhook 上限；post_llm_call 会带整段历史
QQ_MAX_CHARS = 1800                  # 主动消息正文上限（留余量，QQ 硬限更长）
DEDUPE_TTL = 90                      # 同一事件去重窗口（秒）
STARTED_AT = time.time()

SENT = 0
FAILED = 0
LAST_ERROR = ""


# ────────────────────────── 配置 ──────────────────────────

def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("QQ_", "NOTIFY_", "HERMES_"))})
    return env


ENV = load_env()
APPID = ENV.get("QQ_APPID", "")
SECRET = ENV.get("QQ_SECRET", "")
OPENID = ENV.get("QQ_OPENID", "")
SANDBOX = ENV.get("QQ_SANDBOX", "1").lower() not in ("0", "false", "no", "")
NOTIFY_SECRET = ENV.get("NOTIFY_SECRET", "")
HOST = ENV.get("NOTIFY_HOST", "127.0.0.1")
PORT = int(ENV.get("NOTIFY_PORT", "8787") or 8787)
HERMES_HOME = hermes_home({**os.environ, **ENV})
SUMMARY_CHARS = int(ENV.get("SUMMARY_CHARS", "1400") or 1400)
NOTIFY_SESSION_END = ENV.get("NOTIFY_SESSION_END", "0").lower() in ("1", "true", "yes")
# 只推"真的动了工具"的轮次，过滤纯聊天噪音（1=开，0=全部推送）
ONLY_TOOL_TURNS = ENV.get("ONLY_TOOL_TURNS", "1").lower() not in ("0", "false", "no")

QQ_API_BASE = "https://sandbox.api.sgroup.qq.com" if SANDBOX else "https://api.sgroup.qq.com"


# ────────────────────────── 日志 ──────────────────────────

_log_lock = threading.Lock()


def log(msg: str, *, err: bool = False) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {'ERR ' if err else ''}{msg}"
    with _log_lock:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2 * 1024 * 1024:
                LOG_PATH.replace(LOG_PATH.with_suffix(".log.1"))
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        print(line, flush=True)


# ────────────────────────── QQ 发送 ──────────────────────────

class QQClient:
    """QQ 官方机器人 HTTP API（单聊主动消息）。"""

    def __init__(self, appid: str, secret: str, base: str, openid: str = OPENID) -> None:
        self.appid, self.secret, self.base = appid, secret, base
        self.openid = openid
        self._token = ""
        self._expire_at = 0.0
        self._seq = 0
        self._lock = threading.Lock()

    def token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._expire_at - 60:
                return self._token
            body = json.dumps({"appId": self.appid, "clientSecret": self.secret}).encode()
            req = urllib.request.Request(
                "https://bots.qq.com/app/getAppAccessToken", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tok = data.get("access_token")
            if not tok:
                raise RuntimeError(f"token rejected (code={safe_code(data)})")
            self._token = tok
            self._expire_at = time.time() + float(data.get("expires_in") or 7200)
            log(f"QQ access_token 已获取，有效期 {data.get('expires_in')}s")
            return self._token

    def _request(self, path: str, payload: dict, token: str) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"QQBot {token}",
                     "X-Union-Appid": self.appid}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read(1024 * 1024).decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read(65536).decode("utf-8"))
                return exc.code, {"code": safe_code(data)}
            except (ValueError, UnicodeError):
                return exc.code, {"code": "unknown"}

    def _send_payload(self, payload: dict) -> bool:
        global SENT, FAILED, LAST_ERROR
        with self._lock:
            self._seq += 1
            payload = {**payload, "msg_seq": self._seq}
        try:
            for attempt in (1, 2):
                status, data = self._request(f"/v2/users/{self.openid}/messages", payload,
                                             self.token(force=attempt == 2))
                if status == 200 and data.get("id"):
                    SENT += 1
                    LAST_ERROR = ""
                    log(f"已发送 QQ 通知（类型={payload['msg_type']}，msg id {str(data['id'])[:12]}…）")
                    return True
                if status == 401 and attempt == 1:
                    continue
                LAST_ERROR = f"HTTP {status} code={safe_code(data)}"
                break
        except Exception as exc:
            # A timeout may have occurred after QQ accepted the message. Do not blindly resend.
            LAST_ERROR = type(exc).__name__
        FAILED += 1
        log(f"QQ 发送失败: {LAST_ERROR}", err=True)
        return False

    def send(self, content: str) -> bool:
        return self._send_payload({"content": clean(content, 500)[:QQ_MAX_CHARS], "msg_type": 0})

    def send_notification(self, content: str) -> bool:
        if ENV.get("NOTIFY_FORMAT", "image") == "text":
            return self.send(content)
        try:
            from message_card import render_card
            png = render_card(content)
            if len(png) > 4 * 1024 * 1024:
                raise ValueError("card too large")
            status, data = self._request(
                f"/v2/users/{self.openid}/files",
                {"file_type": 1, "file_name": "notification.png", "srv_send_msg": False,
                 "file_data": base64.b64encode(png).decode("ascii")}, self.token())
            if status != 200 or not data.get("file_info"):
                raise RuntimeError(f"upload HTTP {status} code={safe_code(data)}")
            file_info = data["file_info"]
        except Exception as exc:
            log(f"图片准备失败（{type(exc).__name__}），降级为短文字", err=True)
            return self.send(content)
        # No text fallback after this point: sending might succeed despite a lost response.
        return self._send_payload({"msg_type": 7, "media": {"file_info": file_info}})


def safe_code(data: dict) -> str:
    value = str(data.get("code", "unknown")) if isinstance(data, dict) else "unknown"
    return value if re.fullmatch(r"-?\d{1,12}", value) else "unknown"


QQ = QQClient(APPID, SECRET, QQ_API_BASE)


# ────────────────────────── 会话信息 ──────────────────────────

def _s(value: object) -> str:
    """DB 字段可能是 float/None（started_at 是 epoch），统一成字符串。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
        except (OverflowError, OSError, ValueError):
            return str(value)
    return str(value).strip()


def session_info(session_id: str) -> dict[str, str]:
    """从 state.db 只读取会话标题/来源/目录；任何失败都返回空 dict。"""
    if not session_id:
        return {}
    db = HERMES_HOME / "state.db"
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute(
                "select title, display_name, source, cwd, git_branch, started_at "
                "from sessions where id = ?", (session_id,)).fetchone()
        finally:
            con.close()
        if not row:
            return {}
        title, display, source, cwd, branch, started = row
        return {
            "title": (_s(title) or _s(display)),
            "source": _s(source),
            "cwd": _s(cwd),
            "branch": _s(branch),
            "started": _s(started),
        }
    except Exception as exc:                              # noqa: BLE001
        log(f"读取会话信息失败（{session_id[:8]}）: {exc}", err=True)
        return {}


# ────────────────────────── 文本处理 ──────────────────────────

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`([^`]+)`")


def clean(text: str, limit: int) -> str:
    """去掉代码块/多余空白，截断。返回 (文本) —— 不发送整份代码。"""
    if not text:
        return ""
    original_len = len(text)
    text = _FENCE.sub("[代码块已省略]", text)
    text = _INLINE.sub(r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图片]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + f"\n…（原文 {original_len} 字，已截断）"
    return text


def meta_lines(sid: str, platform: str = "", fallback_cwd: str = "") -> list[str]:
    info = session_info(sid)
    out = [f"🗂 会话：{(info.get('title') or sid[:8])[:60]}"]
    tags = [t for t in (info.get("source"), platform, info.get("branch")) if t]
    if tags:
        out.append("🏷 " + " · ".join(dict.fromkeys(tags)))
    cwd = info.get("cwd") or fallback_cwd
    if cwd:
        out.append(f"📁 {Path(cwd).name or cwd}")
    return out


# ────────────────────────── 事件 → 消息 ──────────────────────────

def turn_had_tool_calls(payload: dict) -> bool | None:
    """本轮是否真的动了工具。None = 拿不到历史（无法判断）。

    从对话历史末尾往回走，遇到 role=user 就停——那一段就是一整轮。
    纯聊天（没工具调用）的轮次返回 False，用来过滤掉"好的""谢谢"这类噪音。
    """
    hist = (payload.get("extra") or {}).get("conversation_history")
    if not isinstance(hist, list) or not hist:
        return None
    for msg in reversed(hist):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "tool":
            return True
        if role == "assistant" and msg.get("tool_calls"):
            return True
        if role == "user":
            return False
    return False


def build_message(event: str, payload: dict) -> tuple[str, str] | None:
    """返回 (去重键, 待发文本)；返回 None 表示忽略。"""
    extra = payload.get("extra") or {}
    sid = str(payload.get("session_id") or "")
    stamp = time.strftime("%m-%d %H:%M:%S")
    head = f"⏱ {stamp}"
    meta = meta_lines(sid, _s(extra.get("platform")), _s(payload.get("cwd")))

    if event == "post_llm_call":
        reply = str(extra.get("assistant_response") or "")
        if not reply.strip():
            return None
        # Preserve structure for the local Markdown renderer, but never send code blocks.
        body = _FENCE.sub("[代码块已省略]", reply).strip()
        if len(body) > SUMMARY_CHARS:
            body = body[:SUMMARY_CHARS].rstrip() + "\n\n…（已截断，请在 Hermes 查看完整回复）"
        if not body:
            return None
        if ONLY_TOOL_TURNS and turn_had_tool_calls(payload) is False:
            log(f"纯聊天轮次已跳过（会话 {sid[:8]}）")
            return None
        lines = [f"{head}　✅ 任务完成", *meta]
        user_msg = clean(str(extra.get("user_message") or ""), 120)
        if user_msg:
            lines.append(f"❓ 你问的：{user_msg}")
        lines.append("─" * 12)
        lines.append(body)
        return f"done:{sid}:{extra.get('turn_id') or ''}", "\n".join(lines)

    if event == "pre_approval_request":
        surface = str(extra.get("surface") or "")
        if surface == "smart":
            # approvals.mode=smart 时，每条被标记的命令都会先发一次 pre_approval_request，
            # 再由辅助模型（aux_llm）在 1-2 秒内自动放行，Hermes 界面从头到尾不出现审批卡片。
            # 推给用户只会造成“提醒我审批但哪里都找不到”的假警报，因此跳过；真需要人决策时
            # （smart 判 escalate 后的弹窗、或 gateway/desktop 的审批队列）surface 不是 smart，
            # 会照常推送。
            log(f"smart 自动审批已跳过（会话 {sid[:8]}）")
            return None
        command = clean(str(extra.get("command") or ""), 300)
        desc = clean(str(extra.get("description") or ""), 160)
        if not command and not desc:
            return None
        lines = [f"{head}　⚠️ 需要你审批", *meta]
        if desc:
            lines.append(f"📝 {desc}")
        lines.append("─" * 12)
        lines.append(f"$ {command}")
        lines.append("在 Hermes 里点允许/拒绝即可。")
        key = "approve:" + hashlib.sha1(f"{sid}{command}".encode()).hexdigest()[:16]
        return key, chr(10).join(lines)

    if event == "pre_tool_call":
        if str(payload.get("tool_name") or "") != "clarify":
            return None
        arg = payload.get("tool_input") or {}
        if not isinstance(arg, dict):
            return None
        questions = arg.get("questions")
        if not isinstance(questions, list):
            questions = [arg]  # Legacy notify_ask.py and older Hermes versions.
        rendered = []
        for item in questions[:5]:
            if not isinstance(item, dict):
                continue
            question = clean(str(item.get("question") or item.get("prompt") or ""), 400)
            if not question:
                continue
            section = [f"{len(rendered) + 1}. {question}"]
            if item.get("multi_select"):
                section.append("（可多选）")
            choices = item.get("options") or item.get("choices")
            if isinstance(choices, list) and choices:
                labels = [clean(str(c.get("label") or "") if isinstance(c, dict) else str(c), 80)
                          for c in choices[:6]]
                section.append("选项：" + " / ".join(labels))
            rendered.append("\n".join(section))
        if not rendered:
            return None
        lines = [f"{head}　❓ 需要你回答", *meta, "─" * 12, "\n\n".join(rendered),
                 "\n请回到 Hermes 回答；QQ 只提供提醒。"]
        identity = str(extra.get("tool_call_id") or "") or json.dumps(rendered, ensure_ascii=False)
        key = "ask:" + hashlib.sha256(f"{APPID}:{SANDBOX}:{sid}:{identity}".encode()).hexdigest()[:24]
        return key, "\n".join(lines)

    if event == "api_request_error":
        err = clean(str(extra.get("error_message") or extra.get("error") or "未知错误"), 300)
        lines = [f"{head}　❌ 出错了", *meta]
        if extra.get("provider") or extra.get("model"):
            lines.append(f"🤖 {extra.get('provider', '')} / {extra.get('model', '')}")
        lines.append("─" * 12)
        lines.append(err)
        key = "err:" + hashlib.sha1(f"{sid}{err}".encode()).hexdigest()[:16]
        return key, "\n".join(lines)

    if event == "on_session_end":
        if not NOTIFY_SESSION_END:
            return None
        lines = [f"{head}　⏹ 会话结束", *meta]
        if extra.get("reason"):
            lines.append(f"原因：{extra['reason']}")
        return f"end:{sid}", "\n".join(lines)

    return None


# ────────────────────────── 去重 ──────────────────────────

class Dedupe:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._seen = {k: float(v) for k, v in raw.items()}
        except (OSError, ValueError):
            pass

    def first_time(self, key: str, ttl: int = DEDUPE_TTL) -> bool:
        now = time.time()
        with self._lock:
            for k, ts in list(self._seen.items()):
                if now - ts > 24 * 3600:
                    self._seen.pop(k, None)
            last = self._seen.get(key)
            if last is not None and now - last < ttl:
                return False
            self._seen[key] = now
            self._flush_locked()
            return True

    def _flush_locked(self) -> None:
        try:
            STATE_PATH.write_text(json.dumps(self._seen), encoding="utf-8")
        except OSError:
            pass


DEDUPE = Dedupe()


# ────────────────────────── 处理队列 ──────────────────────────

_work: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=512)


def worker() -> None:
    while True:
        event, payload = _work.get()
        try:
            built = build_message(event, payload)
            if not built:
                continue
            key, text = built
            if not DEDUPE.first_time(key):
                log(f"重复事件已忽略（{event} / {key[:20]}）")
                continue
            QQ.send_notification(text)
        except Exception:                                  # noqa: BLE001
            log("处理事件异常:\n" + traceback.format_exc(), err=True)
        finally:
            _work.task_done()


def handle_event(event: str, payload: dict) -> None:
    try:
        _work.put_nowait((event, payload))
    except queue.Full:
        log("队列已满，丢弃事件", err=True)


# ────────────────────────── HTTP 接口 ──────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "hermes-qq-notify/1.0"

    def log_message(self, fmt: str, *args) -> None:        # 静音访问日志
        return

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                              # noqa: N802
        if self.path.startswith("/health"):
            self._json(200, {"ok": True, "service": "hermes-qq-notify", "uptime_s": int(time.time() - STARTED_AT),
                             "sent": SENT, "failed": FAILED, "last_error": LAST_ERROR,
                             "sandbox": SANDBOX, "queue": _work.qsize()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:                             # noqa: N802
        if not self.path.startswith("/event"):
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._json(413, {"error": "bad length"})
                return
            raw = b""
            while len(raw) < length:
                chunk = self.rfile.read(min(65536, length - len(raw)))
                if not chunk:
                    break
                raw += chunk
            if NOTIFY_SECRET:
                got = self.headers.get("X-Hermes-Signature-256", "")
                want = "sha256=" + hmac.new(NOTIFY_SECRET.encode(), raw, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(got, want):
                    log("签名校验失败，拒绝请求", err=True)
                    self._json(401, {"error": "bad signature"})
                    return
            payload = json.loads(raw.decode("utf-8", "replace") or "{}")
            event = str(payload.get("hook_event_name") or self.headers.get("X-Hermes-Event") or "")
            if not event:
                self._json(400, {"error": "missing event name"})
                return
            handle_event(event, payload)
            self._json(202, {"accepted": event})
        except Exception:                                  # noqa: BLE001
            log("接收事件失败:\n" + traceback.format_exc(), err=True)
            try:
                self._json(500, {"error": "internal"})
            except Exception:                              # noqa: BLE001
                pass


# ────────────────────────── 入口 ──────────────────────────

def preflight() -> bool:
    problems = []
    if not APPID or not SECRET:
        problems.append("QQ_APPID / QQ_SECRET 缺失（见 .env）")
    if not OPENID:
        problems.append("QQ_OPENID 缺失（见 .env）")
    if HOST != "127.0.0.1":
        problems.append("NOTIFY_HOST 必须为 127.0.0.1")
    if ENV.get("QQ_BOUND_APPID") != APPID or ENV.get("QQ_BOUND_SANDBOX") != ("1" if SANDBOX else "0"):
        problems.append("接收者尚未与当前 Bot / 环境配对，请运行 pair_bot.py")
    if not (HERMES_HOME / "state.db").exists():
        log("警告：会话标题数据库不存在，将使用会话 ID")
    if not NOTIFY_SECRET:
        problems.append("NOTIFY_SECRET 缺失；拒绝启动无签名服务")
    for p in problems:
        log("启动检查失败： " + p, err=True)
    return not problems


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        return 0 if preflight() else 2
    if "--test" in args:
        if not preflight():
            return 2
        return 0 if QQ.send_notification(f"⏱ {time.strftime('%m-%d %H:%M:%S')}　🔧 hermes-qq-notify 连通测试\n"
                            f"模式：{'沙箱' if SANDBOX else '正式'}　端口：{PORT}") else 1
    if "--selftest-event" in args:
        if not preflight():
            return 2
        fake = {"hook_event_name": "post_llm_call", "session_id": "selftest-session", "cwd": str(ROOT),
                "extra": {"turn_id": str(time.time()), "user_message": "自检",
                          "assistant_response": "这是一条自检通知：webhook 服务、会话解析与 QQ 投递链路均可用。"}}
        built = build_message("post_llm_call", fake)
        if not built:
            log("自检事件未生成消息", err=True)
            return 1
        return 0 if QQ.send_notification(built[1]) else 1

    if not preflight():
        return 2
    threading.Thread(target=worker, daemon=True, name="qq-notify-worker").start()
    try:
        QQ.token()      # 提前验证凭证；失败不致命（开机时网络可能还没就绪）
    except Exception as exc:                          # noqa: BLE001
        log(f"启动时获取 QQ token 失败，服务继续运行、发送时重试: {exc}", err=True)
    log(f"监听 http://{HOST}:{PORT}/event　沙箱={SANDBOX}　Hermes 目录={HERMES_HOME}")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("收到停止信号，退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())