#!/usr/bin/env python
"""手动推送一条「需要你回答」事件到 hermes-qq-notify。

保留为手动备用：当前本机 Hermes 已经通过工具中间件为 clarify 派发
pre_tool_call；接收端兼容 questions[] 后已实测自动推送，不需要手工补发。
历史版本曾绕过该 hook，升级后应核对真实调用链，不根据 inline 身份推断。
本脚本只验证手动投递，不能证明 Hermes 自动提问事件生效。

用法：
    python notify_ask.py --question "要现在重启桌面端吗？" --options "是,稍后"
    python notify_ask.py -q "..." --session-id 20261023_163605_07d68e
"""
import argparse
import hashlib
import hmac
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent


def load_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description="推一条『需要你回答』到 QQ")
    ap.add_argument("-q", "--question", required=True)
    ap.add_argument("-o", "--options", default="", help="逗号分隔，如 是,稍后")
    ap.add_argument("-s", "--session-id", default="manual")
    ap.add_argument("-p", "--platform", default="desktop")
    args = ap.parse_args()

    env = load_env()
    secret = (env.get("NOTIFY_SECRET") or "").encode()
    if not secret:
        print("缺少 NOTIFY_SECRET（见项目 .env）", file=sys.stderr)
        return 2
    port = env.get("NOTIFY_PORT") or "8787"
    host = env.get("NOTIFY_HOST") or "127.0.0.1"

    options = [{"label": o.strip()} for o in args.options.split(",") if o.strip()]
    payload = {
        "hook_event_name": "pre_tool_call",
        "session_id": args.session_id,
        "tool_name": "clarify",
        "tool_input": {"question": args.question, "options": options},
        "extra": {"platform": args.platform, "source": "notify_ask.py"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/event",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Hermes-Event": "pre_tool_call",
            "X-Hermes-Signature-256": "sha256="
            + hmac.new(secret, body, hashlib.sha256).hexdigest(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"HTTP {resp.status} {resp.read().decode('utf-8', 'replace')[:200]}")
    except Exception as exc:  # noqa: BLE001 - 命令行工具，直接把原因打出来
        print(f"推送失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())