"""hermes-qq-notify 守护进程：notifier.py 退出后自动拉起。

为什么需要它：pythonw 起来的 notifier 没有父进程看着，一旦异常退出（端口占用、
启动时网络未就绪、某次未捕获异常）就永远不会回来。此看门狗搭配当前用户的
Windows 登录启动入口使用，无需管理员权限。

行为：
  - 子进程正常跑了 >= 300 秒后退出 → 视为偶发故障，3 秒后重启
  - 连续快速失败 → 指数退避，最长 60 秒一次
  - 子进程 stdout/stderr 落到 logs/notifier.out.log，便于排查启动失败
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 关键：子进程必须用 pythonw.exe（无控制台）。用 python.exe 时，
# pythonw 父进程没有控制台，Windows 会给子进程新建一个黑窗口，
# 用户关掉窗口=杀死 notifier，看门狗再拉起又弹一个，形成"关不掉的窗口"。
PY = ROOT / ".venv" / "Scripts" / "python.exe"
PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
NOTIFIER = ROOT / "notifier.py"
CREATE_NO_WINDOW = 0x08000000  # Windows: 即使父进程无控制台也不再分配新控制台
LOGS = ROOT / "logs"
OUT = LOGS / "notifier.out.log"
SUP = LOGS / "supervisor.log"

HEALTHY_RUN_SECONDS = 300
BASE_DELAY = 3
MAX_DELAY = 60


def note(msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        if SUP.exists() and SUP.stat().st_size > 1_000_000:
            SUP.replace(SUP.with_suffix(".log.1"))
        with SUP.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def already_running() -> bool:
    """端口上已有健康的 hermes-qq-notify 就不重复启动（手动启动/自启撞车时很关键）。"""
    port = "8787"
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.startswith("NOTIFY_PORT="):
                port = line.split("=", 1)[1].strip() or port
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok")) and data.get("service") == "hermes-qq-notify"
    except Exception:                                  # noqa: BLE001
        return False


def main() -> int:
    # One watchdog per installation, including the startup/health-check race.
    import msvcrt
    LOGS.mkdir(parents=True, exist_ok=True)
    lock = (ROOT / '.supervisor.lock').open('a+b')
    lock.seek(0)
    if lock.read(1) == b'':
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return 0
    if not PY.exists():
        note(f"致命：找不到解释器 {PY}")
        return 2
    child_py = PYW if PYW.exists() else PY
    if already_running():
        note("已有实例在运行（/health 正常），本次启动跳过")
        return 0
    delay = BASE_DELAY
    while not (ROOT / '.stopped').exists():
        started = time.time()
        note("启动 notifier")
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            with OUT.open("ab") as out:
                code = subprocess.call(
                    [str(child_py), str(NOTIFIER)], cwd=str(ROOT),
                    stdout=out, stderr=subprocess.STDOUT,
                    creationflags=(CREATE_NO_WINDOW if sys.platform == "win32" else 0),
                    env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                )
        except Exception as exc:                      # noqa: BLE001
            code = -1
            note(f"拉起失败：{type(exc).__name__}: {exc}")
        ran = time.time() - started
        if ran >= HEALTHY_RUN_SECONDS:
            delay = BASE_DELAY
            note(f"notifier 退出（code={code}，运行 {int(ran)}s），{delay}s 后重启")
        else:
            note(f"notifier 很快退出（code={code}，仅 {int(ran)}s），退避 {delay}s")
            delay = min(delay * 2, MAX_DELAY)
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())