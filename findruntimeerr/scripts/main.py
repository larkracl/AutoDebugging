# main.py
import sys
import os
import json
import subprocess
import traceback # traceback 추가

# --- sys.path 수정 (절대 경로 사용) ---
# Dev Container 내부의 scripts 디렉토리 절대 경로
# 컨테이너 내부 작업 디렉토리가 /app 이고, findruntimeerr가 /app/findruntimeerr로 마운트됨
script_dir_in_container = '/app/findruntimeerr/scripts'
# sys.path에 이 디렉토리가 없으면 추가 (리스트 맨 앞에 추가하여 우선순위 높임)
if script_dir_in_container not in sys.path:
    sys.path.insert(0, script_dir_in_container)
# --------------------------------------

# 디버깅용 로그: sys.path 수정 후 상태 출력
print(f"main.py: sys.path modified: {script_dir_in_container in sys.path}", file=sys.stderr)
print(f"main.py: sys.path = {sys.path}", file=sys.stderr)

try:
    from core import analyze_code # 이제 core 모듈을 찾을 수 있어야 함
except ImportError as e:
    # Import 실패 시 오류 정보 JSON 출력 및 종료
    error_output = {"errors": [{"message": f"ImportError: {e}. Failed to import core module. Check sys.path and file existence in '{script_dir_in_container}'.",
                                "line": 1, "column": 1, "errorType": "InternalImportError"}], "call_graph": None}
    print(json.dumps(error_output))
    print(f"FATAL: ImportError in main.py: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr) # 상세 트레이스백 출력
    sys.exit(1) # 오류 종료 코드 반환
except Exception as e: # 다른 종류의 import 에러
    error_output = {"errors": [{"message": f"Unexpected Import Error: {e}.", "line": 1, "column": 1, "errorType": "InternalImportError"}], "call_graph": None}
    print(json.dumps(error_output))
    print(f"FATAL: Unexpected Import Error in main.py: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)


def main():
    # --- main 함수 전체를 try...except로 감싸서 모든 예외 로깅 ---
    try:
        code = sys.stdin.read()
        mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

        # 이제 main.py가 직접 core.analyze_code를 호출하므로,
        # 하위 스크립트(static_analyze.py, RT_analyze.py) 실행 로직은 제거됨.

        analysis_result = {"errors": [], "call_graph": None} # 기본 결과 구조

        # 동적 분석은 별도 처리
        if mode == 'dynamic':
            # TODO: dynamic_analyze.py 실행 또는 관련 로직 호출
            print(json.dumps({"errors": [{"message": "Dynamic analysis not implemented", "line": 1, "column": 1, "errorType": "NotImplementedError"}], "call_graph": None}))
            return

        # core.py의 analyze_code 직접 호출
        # 이 함수 내부에서 mode에 따라 적절한 체커가 로드됨
        try:
            analysis_result = analyze_code(code, mode=mode)
        except Exception as e: # analyze_code 내부에서 예외 발생 시
            print(f"Error during core analysis (mode={mode}): {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            analysis_result["errors"].append({"message": f"Error during core analysis: {e}", "line": 1, "column": 1, "errorType": "CoreAnalysisError"})
            # call_graph는 None으로 유지

        # 최종 결과 출력
        print(json.dumps(analysis_result))

    except Exception as e: # main 함수 자체의 예외 처리
        print(f"FATAL error in main function: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # stdout으로는 최소한의 오류 JSON 출력 시도
        print(json.dumps({"errors": [{"message": f"Fatal error in main: {e}", "line": 1, "column": 1, "errorType": "FatalMainError"}], "call_graph": None}))
        sys.exit(1) # 오류 종료 코드 반환

if __name__ == '__main__':
    main()