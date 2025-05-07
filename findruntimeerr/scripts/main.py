# main.py (Mode 인자 전달 복원)
import sys
import json
import os
import traceback

# 현재 스크립트 디렉토리를 sys.path에 추가
# 이 방법은 스크립트가 다른 위치에서 심볼릭 링크 등으로 실행될 때 문제가 될 수 있음
# 좀 더 견고한 방법 고려 가능 (예: __file__ 기준 상대 경로)
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# core 모듈 import 시도 및 오류 처리
try:
    # Parso + Astroid 병행 버전 core import
    from core import analyze_code
except ImportError as e:
    # Import 실패 시 오류 JSON 출력 (call_graph: None 포함)
    # 오류 메시지에 트레이스백 포함하여 디버깅 용이하게
    tb_str = traceback.format_exc()
    error_output = {"errors": [{"message": f"ImportError: {e}.\nCheck sys.path and module locations.\n{tb_str}", "line": 1, "column": 0, "to_line": 1, "end_column": 1, "errorType": "ImportError"}], "call_graph": None}
    # JSON 출력은 항상 stdout, 로그는 stderr
    print(json.dumps(error_output, ensure_ascii=False), file=sys.stdout)
    print(f"FATAL: ImportError in main.py: {e}", file=sys.stderr)
    print(tb_str, file=sys.stderr)
    sys.exit(1) # 오류 종료
except Exception as e: # 다른 종류의 import 에러 (거의 발생 안 함)
    tb_str = traceback.format_exc()
    error_output = {"errors": [{"message": f"Unexpected Import Error: {e}.\n{tb_str}", "line": 1, "column": 0, "to_line": 1, "end_column": 1, "errorType": "ImportError"}], "call_graph": None}
    print(json.dumps(error_output, ensure_ascii=False), file=sys.stdout)
    print(f"FATAL: Unexpected Import Error in main.py: {e}", file=sys.stderr)
    print(tb_str, file=sys.stderr)
    sys.exit(1)

def main():
    """스크립트 메인 실행 함수."""
    analysis_result = {"errors": [], "call_graph": None} # 기본 결과 구조
    try:
        # stdin으로부터 전체 코드 읽기 (UTF-8 가정)
        # 에디터 인코딩과 일치해야 함
        code = sys.stdin.read()

        # 실행 인자로부터 mode 읽기 (기본값 'realtime')
        mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'
        # 유효한 모드인지 확인 (소문자로 비교)
        mode = mode.lower()
        if mode not in ('realtime', 'static'):
             print(f"Warning: Invalid mode '{sys.argv[1]}'. Defaulting to 'realtime'.", file=sys.stderr)
             mode = 'realtime'

        # 동적 분석은 이 스크립트에서 처리하지 않음
        if mode == 'dynamic':
             # 이 경우는 호출되지 않아야 함 (extension.ts에서 분기)
             print(json.dumps({"errors": [{"message": "Dynamic analysis mode is not handled by main.py.", "line": 1, "column": 0, "to_line": 1, "end_column": 1, "errorType": "ModeError"}], "call_graph": None}, ensure_ascii=False))
             return # 정상 종료 (오류는 아님)

        # analyze_code 호출 (mode 인자 전달)
        try:
            # analyze_code 함수가 예외를 내부적으로 처리하고 항상 dict 반환 가정
            analysis_result = analyze_code(code, mode=mode)
            # 반환값이 예상 형식이 아니면 오류 처리 (방어 코드)
            if not isinstance(analysis_result, dict) or 'errors' not in analysis_result or 'call_graph' not in analysis_result:
                 raise TypeError(f"analyze_code returned unexpected type: {type(analysis_result)}")

        except Exception as e:
            # analyze_code 함수 실행 중 예상 못한 심각한 오류 발생 시
            print(f"CRITICAL error during analyze_code call: {e}", file=sys.stderr)
            tb_str = traceback.format_exc()
            print(tb_str, file=sys.stderr)
            # 오류 발생 시에도 표준 JSON 형식 유지
            analysis_result = {
                "errors": [{
                    "message": f"Critical error during core analysis: {e}\n{tb_str}",
                    "line": 1, "column": 0, "to_line": 1, "end_column": 1,
                    "errorType": "CoreAnalysisCrash"
                }],
                "call_graph": None
            }

        # 최종 분석 결과(딕셔너리)를 JSON 문자열로 변환하여 stdout으로 출력
        try:
            # ensure_ascii=False 로 유니코드 문자(예: 한글 주석/문자열) 깨짐 방지
            # indent=None 으로 압축된 JSON 출력 (전송량 감소)
            json_output = json.dumps(analysis_result, ensure_ascii=False, indent=None)
            # stdout 인코딩 확인 및 명시적 인코딩 (필요시)
            # sys.stdout.reconfigure(encoding='utf-8') # Python 3.7+
            print(json_output, file=sys.stdout)
        except Exception as e:
             # JSON 직렬화 실패 시 (매우 드문 경우, 순환 참조 등)
             print(f"FATAL error serializing result to JSON: {e}", file=sys.stderr)
             tb_str = traceback.format_exc()
             print(tb_str, file=sys.stderr)
             fallback_error = {
                 "errors": [{
                     "message": f"Failed to serialize analysis result to JSON: {e}",
                     "line": 1, "column": 0, "to_line": 1, "end_column": 1,
                     "errorType": "JSONSerializationError"
                 }],
                 "call_graph": None
             }
             # 실패 시에도 JSON 형식으로 출력 시도
             print(json.dumps(fallback_error, ensure_ascii=False), file=sys.stdout)

    except Exception as e:
        # main 함수 내 다른 예외 발생 시 (stdin 읽기 실패 등)
        print(f"FATAL error in main function execution: {e}", file=sys.stderr)
        tb_str = traceback.format_exc()
        print(tb_str, file=sys.stderr)
        # 최후의 오류 JSON 출력
        fatal_error_output = {
            "errors": [{
                "message": f"Fatal error in script execution: {e}\n{tb_str}",
                "line": 1, "column": 0, "to_line": 1, "end_column": 1,
                "errorType": "FatalMainError"
            }],
            "call_graph": None
        }
        print(json.dumps(fatal_error_output, ensure_ascii=False), file=sys.stdout)
        sys.exit(1) # 오류 종료 코드 반환

if __name__ == '__main__':
    main()