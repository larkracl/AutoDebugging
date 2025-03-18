# core.py
import astroid
from typing import List, Dict, Any, Set
from checkers import (
    check_name_errors,
    check_zero_division_error,
    check_type_error,
    check_attribute_error,
    check_index_error,
    check_key_error,
    check_infinite_loop,
    check_recursion_error,
    check_file_not_found_error,
    # check_..._dynamic  # 동적 분석 함수는 아직 미구현
)
from utils import collect_defined_variables


def analyze_code(code: str, mode: str = 'realtime') -> List[Dict[str, Any]]:
    """
    Python 코드를 분석하여 잠재적인 런타임 에러를 찾습니다.

    Args:
        code: 분석할 Python 코드 문자열.
        mode: 'realtime' (실시간 분석), 'static' (정적 분석), 'dynamic' (동적 분석).

    Returns:
        발견된 오류 정보 목록.
    """
    print(f"analyze_code called with mode: {mode}")  # 디버깅 출력
    try:
        tree = astroid.parse(code)
        print(f"AST parsed successfully: {tree.repr_tree()}")  # 디버깅 출력: AST 내용 확인
    except astroid.AstroidSyntaxError as e:
        print(f"SyntaxError: {e}") # 디버깅 출력
        return [{
            'message': f"SyntaxError: {e.msg}",
            'line': e.line,
            'column': e.col,
            'errorType': 'SyntaxError'
        }]
    except Exception as e:
        print(f"Exception during analysis: {e}")  # 디버깅 출력
        return [{
            "message": f"An error occurred during analysis: {e}",
            "line": 1,
            "column": 0,
            "errorType": "AnalysisError",
        }]

    errors = []

    # 함수별 분석
    for func_node in tree.body:
        if isinstance(func_node, astroid.FunctionDef):
            print(f"Analyzing function: {func_node.name}")  # 디버깅 출력
            _analyze_function(func_node, errors, mode)

    # 모듈 수준 분석
    if mode in ('static', 'dynamic','realtime'):  # dynamic은 아직 미구현, 모듈분석 추가
        print("Analyzing module...")  # 디버깅 출력
        _analyze_module(tree, errors)

    print(f"analyze_code returning errors: {errors}")  # 디버깅 출력
    return errors


def _analyze_function(func_node: astroid.FunctionDef, errors: list, mode: str):
    """함수 단위 분석."""
    print(f"_analyze_function called for: {func_node.name}")  # 디버깅 출력
    defined_vars: Set[str] = collect_defined_variables(func_node)
    print(f"Defined variables: {defined_vars}")  # 디버깅 출력

    # 재귀 호출 검사
    check_recursion_error(func_node, errors)

    # 함수 본문 분석
    for node in func_node.body:
        print(f"Analyzing node in function body: {node!r}")  # 디버깅 출력: 현재 노드
        check_name_errors(node, defined_vars, errors)  # 모든 모드에서 NameError 검사

        if mode == 'realtime':
            if isinstance(node, astroid.BinOp):
                check_zero_division_error(node, errors)  # ZeroDivisionError

        elif mode == 'static':
            if isinstance(node, astroid.BinOp):
                check_zero_division_error(node, errors)  # ZeroDivisionError
                check_type_error(node, errors)  # TypeError
            elif isinstance(node, astroid.Attribute):
                check_attribute_error(node, errors)  # AttributeError
            elif isinstance(node, astroid.Subscript):
                check_index_error(node, errors)  # IndexError
                check_key_error(node, errors)  # KeyError


def _analyze_module(module_node: astroid.Module, errors: list):
    """모듈 단위 분석."""
    print("_analyze_module called")  # 디버깅 출력
    for node in module_node.body:
        print(f"Analyzing node in module body: {node!r}") #디버깅 출력: 현재 노드
        if isinstance(node, astroid.Call) and isinstance(node.func, astroid.Name) and node.func.name == "open":
            check_file_not_found_error(node, errors)
        elif isinstance(node, astroid.While):
            check_infinite_loop(node, errors)  # 최상위 while 루프