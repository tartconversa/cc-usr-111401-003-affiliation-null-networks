"""命令行入口：python -m app.opportunity 资料.json [配置.json]"""
import json
import sys
from pathlib import Path

from . import inspect

def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit('用法: python -m app.opportunity 资料JSON路径 [配置JSON路径]')
    payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    config = None
    if len(sys.argv) == 3:
        config = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    print(json.dumps(inspect(payload, config), ensure_ascii=False, allow_nan=False, indent=2))

if __name__ == '__main__':
    main()
