# main.py
import sys
import json
import subprocess
import os

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
        # 오류 발생 시에도 errors와 call_graph 키를 포함하는 JSON 출력
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
            check=True, # check=True는 그대로 유지하여 오류 시 예외 발생
            timeout=15, # 타임아웃 약간 증가
            cwd=script_dir # 작업 디렉토리 설정
        )
        # stderr가 있다면 로그로 남김 (오류가 아니어도 디버깅 정보 출력 가능)
        if result.stderr:
             print(f"Stderr from {os.path.basename(script_path)}:\n{result.stderr}", file=sys.stderr)
        # stdout만 출력 (JSON 결과)
        print(result.stdout)

    except subprocess.CalledProcessError as e:
        # check=True로 인해 오류 발생 시 여기로 옴
        # stderr 내용을 포함하여 오류 JSON 생성
        print(json.dumps({
            "errors": [{
                "message": f"Error in analysis script ({os.path.basename(script_path)}): Process exited with code {e.returncode}. Stderr: {e.stderr.strip()}", # stderr 추가
                "line": 1, "column": 1, "errorType": "AnalysisScriptError",
                # "stderr": e.stderr # 위 메시지에 포함시킴
            }],
            "call_graph": None
        }))
    except subprocess.TimeoutExpired:
        # ... (TimeoutError 처리 동일) ...
        print(json.dumps({
            "errors": [{"message": f"Analysis script ({os.path.basename(script_path)}) timed out.", "line": 1, "column": 1, "errorType": "AnalysisTimeoutError"}],
            "call_graph": None
        }))
    except Exception as e:
        # ... (UnexpectedError 처리 동일) ...
        print(json.dumps({
            "errors": [{"message": f"Unexpected error in main.py: {e}", "line": 1, "column": 1, "errorType": "UnexpectedError"}],
            "call_graph": None
        }))

if __name__ == '__main__':
    main()