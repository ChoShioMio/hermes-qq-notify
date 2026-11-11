"""Manage the current user's Windows logon entry. Never starts or stops the service."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'hermes-qq-notify.vbs'
MARKER = "' hermes-qq-notify managed logon launcher"


def launcher_text(root: Path) -> str:
    path = str(root.resolve() / 'autostart.vbs').replace('"', '""')
    return (MARKER + '\nSet sh = CreateObject("WScript.Shell")\n'
            'sh.Run "wscript.exe //nologo " & Chr(34) & "' + path + '" & Chr(34), 0, False\n')


def _owned(target: Path, root: Path) -> bool:
    raw = target.read_bytes()
    text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
    return text.startswith(MARKER) or (str(root.resolve() / 'supervisor.py') in text and 'pythonw.exe' in text)


def install(root: Path, startup: Path) -> Path:
    target = startup / NAME
    if target.exists() and not _owned(target, root):
        raise ValueError('Startup filename belongs to an unrelated script; refusing overwrite')
    text = launcher_text(root)
    target.write_text(text, encoding='utf-16')
    if target.read_text(encoding='utf-16') != text:
        raise OSError('Autostart verification failed')
    return target


def remove(root: Path, startup: Path) -> bool:
    target = startup / NAME
    if not target.exists():
        return False
    if not _owned(target, root):
        raise ValueError('Startup filename belongs to an unrelated script; refusing removal')
    target.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'remove', 'status'])
    args = parser.parse_args()
    if os.name != 'nt' or not os.environ.get('APPDATA'):
        parser.error('Windows with an APPDATA directory is required')
    startup = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    if not startup.is_dir():
        parser.error('Windows Startup folder is unavailable')
    if args.action == 'install':
        install(ROOT, startup)
        print('Logon autostart installed. Service was not started.')
    elif args.action == 'remove':
        removed = remove(ROOT, startup)
        print('Logon autostart removed. Run stop.cmd to stop the current service.' if removed else 'No logon entry exists.')
    else:
        print('Logon entry exists.' if (startup / NAME).exists() else 'Logon entry absent.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
