# main.py
import sys
import json
import os

# 현재 스크립트 디렉토리를 sys.path에 추가
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

try:
    from core import analyze_code # core.py에서 analyze_code 함수 직접 import
except ImportError as e:
    print(json.dumps({"errors": [{"message": f"ImportError: {e}. Check sys.path and module locations.", "line": 1, "column": 1, "errorType": "ImportError"}], "call_graph": None}))
    sys.exit(1) # ImportError는 심각한 문제이므로 종료

def main():
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

    # 동적 분석은 아직 별도 처리 필요
    if mode == 'dynamic':
        # TODO: dynamic_analyze.py 실행 또는 관련 로직 호출
        print(json.dumps({"errors": [], "call_graph": None})) # 임시
        return

    # core.py의 analyze_code 직접 호출
    try:
        analysis_result = analyze_code(code, mode=mode)
    except Exception as e:
        # analyze_code 내부에서 예외를 잡지 못한 경우 (예: 심각한 내부 오류)
        import traceback
        print(f"Critical error during analyze_code call: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        analysis_result = {"errors": [{"message": f"Critical error during analysis: {e}", "line": 1, "column": 1, "errorType": "CoreAnalysisError"}], "call_graph": None}

    # 결과 출력
    print(json.dumps(analysis_result))


if __name__ == '__main__':
    main()