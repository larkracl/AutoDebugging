# static_analyze.py

import sys
import json

from core import analyze_code  # core.py에서 analyze_code 함수를 import

if __name__ == '__main__':
    code = sys.stdin.read()
    errors = analyze_code(code, mode='static')  # 'static' 모드로 상세 분석 실행
    print(json.dumps(errors))