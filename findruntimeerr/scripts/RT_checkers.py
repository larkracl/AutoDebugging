# RT_checkers.py (실시간 분석용 체커)
import astroid
import sys
import os
from typing import List, Dict, Any, Set
# utils.py는 공통으로 사용될 수 있음
from utils import get_type, is_compatible, collect_defined_variables

# --- 실시간 분석에 포함할 빠른 검사 함수들 ---

def check_zero_division_error(node: astroid.BinOp, errors: list):
    """ZeroDivisionError를 검사합니다."""
    if isinstance(node.op, astroid.Div):
        try:
            # infer() 호출은 성능에 영향을 줄 수 있으므로, 상수 0만 빠르게 확인
            if isinstance(node.right, astroid.Const) and node.right.value == 0:
                errors.append({
                    'message': 'Potential ZeroDivisionError: Division by zero',
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'ZeroDivisionError'
                })
            # 필요하다면 infer()를 사용한 더 자세한 검사를 여기에 추가 (성능 고려)
            # elif any(isinstance(val, astroid.Const) and val.value == 0 for val in node.right.infer()):
            #      ...
        except astroid.InferenceError:
            pass # 실시간 분석에서는 추론 실패 시 무시

def check_name_errors(node: astroid.NodeNG, defined_vars: Set[str], errors: list):
    """정의되지 않은 변수 사용(NameError)을 검사합니다."""
    if isinstance(node, astroid.Name) and isinstance(node.ctx, astroid.Load):
        if node.name not in defined_vars:
            # 실시간 분석에서는 lookup() 호출 생략 (성능 위주)
            # lookup()은 상위 스코프까지 확인하므로 비용이 클 수 있음
            # try:
            #     node.lookup(node.name)
            # except astroid.NotFoundError:
            errors.append({
                'message': f"Potential NameError: Name '{node.name}' might not be defined",
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'NameError'
            })
            # except Exception as e:
            #     print(f"Error during name lookup for '{node.name}': {e}", file=sys.stderr)


def check_infinite_loop(node: astroid.While, errors: list):
    """잠재적 무한 루프(while True:)를 검사합니다."""
    if isinstance(node.test, astroid.Const) and node.test.value is True:
        # 간단하게 break 문 존재 여부만 확인 (복잡한 제어 흐름 분석 생략)
        has_break = any(isinstance(child, astroid.Break) for child in node.body)
        # walk() 대신 node.body만 순회하여 성능 개선
        # has_break = False
        # for stmt in node.body:
        #     if isinstance(stmt, astroid.Break):
        #         has_break = True
        #         break
        if not has_break:
            errors.append({
                'message': 'Potential infinite loop: `while True` without `break` in the immediate body',
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'InfiniteLoop'
            })

def check_recursion_error(func_node: astroid.FunctionDef, errors: list):
    """재귀 호출(RecursionError)을 검사합니다."""
    # 함수 본문의 최상위 레벨에서 직접적인 재귀 호출만 검사 (성능 위주)
    for node in func_node.body:
        if isinstance(node, astroid.Call):
            if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                # 중복 오류 방지 (간단 체크)
                 is_duplicate = any(
                     err['errorType'] == 'RecursionError' and err['line'] == node.lineno
                     for err in errors if err['line'] >= func_node.fromlineno and err['line'] <= func_node.tolineno
                 )
                 if not is_duplicate:
                    errors.append({
                        'message': f"Potential RecursionError: Direct recursive call to function '{func_node.name}'",
                        'line': node.lineno,
                        'column': node.col_offset,
                        'errorType': 'RecursionError'
                    })
                    break # 함수당 하나만 보고

# 실시간 분석에서는 파일 존재 여부 확인은 비용이 크므로 제외 (선택 사항)
# def check_file_not_found_error(node: astroid.Call, errors: list): ...

# --- 상세 분석에만 포함될 함수들은 여기에 정의하지 않음 ---
# def check_type_error(node: astroid.BinOp, errors: list): ...
# def check_attribute_error(node: astroid.Attribute, errors: list): ...
# def check_index_error(node: astroid.Subscript, errors: list): ...
# def check_key_error(node: astroid.Subscript, errors: list): ...