# main.py
import sys
import json
import subprocess
import os # 스크립트 경로를 위해 추가

def main():
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

    # 스크립트가 있는 디렉토리 경로
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if mode == 'static':
        script_path = os.path.join(script_dir, 'static_analyze.py')
    elif mode == 'dynamic':
        script_path = os.path.join(script_dir, 'dynamic_analyze.py')
    elif mode == 'realtime':
        script_path = os.path.join(script_dir, 'RT_analyze.py')
    else:
        print(json.dumps({
            "errors": [{"message": f"Invalid mode: {mode}", "line": 1, "column": 1, "errorType": "InvalidModeError"}],
            "call_graph": None
        }))
        return

    try:
        # 스크립트 실행 시 현재 디렉토리를 스크립트가 있는 디렉토리로 설정 (import 문제 방지)
        result = subprocess.run(
            ['python3', script_path],
            input=code,
            capture_output=True,
            text=True,
            check=True,
            timeout=15, # 타임아웃 약간 증가
            cwd=script_dir # 작업 디렉토리 설정
        )
        # 결과 출력 전에 stderr에 로그 출력 (디버깅용)
        if result.stderr:
             print(f"Stderr from {script_path}:\n{result.stderr}", file=sys.stderr)

        print(result.stdout)

    except subprocess.CalledProcessError as e:
        print(json.dumps({
            "errors": [{
                "message": f"Error in analysis script ({os.path.basename(script_path)}): Process exited with code {e.returncode}",
                "line": 1, "column": 1, "errorType": "AnalysisScriptError",
                "stderr": e.stderr
            }],
            "call_graph": None
        }))
    except subprocess.TimeoutExpired:
        print(json.dumps({
            "errors": [{"message": f"Analysis script ({os.path.basename(script_path)}) timed out.", "line": 1, "column": 1, "errorType": "AnalysisTimeoutError"}],
            "call_graph": None
        }))
    except Exception as e:
        print(json.dumps({
            "errors": [{"message": f"Unexpected error in main.py: {e}", "line": 1, "column": 1, "errorType": "UnexpectedError"}],
            "call_graph": None
        }))

if __name__ == '__main__':
    main()