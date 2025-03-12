# main.py
import sys
import json
import subprocess

def main():
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'

    if mode == 'static':
        script_path = 'static_analyze.py'
    elif mode == 'dynamic':
        script_path = 'dynamic_analyze.py'  # 미구현
    elif mode == 'realtime':
        script_path = 'RT_analyze.py'
    else:
        print(json.dumps([{
            "message": f"Invalid mode: {mode}",
            "line": 1,
            "column": 1,
            "errorType": "InvalidModeError",
        }]))
        return

    try:
        result = subprocess.run(
            ['python3', script_path],
            input=code,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        print(result.stdout)

    except subprocess.CalledProcessError as e:
        print(json.dumps([{
            "message": f"Error in analysis script ({script_path}): {e}",
            "line": 1,
            "column": 1,
            "errorType": "AnalysisScriptError",
            "stdout": e.stdout,
            "stderr": e.stderr
        }]))
    except subprocess.TimeoutExpired:
        print(json.dumps([{
            "message": f"Analysis script ({script_path}) timed out.",
            "line": 1,
            "column": 1,
            "errorType": "AnalysisTimeoutError",
        }]))
    except Exception as e:
        print(json.dumps([{
            "message": f"Unexpected error in main.py: {e}",
            "line": 1,
            "column": 1,
            "errorType": "UnexpectedError",
        }]))

if __name__ == '__main__':
    main()