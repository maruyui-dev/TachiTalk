"""Local publisher key setup. Never include private keys in a client build."""
import argparse
import base64
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import re
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def writable_directory(directory, key_id):
    """Reserve a fresh destination and test actual writes before reading secrets."""
    directory = Path(directory).resolve()
    if directory.is_relative_to(ROOT):
        raise ValueError('私钥必须保存在仓库之外的安全目录')
    if not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key_id):
        raise ValueError('key-id只能使用字母、数字、下划线和短横线')
    if directory.exists():
        raise FileExistsError('密钥目录已存在，拒绝覆盖；请保留原密钥或指定全新目录')
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        probe = directory / '.write-check'
        probe_created = False
        try:
            with probe.open('xb') as stream:
                probe_created = True
                stream.write(b'TachiTalk directory check; no key material\n')
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if probe_created:
                probe.unlink()
        yield directory
    finally:
        # Only our freshly created empty destination may be removed. Partial keys
        # and pre-existing parent directories are never deleted or overwritten.
        try:
            directory.rmdir()
        except OSError:
            pass


def _write_keys(directory, key_id, password):
    key = Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.BestAvailableEncryption(password))
    public = json.dumps({key_id: base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')},
                        indent=2).encode('utf-8') + b'\n'
    private_path, public_path = directory / f'{key_id}.pem', directory / 'release_keys.json'
    for path, content in ((private_path, encrypted), (public_path, public)):
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return private_path, public_path


def create_keys(directory, key_id, password):
    if not isinstance(password, bytes) or len(password) < 12:
        raise ValueError('私钥必须设置至少12字节的密码')
    with writable_directory(directory, key_id) as destination:
        return _write_keys(destination, key_id, password)


def main():
    parser = argparse.ArgumentParser(description='本地生成Ed25519发布密钥：加密私钥只写仓库外，不覆盖旧目录')
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--key-id', default='release-1')
    parser.add_argument('--check-directory', action='store_true', help='只检查目录写入权限，不询问密码、不生成密钥')
    args = parser.parse_args()
    if not args.check_directory and not sys.stdin.isatty():
        parser.error('请在本机交互终端运行，密码通过隐藏输入读取，不接受聊天或管道输入')
    try:
        with writable_directory(args.directory, args.key_id) as destination:
            if args.check_directory:
                print(f'目录可写：{destination}；没有生成密钥，预检结束会移除空目标目录。')
                return
            password = getpass.getpass('设置私钥密码（至少12字符，输入不可见）：')
            if len(password) < 12 or password != getpass.getpass('再次输入私钥密码：'):
                parser.error('密码太短或两次输入不一致')
            private, public = _write_keys(destination, args.key_id, password.encode('utf-8'))
    except (OSError, ValueError) as exc:
        parser.error(f'密钥目录操作失败：{args.directory}\n{exc}\n'
                     '请从开始菜单打开普通 PowerShell 重试，或选择可写的仓库外安全新目录。'
                     '如目录内已有文件，请保留检查；不会自动删除或覆盖已有密钥。')
    except (EOFError, KeyboardInterrupt):
        parser.exit(130, '\n已取消；保留已有文件，只移除本次创建的空目标目录。\n')
    print(f'加密私钥：{private}\n可公开的客户端公钥配置：{public}')
    print('只把公钥JSON加入项目。私钥与密码应分别安全备份；不要上传仓库或发到聊天中。')


if __name__ == '__main__':
    main()
