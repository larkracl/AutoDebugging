# main.py
import sys
import os
import json
import subprocess

# --- sys.path 수정 ---
# main.py 파일이 있는 디렉토리의 절대 경로를 얻음
script_dir = os.path.dirname(os.path.abspath(__file__))
# sys.path에 이 디렉토리가 없으면 추가
if script_dir not in sys.path:
    sys.path.append(script_dir)
# ---------------------

# 이제 core, utils, checkers 등을 import 할 수 있어야 함
try:
    # 이 import 문은 실제 분석 로직을 실행하는 하위 스크립트(static_analyze.py 등)에서
    # 필요하므로 main.py 자체에서는 필요 없을 수 있습니다.
    # 하지만 sys.path가 올바르게 설정되었는지 확인하는 용도로 남겨둘 수 있습니다.
    # 또는 하위 스크립트 실행 전 sys.path 설정을 확인하는 로깅 추가
    print(f"main.py: Current sys.path includes script_dir: {script_dir in sys.path}", file=sys.stderr)
    print(f"main.py: sys.path = {sys.path}", file=sys.stderr) # 디버깅용 sys.path 전체 출력
except ImportError as e:
    # 만약 여기서 import 에러가 난다면 sys.path 설정에 문제가 있는 것
    print(json.dumps({
        "errors": [{"message": f"Critical Error: Failed to setup sys.path correctly in main.py. Cannot import core modules. Details: {e}",
                    "line": 1, "column": 1, "errorType": "InternalImportError"}],
        "call_graph": None
    }))
    sys.exit(1) # 비정상 종료

def main():
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

    script_to_run = None

    if mode == 'static':
        script_to_run = os.path.join(script_dir, 'static_analyze.py')
    elif mode == 'dynamic':
        script_to_run = os.path.join(script_dir, 'dynamic_analyze.py')
    elif mode == 'realtime':
        script_to_run = os.path.join(script_dir, 'RT_analyze.py')

    result_json = {"errors": [], "call_graph": None}

    if script_to_run is None:
        result_json["errors"].append({
            "message": f"Invalid mode: {mode}",
            "line": 1, "column": 1, "errorType": "InvalidModeError"
        })
        print(json.dumps(result_json))
        return

    try:
        # --- subprocess.run 호출 시 환경 변수 전달 (선택적이지만 더 안정적) ---
        # 현재 sys.path를 자식 프로세스도 알 수 있도록 PYTHONPATH 환경 변수 설정
        env = os.environ.copy()
        # script_dir를 PYTHONPATH의 맨 앞에 추가
        current_pythonpath = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = f"{script_dir}{os.pathsep}{current_pythonpath}"
        print(f"main.py: Setting PYTHONPATH for subprocess: {env['PYTHONPATH']}", file=sys.stderr)

        result = subprocess.run(
            [sys.executable, script_to_run], # 'python3' 대신 현재 실행 중인 인터프리터 사용
            input=code,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
            cwd=script_dir, # cwd는 유지해도 좋음
            env=env # 수정된 환경 변수 전달
        )
        # --- ---

        if result.stderr:
             print(f"Stderr from {os.path.basename(script_to_run)}:\n{result.stderr}", file=sys.stderr)

        if result.stdout.strip():
            try:
                script_output = json.loads(result.stdout)
                if isinstance(script_output.get("errors"), list):
                     result_json["errors"] = script_output["errors"]
                if "call_graph" in script_output:
                     result_json["call_graph"] = script_output["call_graph"]
            except json.JSONDecodeError as json_err:
                 result_json["errors"].append({
                     "message": f"Error decoding JSON from {os.path.basename(script_to_run)}: {json_err}. Output: {result.stdout[:100]}...",
                     "line": 1, "column": 1, "errorType": "JSONDecodeError"
                 })

    # ... (CalledProcessError, TimeoutExpired, Exception 처리 동일) ...
    except subprocess.CalledProcessError as e:
        result_json["errors"].append({
            "message": f"Analysis script ({os.path.basename(script_to_run)}) failed (Exit Code {e.returncode}). Stderr: {e.stderr.strip() if e.stderr else 'N/A'}", # stderr None 체크
            "line": 1, "column": 1, "errorType": "AnalysisScriptError",
        })
    except subprocess.TimeoutExpired:
        result_json["errors"].append({
            "message": f"Analysis script ({os.path.basename(script_to_run)}) timed out.",
            "line": 1, "column": 1, "errorType": "AnalysisTimeoutError"
        })
    except Exception as e:
        import traceback
        print(f"Unexpected error in main.py: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        result_json["errors"].append({
            "message": f"Unexpected error in main.py: {e}",
            "line": 1, "column": 1, "errorType": "UnexpectedError"
        })

    print(json.dumps(result_json))


if __name__ == '__main__':
    main()