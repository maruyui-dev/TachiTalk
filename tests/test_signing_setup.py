"""Publisher key generation stays outside the repository and never overwrites a key."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.serialization import load_pem_private_key

from scripts.create_signing_key import create_keys, main, ROOT
from scripts.component_release import sign_payload
from app.updates.manifest import verify
from tests.test_updates import bundle


class SigningSetupTests(unittest.TestCase):
    def setUp(self):
        # Model an external signing directory and repository within an owned QA fixture.
        # External directory probes returned WinError 5 on this host. No production key is generated.
        (ROOT / 'work').mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=ROOT / 'work')
        self.addCleanup(self.temp.cleanup)
        fixture = Path(self.temp.name).resolve()
        self.repository = fixture / 'repository'
        self.repository.mkdir()
        repository = patch('scripts.create_signing_key.ROOT', self.repository)
        repository.start()
        self.addCleanup(repository.stop)
        self.directory = fixture / 'test-only-keys'

    def test_encrypted_private_key_matches_public_client_configuration(self):
        password = b'obviously-fake-test-password'
        private, public = create_keys(self.directory, 'test-only', password)
        self.assertTrue(private.is_file(), '必须生成加密私钥文件')
        self.assertTrue(public.is_file(), '必须生成客户端公钥配置')
        encoded = private.read_bytes()
        self.assertIn(b'ENCRYPTED PRIVATE KEY', encoded)
        with self.assertRaises(TypeError):
            load_pem_private_key(encoded, None)
        payload, _ = bundle()
        with patch.dict('os.environ', {'TACHITALK_SIGNING_PASSWORD': password.decode()}):
            envelope = sign_payload(payload, private, 'test-only')
        self.assertEqual(verify(envelope, json.loads(public.read_text())), payload)

    def test_existing_key_directory_is_preserved(self):
        self.directory.mkdir()
        original = self.directory / 'release-1.pem'
        original.write_bytes(b'existing key sentinel')
        with self.assertRaises(FileExistsError):
            create_keys(self.directory, 'release-1', b'obviously-fake-test-password')
        self.assertEqual(original.read_bytes(), b'existing key sentinel')

    def test_signing_prompts_in_local_terminal_but_never_waits_for_ci_input(self):
        password = b'obviously-fake-test-password'
        private, public = create_keys(self.directory, 'test-only', password)
        payload, _ = bundle()
        with patch.dict('os.environ', {'TACHITALK_SIGNING_PASSWORD': ''}), \
                patch('scripts.component_release.sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, '交互终端'):
                sign_payload(payload, private, 'test-only')
        with patch.dict('os.environ', {'TACHITALK_SIGNING_PASSWORD': ''}), \
                patch('scripts.component_release.sys.stdin.isatty', return_value=True), \
                patch('getpass.getpass', return_value=password.decode()) as prompt:
            envelope = sign_payload(payload, private, 'test-only')
        prompt.assert_called_once()
        self.assertEqual(verify(envelope, json.loads(public.read_text())), payload)

    def test_private_key_cannot_be_generated_inside_repository(self):
        with self.assertRaisesRegex(ValueError, '仓库'):
            create_keys(self.repository / 'signing-must-be-rejected', 'release-1', b'obviously-fake-test-password')

    def test_weak_password_and_invalid_key_id_are_rejected_before_writes(self):
        for key_id, password in [('release-1', b'short'), ('release-1', b'@@@'),
                                 ('../escape', b'obviously-fake-test-password')]:
            with self.subTest(key_id=key_id), self.assertRaises(ValueError):
                create_keys(self.directory, key_id, password)
            self.assertFalse(self.directory.exists())

    def test_at_sign_is_accepted_in_a_long_enough_password(self):
        password = b'QA-only-@@@-password'
        private, _ = create_keys(self.directory, 'test-only', password)
        key = load_pem_private_key(private.read_bytes(), password)
        self.assertEqual(len(key.public_key().public_bytes_raw()), 32)

    def test_unwritable_directory_fails_before_password_prompt_without_traceback(self):
        error = io.StringIO()
        with patch('sys.argv', ['create_signing_key.py', '--directory', str(self.directory)]), \
                patch('sys.stdin.isatty', return_value=True), \
                patch('pathlib.Path.mkdir', side_effect=PermissionError(13, 'Access denied')), \
                patch('getpass.getpass', return_value='obviously-fake-test-password') as prompt, \
                redirect_stderr(error):
            try:
                main()
            except SystemExit as exc:
                self.assertEqual(exc.code, 2)
            except OSError as exc:
                self.fail(f'目录权限错误必须转为明确的命令行错误，实际为 {type(exc).__name__}')
            else:
                self.fail('不可写目录必须失败')
        prompt.assert_not_called()
        self.assertIn('目录', error.getvalue())
        self.assertIn('PowerShell', error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())

    def test_check_directory_uses_real_writes_without_prompt_or_key_generation(self):
        output, error = io.StringIO(), io.StringIO()
        with patch('sys.argv', ['create_signing_key.py', '--directory', str(self.directory), '--check-directory']), \
                patch('sys.stdin.isatty', return_value=False), \
                patch('getpass.getpass') as prompt, \
                patch('scripts.create_signing_key.Ed25519PrivateKey.generate') as generate, \
                redirect_stdout(output), redirect_stderr(error):
            try:
                main()
            except SystemExit as exc:
                self.fail(f'不需要交互终端的目录预检应成功，实际退出码 {exc.code}: {error.getvalue()}')
        prompt.assert_not_called()
        generate.assert_not_called()
        self.assertIn('可写', output.getvalue())
        self.assertFalse(self.directory.exists(), '预检须移除自己创建的空目标目录，允许随后正常生成')

    def test_password_mismatch_releases_only_empty_reserved_directory(self):
        with patch('sys.argv', ['create_signing_key.py', '--directory', str(self.directory)]), \
                patch('sys.stdin.isatty', return_value=True), \
                patch('getpass.getpass', side_effect=['obviously-fake-test-password', 'different-test-password']), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.directory.exists())

    def test_file_write_denied_also_fails_before_password_prompt(self):
        with patch('sys.argv', ['create_signing_key.py', '--directory', str(self.directory)]), \
                patch('sys.stdin.isatty', return_value=True), \
                patch('pathlib.Path.open', side_effect=PermissionError(13, 'File write denied')), \
                patch('getpass.getpass') as prompt, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)
        prompt.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_cancelled_prompt_removes_only_empty_destination(self):
        with patch('sys.argv', ['create_signing_key.py', '--directory', str(self.directory)]), \
                patch('sys.stdin.isatty', return_value=True), \
                patch('getpass.getpass', side_effect=KeyboardInterrupt), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 130)
        self.assertFalse(self.directory.exists())

    def test_partial_key_write_is_preserved_and_retry_cannot_overwrite_it(self):
        original_open = os.open

        def fail_public_file(path, *args, **kwargs):
            if Path(path).name == 'release_keys.json':
                raise PermissionError(13, 'Simulated public file write failure')
            return original_open(path, *args, **kwargs)

        with patch('os.open', side_effect=fail_public_file):
            with self.assertRaises(PermissionError):
                create_keys(self.directory, 'test-only', b'obviously-fake-test-password')
        original = (self.directory / 'test-only.pem').read_bytes()
        self.assertIn(b'ENCRYPTED PRIVATE KEY', original)
        with self.assertRaises(FileExistsError):
            create_keys(self.directory, 'test-only', b'obviously-fake-test-password')
        self.assertEqual((self.directory / 'test-only.pem').read_bytes(), original)
