# dynamic_analyze.py

import sys
import json


def analyze_code_dynamic(code: str) -> list:
    """
    (미구현) 동적 분석을 수행합니다.
    """
    # TODO: 동적 분석 로직 구현 (예: pdb 사용, 코드 실행 및 결과 관찰)
    errors = []
    # 예시: 더미 오류 데이터
    # errors.append({
    #     "message": "Dynamic analysis not implemented yet.",
    #     "line": 1,
    #     "column": 1,
    #     "errorType": "DynamicAnalysisNotImplemented",
    # })
    return errors


if __name__ == '__main__':
    code = sys.stdin.read()
    errors = analyze_code_dynamic(code)  # 동적 분석 함수 호출 (현재는 빈 리스트 반환)
    print(json.dumps(errors))