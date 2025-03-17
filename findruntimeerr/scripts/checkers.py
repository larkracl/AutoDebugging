# checkers.py
import astroid
from typing import List, Dict, Any, Set
from utils import get_type, is_compatible


def check_zero_division_error(node: astroid.BinOp, errors: list):
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

def check_name_errors(node: astroid.NodeNG, defined_vars: Set[str], errors: list):
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

def check_type_error(node: astroid.BinOp, errors: list):
    """TypeError를 검사합니다."""
    try:
        left_type = get_type(node.left)
        right_type = get_type(node.right)

        if left_type and right_type and not is_compatible(left_type, right_type, node.op):
            errors.append({
                "message": f"Potential TypeError: Incompatible types for {node.op} operation: {left_type} and {right_type}",
                "line": node.lineno,
                "column": node.col_offset,
                "errorType": "TypeError",
            })
    except astroid.InferenceError:
        pass

def check_attribute_error(node: astroid.Attribute, errors: list):
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

def check_index_error(node: astroid.Subscript, errors: list):
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

def check_key_error(node: astroid.Subscript, errors: list):
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
def check_infinite_loop(node: astroid.While, errors: list):
    """잠재적 무한 루프(while True:)를 검사합니다."""
    if isinstance(node.test, astroid.Const) and node.test.value is True:
        if not any(isinstance(child, astroid.Break) for child in node.body):
            errors.append({
                'message': 'Potential infinite loop: while True without break',
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'InfiniteLoop'
            })

def check_recursion_error(func_node: astroid.FunctionDef, errors: list):
    """재귀 호출(RecursionError)을 검사합니다."""
    for node in func_node.body:
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
            check_recursion_error(node, errors)

def check_file_not_found_error(node: astroid.Call, errors: list):
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