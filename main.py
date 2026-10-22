"""TachiTalk统一启动入口：在已激活的虚拟环境中运行本文件。"""
from app.bootstrap import main


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--release-check':
        try:
            from app.release_check import run
            result = run(sys.argv[2])
        except Exception as error:
            import json
            from pathlib import Path
            Path(sys.argv[2]).write_text(json.dumps({'ok': False, 'error': f'{type(error).__name__}: {error}'}), encoding='utf-8')
            result = 1
        raise SystemExit(result)
    raise SystemExit(main())
