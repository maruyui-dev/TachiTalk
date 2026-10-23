"""Run in the developer's secure signing environment, separate from package building."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.component_release import sign_payload
from app.updates.manifest import validate, verify, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--keys', type=Path, required=True, help='客户端内置的可信公钥JSON')
    parser.add_argument('--key-id', default='release-1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('签名输出已存在，拒绝覆盖')
    payload = validate(json.loads(args.payload.read_text(encoding='utf-8')))
    envelope = sign_payload(payload, os.environ['TACHITALK_SIGNING_KEY'], args.key_id)
    verify(envelope, json.loads(args.keys.read_text(encoding='utf-8')))
    atomic_json(args.output, envelope)


if __name__ == '__main__':
    main()
