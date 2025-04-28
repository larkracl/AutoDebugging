# static_analyze.py
import sys
import json
from core import analyze_code

if __name__ == '__main__':
    code = sys.stdin.read()
    analysis_result = analyze_code(code, mode='static') # 'static' 모드
    print(json.dumps(analysis_result))