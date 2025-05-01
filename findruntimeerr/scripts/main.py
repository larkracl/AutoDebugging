# main.py
import sys
import json
import os
import traceback

# 현재 스크립트 디렉토리를 sys.path에 추가
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# core 모듈 import 시도 및 오류 처리
try:
    # parso 기반으로 수정된 core.py를 import
    from core import analyze_code
except ImportError as e:
    error_output = {"errors": [{"message": f"ImportError: {e}. Check sys.path and module locations.", "line": 1, "column": 1, "errorType": "ImportError"}], "call_graph": None}
    print(json.dumps(error_output))
    print(f"FATAL: ImportError in main.py: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
except Exception as e: # 다른 종류의 import 에러
    error_output = {"errors": [{"message": f"Unexpected Import Error: {e}.", "line": 1, "column": 1, "errorType": "ImportError"}], "call_graph": None}
    print(json.dumps(error_output))
    print(f"FATAL: Unexpected Import Error in main.py: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

def main():
    try:
        code = sys.stdin.read()
        mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

        # 동적 분석은 별도 처리
        if mode == 'dynamic':
            print(json.dumps({"errors": [{"message": "Dynamic analysis not implemented", "line": 1, "column": 1, "errorType": "NotImplementedError"}], "call_graph": None}))
            return

        try:
            # parso 기반 analyze_code 호출
            analysis_result = analyze_code(code, mode=mode)
        except Exception as e:
            print(f"Critical error during analyze_code call: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            analysis_result = {"errors": [{"message": f"Critical error during analysis: {e}", "line": 1, "column": 1, "errorType": "CoreAnalysisError"}], "call_graph": None}

        print(json.dumps(analysis_result))

    except Exception as e:
        print(f"FATAL error in main function: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"errors": [{"message": f"Fatal error in main: {e}", "line": 1, "column": 1, "errorType": "FatalMainError"}], "call_graph": None}))
        sys.exit(1)

if __name__ == '__main__':
    main()