# scripts/main.py
import sys
import json
import os
import traceback

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from core import analyze_code
except ImportError as e:
    tb_str = traceback.format_exc()
    error_output = {"errors": [{"message": f"ImportError: {e}.\n{tb_str}", "line": 1, "column": 0, "errorType": "ImportError"}], "call_graph": None}
    print(json.dumps(error_output, ensure_ascii=False), file=sys.stdout)
    sys.exit(1)
except Exception as e:
    tb_str = traceback.format_exc()
    error_output = {"errors": [{"message": f"Unexpected Import Error: {e}.\n{tb_str}", "line": 1, "column": 0, "errorType": "ImportError"}], "call_graph": None}
    print(json.dumps(error_output, ensure_ascii=False), file=sys.stdout)
    sys.exit(1)

def main():
    """스크립트 메인 실행 함수."""
    analysis_result = {"errors": [], "call_graph": None}
    try:
        code = sys.stdin.read()
        mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'realtime'
        base_dir = sys.argv[2] if len(sys.argv) > 2 else None
        
        if mode not in ('realtime', 'static'):
             mode = 'realtime'

        try:
            analysis_result = analyze_code(code, mode=mode, base_dir=base_dir)
            if not isinstance(analysis_result, dict) or 'errors' not in analysis_result or 'call_graph' not in analysis_result:
                 raise TypeError(f"analyze_code returned unexpected type: {type(analysis_result)}")
        except Exception as e:
            tb_str = traceback.format_exc()
            analysis_result = {
                "errors": [{"message": f"Critical error during core analysis: {e}\n{tb_str}", "line": 1, "column": 0, "errorType": "CoreAnalysisCrash"}],
                "call_graph": None
            }

        try:
            json_output = json.dumps(analysis_result, ensure_ascii=False, indent=None)
            print(json_output, file=sys.stdout)
        except Exception as e:
             tb_str = traceback.format_exc()
             fallback_error = {"errors": [{"message": f"Failed to serialize result: {e}", "line": 1, "column": 0, "errorType": "JSONSerializationError"}], "call_graph": None}
             print(json.dumps(fallback_error, ensure_ascii=False), file=sys.stdout)

    except Exception as e:
        tb_str = traceback.format_exc()
        fatal_error_output = {"errors": [{"message": f"Fatal error in script execution: {e}\n{tb_str}", "line": 1, "column": 0, "errorType": "FatalMainError"}], "call_graph": None}
        print(json.dumps(fatal_error_output, ensure_ascii=False), file=sys.stdout)
        sys.exit(1)

if __name__ == '__main__':
    main()