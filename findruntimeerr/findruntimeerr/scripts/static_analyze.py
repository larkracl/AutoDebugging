# static_analyze.py
import sys
import json

from core import analyze_code

if __name__ == '__main__':
    code = sys.stdin.read()
    errors = analyze_code(code, mode='static')  # 'static' 모드로 호출
    print(json.dumps(errors))