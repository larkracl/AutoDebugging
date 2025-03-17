# main.py
import sys
import json
import subprocess

def main():
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'  # 기본값: realtime

    if mode == 'static':
        script_path = 'static_analyze.py'
    elif mode == 'dynamic':
        script_path = 'dynamic_analyze.py'  # 아직 미구현
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
        # subprocess.run을 사용하여 Python 스크립트 실행
        result = subprocess.run(
            ['python3', script_path],  # Python 인터프리터와 스크립트 경로
            input=code,  # 표준 입력으로 코드 전달
            capture_output=True,  # 표준 출력/에러 캡처
            text=True,  # 텍스트 모드
            check=True,  # 오류 발생 시 예외 발생
            timeout=10 # 타임아웃 설정 (10초)
        )
        print(result.stdout)  # 분석 결과 (JSON) 출력

    except subprocess.CalledProcessError as e:
        # 하위 프로세스(analyze.py) 실행 중 오류 발생 시
        print(json.dumps([{
            "message": f"Error in analysis script ({script_path}): {e}",
            "line": 1,
            "column": 1,
            "errorType": "AnalysisScriptError",
            "stdout": e.stdout,  # analyze.py의 표준 출력 (있는 경우)
            "stderr": e.stderr   # analyze.py의 표준 에러 (있는 경우)
        }]))
    except subprocess.TimeoutExpired:
        print(json.dumps([{
            "message": f"Analysis script ({script_path}) timed out.",
            "line": 1,
            "column": 1,
            "errorType": "AnalysisTimeoutError",
        }]))
    except Exception as e: #기타 예외
        print(json.dumps([{
            "message": f"Unexpected error in main.py: {e}",
            "line": 1,
            "column": 1,
            "errorType": "UnexpectedError",
        }]))

if __name__ == '__main__':
    main()