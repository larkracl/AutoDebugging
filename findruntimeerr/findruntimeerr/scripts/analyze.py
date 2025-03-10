import astroid
import sys
import json
import os
from typing import Union, Optional, List, Set, Dict, Any


def analyze_code(code: str, mode: str = 'simple') -> List[Dict[str, Any]]:
    """
    Python 코드를 분석하여 잠재적인 런타임 에러를 찾습니다.

    Args:
        code: 분석할 Python 코드 문자열.
        mode: 'simple' (실시간 분석) 또는 'detailed' (상세 분석).

    Returns:
        발견된 오류 정보 목록. 각 오류 정보는 딕셔너리 형태입니다.
    """
    try:
        tree = astroid.parse(code)  # 1. 코드를 파싱하여 AST 생성
    except astroid.AstroidSyntaxError as e:
        message = str(e)  # 또는 e.args[0]
        return [{
            'message': f"SyntaxError: {message}",
            'line': getattr(e, "line", 1),
            'column': getattr(e, "col", 0),
            'errorType': 'SyntaxError'
        }]
    except Exception as e:  # 3. 기타 예외 처리
        return [{
            "message": f"An error occurred during analysis: {e}",
            "line": 1,
            "column": 0,
            "errorType": "AnalysisError",
        }]

    errors = []

    # 함수별 분석
    for func_node in tree.body:  # 4. 모듈의 최상위 노드 순회
        if isinstance(func_node, astroid.FunctionDef):  # 5. 함수 정의 노드만 처리
            _analyze_function(func_node, errors, mode)  # 6. 함수별 분석 호출

    # 전체 코드 분석 (필요한 경우 추가)
    if mode == 'detailed':
        _analyze_module(tree, errors)

    return errors  # 7. 발견된 오류 반환


def _analyze_function(func_node: astroid.FunctionDef, errors: list, mode: str):
    """함수 단위 분석."""
    # 함수 내에서 정의된 변수
    defined_vars: Set[str] = _collect_defined_variables(func_node)

    # 재귀 호출 검사 (함수 노드에 대해 수행)
    _check_recursion_error(func_node, errors)

    # 함수 본문 분석
    for node in func_node.body:
        if mode == 'simple':
            _check_name_errors(node, defined_vars, errors)
            if isinstance(node, astroid.BinOp):  # ZeroDivisionError
                _check_zero_division_error(node, errors)


        elif mode == 'detailed':
            _check_name_errors(node, defined_vars, errors)
            if isinstance(node, astroid.BinOp):
                _check_zero_division_error(node, errors)
                _check_type_error(node, errors)
            elif isinstance(node, astroid.Attribute):
                _check_attribute_error(node, errors)
            elif isinstance(node, astroid.Subscript):
                _check_index_error(node, errors)
                _check_key_error(node, errors)


def _analyze_module(module_node: astroid.Module, errors: list):
    """모듈(전체 코드) 단위 분석 (필요한 경우 추가)."""
    for node in module_node.body:
        if isinstance(node, astroid.Call) and isinstance(node.func, astroid.Name) and node.func.name == "open":
            _check_file_not_found_error(node, errors)
        elif isinstance(node, astroid.While):  # 최상위 while 루프
            _check_infinite_loop(node, errors)

def _collect_defined_variables(func_node: astroid.FunctionDef) -> Set[str]:
    """함수 내에서 정의된 변수 이름을 수집합니다."""
    defined_vars: Set[str] = set()
    # 함수 매개변수
    for arg in func_node.args.args + func_node.args.posonlyargs + func_node.args.kwonlyargs:
        defined_vars.add(arg.name)
    if func_node.args.vararg:
        defined_vars.add(func_node.args.vararg)
    if func_node.args.kwarg:
        defined_vars.add(func_node.args.kwarg)

    # 함수 본문 내 할당문
    for node in func_node.body:
        if isinstance(node, astroid.Assign):
            for target in node.targets:
                if isinstance(target, astroid.Name):
                    defined_vars.add(target.name)
    return defined_vars

# --- (아래는 이전 코드의 오류 검사 함수들, _check_... ) ---

def _check_zero_division_error(node: astroid.BinOp, errors: list):
    """ZeroDivisionError를 검사합니다."""
    if isinstance(node.op, astroid.Div):
        try:
            right_value = node.right.infer()
            if any(isinstance(val, astroid.Const) and val.value == 0 for val in right_value):
                errors.append({
                    'message': 'Potential ZeroDivisionError: Division by zero',
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'ZeroDivisionError'
                })
        except astroid.InferenceError:
            pass

def _check_name_errors(node: astroid.NodeNG, defined_vars: Set[str], errors: list):
    """정의되지 않은 변수 사용(NameError)을 검사합니다."""
    if isinstance(node, astroid.Name) and isinstance(node.ctx, astroid.Load):
        if node.name not in defined_vars:
            try:
                node.lookup(node.name)  # 스코프 내에서 찾기
            except astroid.NotFoundError:
                errors.append({
                    'message': f"Potential NameError: Name '{node.name}' is not defined in this scope",
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'NameError'
                })

def _check_type_error(node: astroid.BinOp, errors: list):
    """TypeError를 검사합니다."""
    try:
        left_type = _get_type(node.left)
        right_type = _get_type(node.right)

        if left_type and right_type and not _is_compatible(left_type, right_type, node.op):
            errors.append({
                "message": f"Potential TypeError: Incompatible types for {node.op} operation: {left_type} and {right_type}",
                "line": node.lineno,
                "column": node.col_offset,
                "errorType": "TypeError",
            })
    except astroid.InferenceError:
        pass

def _check_attribute_error(node: astroid.Attribute, errors: list):
    """AttributeError를 검사합니다."""
    try:
        for inferred in node.value.infer():
            if inferred is astroid.Uninferable:
                continue
            if isinstance(inferred, astroid.Instance):
                try:
                    inferred.getattr(node.attrname)
                except astroid.NotFoundError:
                    errors.append({
                        "message": f"Potential AttributeError: '{inferred.name}' object has no attribute '{node.attrname}'",
                        "line": node.lineno,
                        "column": node.col_offset,
                        "errorType": "AttributeError",
                    })
            elif isinstance(inferred, astroid.Const) and inferred.value is None:
                errors.append({
                    "message": f"Potential AttributeError: 'NoneType' object has no attribute '{node.attrname}'",
                    "line": node.lineno,
                    "column": node.col_offset,
                    "errorType": "AttributeError",
                })
    except astroid.InferenceError:
        pass

def _check_index_error(node: astroid.Subscript, errors: list):
    """IndexError를 검사합니다."""
    try:
        for value_inferred in node.value.infer():
            if value_inferred is astroid.Uninferable:
                continue

            if isinstance(value_inferred, (astroid.List, astroid.Tuple)):
                if isinstance(node.slice, astroid.Const) and isinstance(node.slice.value, int):
                    index = node.slice.value
                    length = len(value_inferred.elts)
                    if index < -length or index >= length:
                        errors.append({
                            "message": f"Potential IndexError: Index {index} out of range for sequence of length {length}",
                            "line": node.lineno,
                            "column": node.col_offset,
                            "errorType": "IndexError",
                        })
            elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, str):
                if isinstance(node.slice, astroid.Const) and isinstance(node.slice.value, int):
                    index = node.slice.value
                    length = len(value_inferred.value)
                    if index < -length or index >= length:
                        errors.append({
                            "message": f"Potential IndexError: Index {index} out of range for string of length {length}",
                            "line": node.lineno,
                            "column": node.col_offset,
                            "errorType": "IndexError",
                        })
    except astroid.InferenceError:
        pass

def _check_key_error(node: astroid.Subscript, errors: list):
    """KeyError를 검사합니다."""
    try:
        for value_inferred in node.value.infer():
            if value_inferred is astroid.Uninferable:
                continue

            if isinstance(value_inferred, astroid.Dict):
                if isinstance(node.slice, astroid.Const):
                    key = node.slice.value
                    dict_keys = [k.value for k in value_inferred.keys if isinstance(k, astroid.Const)]
                    if key not in dict_keys:
                        errors.append({
                            "message": f"Potential KeyError: Key '{key}' not found in dictionary",
                            "line": node.lineno,
                            "column": node.col_offset,
                            "errorType": "KeyError",
                        })
    except astroid.InferenceError:
        pass
def _check_infinite_loop(node: astroid.While, errors: list):
    """잠재적 무한 루프(while True:)를 검사합니다."""
    if isinstance(node.test, astroid.Const) and node.test.value is True:
        if not any(isinstance(child, astroid.Break) for child in node.body):
            errors.append({
                'message': 'Potential infinite loop: while True without break',
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'InfiniteLoop'
            })

def _check_recursion_error(func_node: astroid.FunctionDef, errors: list):
    """재귀 호출(RecursionError)을 검사합니다."""
    for node in func_node.body: # 또는 func_node.get_children()
        if isinstance(node, astroid.Call):
            if (
                isinstance(node.func, astroid.Name)
                and node.func.name == func_node.name
            ):
                errors.append({
                    'message': 'Potential RecursionError: Recursive function call',
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'RecursionError'
                })
        # 만약 내부에 또다른 함수 정의가 있다면, 재귀적으로 검사.
        if isinstance(node, astroid.FunctionDef):
            _check_recursion_error(node, errors) # 재귀 호출

def _check_file_not_found_error(node: astroid.Call, errors: list):
    """파일이 존재하지 않는 경우(FileNotFoundError)를 검사합니다."""
    # open() 함수 호출이고, 첫 번째 인자가 문자열 상수인 경우
    if node.args and isinstance(node.args[0], astroid.Const):
        file_path = node.args[0].value
        if isinstance(file_path, str) and not os.path.exists(file_path):
            errors.append({
                "message": f"Potential FileNotFoundError: File '{file_path}' does not exist",
                "line": node.lineno,
                "column": node.col_offset,
                "errorType": "FileNotFoundError",
            })

def _get_type(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다."""
    try:
        for inferred in node.infer():
            if inferred is astroid.Uninferable:
                return None

            if isinstance(inferred, astroid.Const):
                return type(inferred.value).__name__
            elif isinstance(inferred, astroid.List):
                return "list"
            elif isinstance(inferred, astroid.Tuple):
                return "tuple"
            elif isinstance(inferred, astroid.Dict):
                return "dict"
            elif isinstance(inferred, astroid.FunctionDef):
                return "function"
            elif isinstance(inferred, astroid.ClassDef):
                return inferred.name
            elif isinstance(inferred, astroid.Instance):
                return inferred.name
            elif isinstance(inferred, astroid.Module):
                return "module"
            elif isinstance(inferred, astroid.Name):  # 변수
                if inferred.name in ('True', 'False'):
                    return 'bool'
    except astroid.InferenceError:
        return None
    return None

def _is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    if type1 is None or type2 is None:  # 타입을 추론할 수 없는 경우
        return True  # 일단 호환된다고 가정 (더 정교한 분석 필요)

    if type1 == type2:
        return True

    # 숫자 타입
    if type1 in ("int", "float") and type2 in ("int", "float"):
        if op in ("+", "-", "*", "/", "//", "%", "**"):
            return True

    # 문자열
    if type1 == "str" and type2 == "str" and op == '+':
        return True
    if type1 == 'str' and type2 == 'int' and op == '*':
        return True

    # 리스트
    if type1 == 'list' and type2 == 'list' and op == '+':
        return True
    if type1 == 'list' and type2 == 'int' and op == '*':
        return True

    return False

if __name__ == '__main__':
    code = sys.stdin.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'simple'
    errors = analyze_code(code, mode)
    print(json.dumps(errors))