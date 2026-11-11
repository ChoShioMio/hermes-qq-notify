"""One-shot private-message pairing for a NEW bot; never reuse another AppID's OpenID.

Only the exact challenge is inspected; unrelated events are discarded, never logged.
Credentials are written to the local .env only after a matching private message arrives.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import time
import urllib.request

ROOT = Path(__file__).resolve().parent


def recipient_for(event: dict, challenge: str) -> str | None:
    if event.get('op') != 0 or event.get('t') != 'C2C_MESSAGE_CREATE':
        return None
    data = event.get('d') or {}
    if not isinstance(data, dict) or str(data.get('content') or '').strip() != challenge:
        return None
    author = data.get('author') or {}
    value = author.get('user_openid') if isinstance(author, dict) else None
    return value if isinstance(value, str) and value else None


def read_credentials(path: Path) -> tuple[str, str]:
    rows = [s.strip() for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip() and not s.lstrip().startswith('#')]
    if len(rows) == 2 and rows[0].isdigit() and '=' not in rows[1]:
        return rows[0], rows[1]
    values = {}
    for row in rows:
        if '=' in row:
            key, value = row.split('=', 1)
            values[key.strip()] = value.strip()
    appid, secret = values.get('QQ_APPID', ''), values.get('QQ_SECRET', '')
    if not appid.isdigit() or not secret:
        raise ValueError('Expected AppID then AppSecret on two lines, or QQ_APPID/QQ_SECRET keys')
    return appid, secret


def save_binding(path: Path, values: dict[str, str]) -> None:
    """Preserve unrelated settings, remove old credential keys, atomic replacement."""
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    kept = [line for line in lines if line.split('=', 1)[0].strip() not in values]
    text = '\n'.join(kept + [f'{key}={value}' for key, value in values.items()]) + '\n'
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def main() -> int:
    import websocket
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--environment', choices=['production', 'sandbox'], required=True)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    appid, secret = read_credentials(args.credentials)
    base = 'https://sandbox.api.sgroup.qq.com' if args.environment == 'sandbox' else 'https://api.sgroup.qq.com'
    body = json.dumps({'appId': appid, 'clientSecret': secret}).encode()
    req = urllib.request.Request('https://bots.qq.com/app/getAppAccessToken', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        token = json.loads(response.read(65536)).get('access_token')
    if not token:
        print('TOKEN_REJECTED', flush=True)
        return 2
    req = urllib.request.Request(base + '/gateway/bot', headers={'Authorization': 'QQBot ' + token, 'X-Union-Appid': appid})
    with urllib.request.urlopen(req, timeout=20) as response:
        gateway = json.loads(response.read(65536))
    url = gateway.get('url', '')
    if not url.startswith('wss://'):
        print('NO_GATEWAY_URL', flush=True)
        return 2
    ws = websocket.create_connection(url, timeout=2)
    challenge = '绑定通知 ' + secrets.token_hex(3).upper()
    deadline = time.monotonic() + args.timeout
    beat_at, interval, seq = float('inf'), 30.0, None
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= beat_at:
                ws.send(json.dumps({'op': 1, 'd': seq}))
                beat_at = now + interval
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                print('GATEWAY_CLOSED; environment or event subscription must be checked', flush=True)
                return 2
            if isinstance(raw, bytes):
                # Close frames expose only the public close code, not raw event contents.
                print('GATEWAY_BINARY_OR_CLOSE', flush=True)
                return 2
            event = json.loads(raw)
            seq = event.get('s', seq)
            if event.get('op') == 10:
                interval = float(event['d']['heartbeat_interval']) / 1000
                beat_at = time.monotonic() + interval
                ws.send(json.dumps({'op': 2, 'd': {'token': 'QQBot ' + token, 'intents': 1 << 25, 'shard': [0, 1], 'properties': {}}}))
            elif event.get('op') in (7, 9):
                print('GATEWAY_RECONNECT_OR_INVALID_SESSION', flush=True)
                return 2
            elif event.get('t') == 'READY':
                print(f'READY environment={args.environment}', flush=True)
                print('SEND_TO_NEW_BOT: ' + challenge, flush=True)
            recipient = recipient_for(event, challenge)
            if recipient:
                save_binding(ROOT / '.env', {
                    'QQ_APPID': appid, 'QQ_SECRET': secret, 'QQ_OPENID': recipient,
                    'QQ_SANDBOX': '1' if args.environment == 'sandbox' else '0',
                    'QQ_BOUND_APPID': appid, 'QQ_BOUND_SANDBOX': '1' if args.environment == 'sandbox' else '0',
                })
                # Verify the exact file target without printing credentials or identity.
                stored = (ROOT / '.env').read_text(encoding='utf-8')
                if not all(f'{key}={value}\n' in stored for key, value in {'QQ_APPID': appid, 'QQ_SECRET': secret, 'QQ_OPENID': recipient}.items()):
                    raise RuntimeError('binding verification failed')
                print('PAIRED: new credentials and new recipient saved; no notification sent', flush=True)
                return 0
    finally:
        ws.close()
    print('PAIR_TIMEOUT; configuration unchanged', flush=True)
    return 3


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # HTTP errors may contain secrets in request paths. Do not dump raw exceptions.
        print('PAIR_FAILED ' + type(exc).__name__, flush=True)
        raise SystemExit(2)
