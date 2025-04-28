# static_checkers.py (상세 분석용 체커)
import astroid
import sys
import os
from typing import List, Dict, Any, Set
# utils.py는 공통으로 사용
from utils import get_type, is_compatible, collect_defined_variables

# --- 상세 분석 시 사용할 모든 검사 함수들 ---

def check_zero_division_error(node: astroid.BinOp, errors: list):
    """ZeroDivisionError를 검사합니다."""
    if isinstance(node.op, astroid.Div):
        try:
            right_value_inferred = list(node.right.infer())
            if any(isinstance(val, astroid.Const) and val.value == 0 for val in right_value_inferred):
                errors.append({
                    'message': 'Potential ZeroDivisionError: Division by zero',
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'ZeroDivisionError'
                })
        except astroid.InferenceError:
            pass

def check_name_errors(node: astroid.NodeNG, defined_vars: Set[str], errors: list):
    """정의되지 않은 변수 사용(NameError)을 검사합니다 (lookup 사용)."""
    if isinstance(node, astroid.Name) and isinstance(node.ctx, astroid.Load):
        # 함수/클래스 이름 등 builtins는 제외 (선택적)
        if node.name in __builtins__: # type: ignore
             return

        if node.name not in defined_vars:
            try:
                node.lookup(node.name) # 상위 스코프까지 확인
            except astroid.NotFoundError:
                errors.append({
                    'message': f"Potential NameError: Name '{node.name}' is not defined in this scope",
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'NameError'
                })
            except Exception as e:
                 print(f"Error during name lookup for '{node.name}': {e}", file=sys.stderr)

def check_type_error(node: astroid.BinOp, errors: list):
    """TypeError를 검사합니다."""
    try:
        left_type = get_type(node.left)
        right_type = get_type(node.right)

        if left_type and right_type and not is_compatible(left_type, right_type, node.op):
            errors.append({
                "message": f"Potential TypeError: Incompatible types for '{node.op}' operation: {left_type} and {right_type}",
                "line": node.lineno,
                "column": node.col_offset,
                "errorType": "TypeError",
            })
    except astroid.InferenceError:
        pass

def check_attribute_error(node: astroid.Attribute, errors: list):
    """AttributeError를 검사합니다."""
    try:
        value_inferred_list = list(node.value.infer())
        if not value_inferred_list: return

        has_attribute = False
        possible_types = []

        for inferred in value_inferred_list:
            if inferred is astroid.Uninferable:
                possible_types.append("Uninferable")
                continue

            current_type_name = getattr(inferred, 'name', type(inferred).__name__)
            # 이미 None 에러가 보고되었으면 추가 검사 X
            if current_type_name == 'NoneType' and any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']=='AttributeError' for err in errors):
                continue

            possible_types.append(current_type_name)

            if isinstance(inferred, astroid.Instance):
                try:
                    inferred.getattr(node.attrname)
                    has_attribute = True
                    break
                except astroid.NotFoundError:
                    pass
            elif isinstance(inferred, astroid.Const) and inferred.value is None:
                 # None 에러는 여기서 바로 추가 (중복 방지 필요 없음)
                errors.append({
                    "message": f"Potential AttributeError: 'NoneType' object has no attribute '{node.attrname}'",
                    "line": node.lineno, "column": node.col_offset, "errorType": "AttributeError",
                })
                # None 에러 발견 시 더 검사할 필요 없음 (다른 타입 가능성이 있어도 None일 가능성이 있으므로)
                # return # 여기서 리턴하면 다른 타입 검사 안함. 선택 필요.
            elif isinstance(inferred, astroid.Module):
                 try:
                    inferred.getattr(node.attrname)
                    has_attribute = True
                    break
                 except astroid.NotFoundError:
                    pass
            elif hasattr(inferred, node.attrname): # 다른 내장 타입 등
                 has_attribute = True
                 break

        # 모든 추론된 타입에서 속성을 찾지 못한 경우 + None 에러가 아니었던 경우
        if not has_attribute and not any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']=='AttributeError' for err in errors):
             types_str = ", ".join(sorted(list(set(possible_types)))) # 중복 제거 및 정렬
             errors.append({
                 "message": f"Potential AttributeError: Object(s) of type '{types_str}' may not have attribute '{node.attrname}'",
                 "line": node.lineno, "column": node.col_offset, "errorType": "AttributeError",
             })

    except astroid.InferenceError:
        pass

def check_index_error(node: astroid.Subscript, errors: list):
    """IndexError를 검사합니다."""
    try:
        slice_inferred = list(node.slice.infer())
        if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
             if isinstance(node.slice, astroid.Name):
                  errors.append({
                     "message": f"Potential IndexError: Index might be out of range (variable index '{node.slice.name}').",
                     "line": node.lineno, "column": node.col_offset, "errorType": "IndexError",
                  })
             return

        index_value = None
        if isinstance(slice_inferred[0], astroid.Const) and isinstance(slice_inferred[0].value, int):
            index_value = slice_inferred[0].value
        else:
             return


        for value_inferred in node.value.infer():
            if value_inferred is astroid.Uninferable:
                continue

            length = None
            if isinstance(value_inferred, (astroid.List, astroid.Tuple)):
                length = len(value_inferred.elts)
            elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, str):
                length = len(value_inferred.value)

            if length is not None and index_value is not None:
                if index_value < -length or index_value >= length:
                    errors.append({
                        "message": f"Potential IndexError: Index {index_value} out of range for sequence of length {length}",
                        "line": node.lineno, "column": node.col_offset, "errorType": "IndexError",
                    })
                    return

    except astroid.InferenceError:
        pass

def check_key_error(node: astroid.Subscript, errors: list):
    """KeyError를 검사합니다."""
    try:
        slice_inferred = list(node.slice.infer())
        if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
            return

        key_value = None
        if isinstance(slice_inferred[0], astroid.Const):
             key_value = slice_inferred[0].value
        else:
             return

        for value_inferred in node.value.infer():
            if value_inferred is astroid.Uninferable:
                continue

            if isinstance(value_inferred, astroid.Dict):
                dict_keys = set()
                for k_node, _ in value_inferred.items:
                     if isinstance(k_node, astroid.Const):
                         dict_keys.add(k_node.value)

                if key_value not in dict_keys:
                    key_repr = repr(key_value)
                    errors.append({
                        "message": f"Potential KeyError: Key {key_repr} may not be found in dictionary",
                        "line": node.lineno, "column": node.col_offset, "errorType": "KeyError",
                    })
                    return
    except astroid.InferenceError:
        pass

def check_infinite_loop(node: astroid.While, errors: list):
    """잠재적 무한 루프(while True:)를 검사합니다 (상세 버전)."""
    if isinstance(node.test, astroid.Const) and node.test.value is True:
        # 상세 분석에서는 walk()를 사용해 중첩된 break도 찾기 시도
        has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.walk())
        if not has_break:
            errors.append({
                'message': 'Potential infinite loop: `while True` without a reachable `break` statement',
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'InfiniteLoop'
            })

def check_recursion_error(func_node: astroid.FunctionDef, errors: list):
    """재귀 호출(RecursionError)을 검사합니다 (상세 버전)."""
    # walk()를 사용하여 함수 내부의 모든 노드 순회 (중첩 함수 내 호출 포함)
    for node in func_node.walk():
        if isinstance(node, astroid.Call):
            if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                 is_duplicate = any(
                     err['errorType'] == 'RecursionError' and err['line'] == node.lineno and err['column'] == node.col_offset
                     for err in errors
                 )
                 if not is_duplicate:
                    errors.append({
                        'message': f"Potential RecursionError: Recursive call to function '{func_node.name}'",
                        'line': node.lineno,
                        'column': node.col_offset,
                        'errorType': 'RecursionError'
                    })
                    # break # 하나만 찾으려면

def check_file_not_found_error(node: astroid.Call, errors: list):
    """파일이 존재하지 않는 경우(FileNotFoundError)를 검사합니다."""
    if isinstance(node.func, astroid.Name) and node.func.name == 'open':
        if node.args and isinstance(node.args[0], astroid.Const):
            file_path_value = node.args[0].value
            if isinstance(file_path_value, str):
                # 절대 경로 또는 실행 위치 기준 상대 경로 확인
                if not os.path.exists(file_path_value):
                    # TODO: 스크립트 파일 위치 기준 상대 경로 처리 추가
                    errors.append({
                        "message": f"Potential FileNotFoundError: File '{file_path_value}' might not exist",
                        "line": node.lineno,
                        "column": node.col_offset,
                        "errorType": "FileNotFoundError",
                    })