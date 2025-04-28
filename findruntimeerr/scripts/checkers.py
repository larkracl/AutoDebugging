# checkers.py
import astroid
import sys # stderr 출력을 위해 추가
import os # check_file_not_found_error 에서 사용
from typing import List, Dict, Any, Set
from utils import get_type, is_compatible # 상대 경로 대신 절대 경로 사용 (main.py에서 실행될 때 기준)


def check_zero_division_error(node: astroid.BinOp, errors: list):
    """ZeroDivisionError를 검사합니다."""
    if isinstance(node.op, astroid.Div):
        try:
            right_value_inferred = list(node.right.infer()) # 한 번만 infer 호출
            if any(isinstance(val, astroid.Const) and val.value == 0 for val in right_value_inferred):
                errors.append({
                    'message': 'Potential ZeroDivisionError: Division by zero',
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'ZeroDivisionError'
                })
        except astroid.InferenceError:
            pass # 추론 실패 시 무시

def check_name_errors(node: astroid.NodeNG, defined_vars: Set[str], errors: list):
    """정의되지 않은 변수 사용(NameError)을 검사합니다."""
    if isinstance(node, astroid.Name) and isinstance(node.ctx, astroid.Load):
        if node.name not in defined_vars:
            try:
                # lookup으로 상위 스코프까지 확인
                defs = node.lookup(node.name)[1]
                # 만약 lookup이 성공했지만, FunctionDef나 ClassDef가 아니라면 (예: import된 모듈 등)
                # NameError가 아닐 수 있음. 더 정교한 확인 필요 시 여기에 로직 추가.
            except astroid.NotFoundError:
                errors.append({
                    'message': f"Potential NameError: Name '{node.name}' is not defined in this scope",
                    'line': node.lineno,
                    'column': node.col_offset,
                    'errorType': 'NameError'
                })
            except Exception as e: # 예상치 못한 lookup 오류
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
        pass # 타입 추론 실패 시 무시

def check_attribute_error(node: astroid.Attribute, errors: list):
    """AttributeError를 검사합니다."""
    try:
        value_inferred_list = list(node.value.infer()) # 한 번만 infer 호출
        if not value_inferred_list: # 추론 결과가 없으면 검사 불가
             return

        has_attribute = False
        possible_types = []

        for inferred in value_inferred_list:
            if inferred is astroid.Uninferable:
                possible_types.append("Uninferable")
                continue # 추론 불가 시 속성 검사 불가

            possible_types.append(getattr(inferred, 'name', type(inferred).__name__)) # 타입 이름 기록

            if isinstance(inferred, astroid.Instance):
                try:
                    inferred.getattr(node.attrname)
                    has_attribute = True # 속성 발견!
                    break # 하나라도 찾으면 더 이상 검사 필요 없음
                except astroid.NotFoundError:
                    pass # 이 타입에는 속성이 없음
            elif isinstance(inferred, astroid.Const) and inferred.value is None:
                errors.append({ # NoneType 에러는 바로 추가
                    "message": f"Potential AttributeError: 'NoneType' object has no attribute '{node.attrname}'",
                    "line": node.lineno, "column": node.col_offset, "errorType": "AttributeError",
                })
                return # None 에러는 확정적이므로 더 검사 안 함
            elif isinstance(inferred, astroid.Module):
                 try:
                    inferred.getattr(node.attrname)
                    has_attribute = True
                    break
                 except astroid.NotFoundError:
                    pass
            else:
                # 다른 타입 (List, Dict 등)에 대한 속성 접근도 검사 가능 (필요시 추가)
                # 예를 들어, list에 append가 있는지 등
                if hasattr(inferred, node.attrname):
                     has_attribute = True
                     break


        # 모든 추론된 타입에서 속성을 찾지 못한 경우
        if not has_attribute and not any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']=='AttributeError' for err in errors):
             types_str = ", ".join(set(possible_types)) # 중복 제거
             errors.append({
                 "message": f"Potential AttributeError: Object(s) of type '{types_str}' may not have attribute '{node.attrname}'",
                 "line": node.lineno, "column": node.col_offset, "errorType": "AttributeError",
             })

    except astroid.InferenceError:
        pass # 추론 실패 시 무시

def check_index_error(node: astroid.Subscript, errors: list):
    """IndexError를 검사합니다."""
    try:
        slice_inferred = list(node.slice.infer()) # 인덱스/슬라이스 값 추론
        if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
             # 인덱스 값 추론 불가 시 검사 어려움
             if isinstance(node.slice, astroid.Name): # 변수 인덱스 경고
                  errors.append({
                     "message": f"Potential IndexError: Index might be out of range (variable index '{node.slice.name}').",
                     "line": node.lineno, "column": node.col_offset, "errorType": "IndexError",
                  })
             return


        index_value = None
        if isinstance(slice_inferred[0], astroid.Const) and isinstance(slice_inferred[0].value, int):
            index_value = slice_inferred[0].value
        else:
             # 상수가 아닌 인덱스는 현재 검사 한계
             return


        for value_inferred in node.value.infer(): # 대상 객체 추론
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
                    # 오류 발견 시 해당 객체에 대한 검사 중단 (하나의 오류만 보고)
                    return

    except astroid.InferenceError:
        pass # 추론 실패 시 무시

def check_key_error(node: astroid.Subscript, errors: list):
    """KeyError를 검사합니다."""
    try:
        slice_inferred = list(node.slice.infer()) # 키 값 추론
        if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
            return # 키 값 추론 불가

        key_value = None
        if isinstance(slice_inferred[0], astroid.Const):
             key_value = slice_inferred[0].value
        else:
             # 상수가 아닌 키는 현재 검사 한계
             return


        for value_inferred in node.value.infer(): # 딕셔너리 객체 추론
            if value_inferred is astroid.Uninferable:
                continue

            if isinstance(value_inferred, astroid.Dict):
                # 딕셔너리 키들을 상수 값으로 가져오기 시도
                dict_keys = set()
                for k_node, _ in value_inferred.items:
                     if isinstance(k_node, astroid.Const):
                         dict_keys.add(k_node.value)
                     # TODO: 변수 키 등 다른 형태의 키 처리 추가 가능

                if key_value not in dict_keys:
                    # repr()을 사용하여 키 값의 표현을 얻음 (예: 문자열은 따옴표 포함)
                    key_repr = repr(key_value)
                    errors.append({
                        "message": f"Potential KeyError: Key {key_repr} may not be found in dictionary",
                        "line": node.lineno, "column": node.col_offset, "errorType": "KeyError",
                    })
                    # 오류 발견 시 해당 객체에 대한 검사 중단
                    return
    except astroid.InferenceError:
        pass # 추론 실패 시 무시

def check_infinite_loop(node: astroid.While, errors: list):
    """잠재적 무한 루프(while True:)를 검사합니다."""
    if isinstance(node.test, astroid.Const) and node.test.value is True:
        # node.body를 순회하며 break 문 찾기 (break가 다른 블록 안에 중첩된 경우는?)
        has_break = False
        queue = list(node.body)
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited: continue
            visited.add(current)

            if isinstance(current, astroid.Break):
                 has_break = True
                 break
            # 다른 블록 (If, For, While, Try 등) 안에 break가 있을 수 있음
            if hasattr(current, 'body'):
                queue.extend(current.body)
            if hasattr(current, 'orelse'):
                queue.extend(current.orelse)
            if hasattr(current, 'handlers'): # Try..except
                 for handler in current.handlers:
                     queue.extend(handler.body)
            if hasattr(current, 'finalbody'): # Try..finally
                 queue.extend(current.finalbody)


        if not has_break:
            errors.append({
                'message': 'Potential infinite loop: `while True` without a reachable `break` statement',
                'line': node.lineno,
                'column': node.col_offset,
                'errorType': 'InfiniteLoop'
            })

def check_recursion_error(func_node: astroid.FunctionDef, errors: list):
    """재귀 호출(RecursionError)을 검사합니다."""
    # func_node.walk()를 사용하여 함수 내부의 모든 노드 순회
    for node in func_node.walk():
        if isinstance(node, astroid.Call):
            # 함수 호출 노드이고, 호출 대상이 현재 함수 이름과 같으면 재귀 호출
            if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                # 같은 오류가 이미 추가되었는지 확인 (중복 방지)
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
                    # 함수당 하나의 재귀 오류만 보고하려면 여기서 break 가능
                    # break


def check_file_not_found_error(node: astroid.Call, errors: list):
    """파일이 존재하지 않는 경우(FileNotFoundError)를 검사합니다."""
    # open() 함수 호출이고, 첫 번째 인자가 문자열 상수인 경우
    if isinstance(node.func, astroid.Name) and node.func.name == 'open':
        if node.args and isinstance(node.args[0], astroid.Const):
            file_path_value = node.args[0].value
            if isinstance(file_path_value, str):
                # 상대 경로 처리 추가 (선택적)
                # script_dir = os.path.dirname(node.root().file) # 스크립트 파일 기준
                # abs_path = os.path.join(script_dir, file_path_value)
                # if not os.path.exists(abs_path): ...

                # 현재는 절대 경로 또는 실행 위치 기준 상대 경로만 확인
                if not os.path.exists(file_path_value):
                    errors.append({
                        "message": f"Potential FileNotFoundError: File '{file_path_value}' might not exist",
                        "line": node.lineno,
                        "column": node.col_offset,
                        "errorType": "FileNotFoundError",
                    })