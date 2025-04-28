# main.py
import sys
import json
import os
# core 모듈을 import (core.py가 같은 디렉토리에 있다고 가정)
try:
    from core import analyze_code
except ImportError:
    # 만약 다른 경로에 있다면 sys.path 수정 필요
    print("Error: Could not import 'core' module. Make sure core.py is in the same directory or Python path.", file=sys.stderr)
    sys.exit(1)

def main():
    code = sys.stdin.read()
    # mode는 'realtime', 'static', 'dynamic' 중 하나로 전달됨
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

    # 동적 분석은 아직 별도 처리 필요
    if mode == 'dynamic':
        # TODO: dynamic_analyze.py 실행 또는 관련 로직 호출
        print(json.dumps({"errors": [], "call_graph": None})) # 임시
        return

    # core.py의 analyze_code 직접 호출
    analysis_result = analyze_code(code, mode=mode)

    # 결과 출력
    print(json.dumps(analysis_result))


if __name__ == '__main__':
    main()