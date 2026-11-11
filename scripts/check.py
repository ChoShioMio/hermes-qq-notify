"""Run the unit suite offline, without QQ or Hermes business environment variables."""
from pathlib import Path
import os
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in tuple(os.environ):
    if key.startswith(('QQ_', 'NOTIFY_', 'HERMES_')) or key in ('SUMMARY_CHARS', 'ONLY_TOOL_TURNS'):
        os.environ.pop(key, None)


def deny_network(*args, **kwargs):
    raise AssertionError('Network access is disabled during offline regression')


if __name__ == '__main__':
    socket.getaddrinfo = deny_network
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
