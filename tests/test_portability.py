import os
import io
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class PortabilityTests(unittest.TestCase):
    def test_clean_source_copy_checks_fake_config_without_network_or_database(self):
        from configure import initialize
        from pair_bot import save_binding
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'fresh source'
            root.mkdir()
            source = Path(__file__).resolve().parents[1]
            for name in ('notifier.py', 'project_config.py', '.env.example'):
                shutil.copyfile(source / name, root / name)
            self.assertTrue(initialize(root))
            save_binding(root / '.env', {'QQ_APPID': 'fake-app', 'QQ_SECRET': 'fake-secret', 'QQ_OPENID': 'fake-user', 'QQ_SANDBOX': '0', 'QQ_BOUND_APPID': 'fake-app', 'QQ_BOUND_SANDBOX': '0', 'HERMES_HOME': str(root / 'absent-home')})
            env = {k: v for k, v in os.environ.items() if not k.startswith(('QQ_', 'NOTIFY_', 'HERMES_'))}
            program = 'import runpy, socket, sys; sys.argv=["notifier.py", "--check"]; socket.getaddrinfo=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network forbidden")); runpy.run_path("notifier.py",run_name="__main__")'
            result = subprocess.run([sys.executable, '-c', program], cwd=root, env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, 'fresh source config check failed')
            self.assertFalse((root / 'absent-home').exists())
            self.assertFalse((root / 'state.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher integration')
    def test_real_launcher_runs_from_relocated_unicode_directory(self):
        from manage_autostart import install
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '迁移 with spaces'
            root.mkdir()
            startup = Path(directory) / 'Startup'
            startup.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'autostart.vbs', root / 'autostart.vbs')
            (root / 'supervisor.py').write_text('from pathlib import Path\nimport json, os\nPath(__file__).with_name("launcher-result.json").write_text(json.dumps({"cwd": os.getcwd()}), encoding="utf-8")\n', encoding='utf-8')
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True, capture_output=True, timeout=30)
            result = root / 'launcher-result.json'
            for launcher in (root / 'autostart.vbs', install(root, startup)):
                subprocess.run(['cscript.exe', '//nologo', str(launcher)], check=True, capture_output=True, timeout=10)
                deadline = time.monotonic() + 10
                while not result.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertTrue(result.exists(), 'relocated launcher did not invoke fixture supervisor')
                self.assertEqual(Path(json.loads(result.read_text(encoding='utf-8'))['cwd']), root)
                result.unlink()

    def test_watchdog_does_not_mistake_another_service_for_our_listener(self):
        import supervisor
        with tempfile.TemporaryDirectory() as directory, patch.object(supervisor, 'ROOT', Path(directory)):
            with patch.object(supervisor.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"ok": true, "service": "another-service"}')):
                self.assertFalse(supervisor.already_running())
            with patch.object(supervisor.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"ok": true, "service": "hermes-qq-notify"}')):
                self.assertTrue(supervisor.already_running())

    def test_autostart_install_and_remove_are_scoped_and_support_unicode_paths(self):
        from manage_autostart import install, remove
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '项目 with spaces'
            root.mkdir()
            startup = Path(directory) / 'Startup'
            startup.mkdir()
            target = install(root, startup)
            text = target.read_text(encoding='utf-16')
            self.assertIn(str(root / 'autostart.vbs'), text)
            self.assertEqual(install(root, startup), target)
            self.assertTrue(remove(root, startup))
            self.assertFalse(target.exists())
            target.write_text('unrelated script', encoding='utf-8')
            with self.assertRaises(ValueError):
                install(root, startup)
            with self.assertRaises(ValueError):
                remove(root, startup)
            self.assertEqual(target.read_text(encoding='utf-8'), 'unrelated script')

    def test_config_initialization_generates_secret_and_never_overwrites(self):
        from configure import initialize
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('NOTIFY_SECRET=\nQQ_OPENID=\n', encoding='utf-8')
            self.assertTrue(initialize(root))
            text = (root / '.env').read_text(encoding='utf-8')
            secret = text.splitlines()[0].split('=', 1)[1]
            self.assertGreaterEqual(len(secret), 64)
            self.assertFalse(initialize(root))
            self.assertEqual((root / '.env').read_text(encoding='utf-8'), text)

    def test_hermes_home_resolves_override_and_windows_local_appdata(self):
        from project_config import hermes_home
        home = Path('test-user-home')
        self.assertEqual(hermes_home({'HERMES_HOME': 'custom-profile'}, home), Path('custom-profile'))
        self.assertEqual(hermes_home({'LOCALAPPDATA': 'local-appdata'}, home), Path('local-appdata') / 'hermes')
        self.assertEqual(hermes_home({}, home), home / '.hermes')

if __name__ == '__main__':
    unittest.main()
