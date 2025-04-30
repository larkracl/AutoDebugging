# checkers.py
import astroid
import os
import sys
from typing import List, Dict, Any, Set, Union
from utils import get_type, is_compatible # utils.py의 함수 사용

class BaseChecker:
    """모든 체커의 베이스 클래스."""
    MSG_ID = 'BaseError'
    node_types = () # 검사할 노드 타입 지정 (튜플)

    def __init__(self, linter):
        self.linter = linter # Linter 인스턴스 저장

    def add_message(self, node: astroid.NodeNG, message: str):
        """Linter에 오류 메시지를 추가합니다 (중복 방지 포함)."""
        line = getattr(node, 'fromlineno', 1) or getattr(node, 'lineno', 1) or 1
        col = getattr(node, 'col_offset', 0) or 0
        to_line = getattr(node, 'tolineno', line) or line
        end_col = getattr(node, 'end_col_offset', col + 1) or (col + 1)
        line = max(1, line); col = max(0, col)
        to_line = max(1, to_line); end_col = max(0, end_col)
        error_key = (self.MSG_ID, line, col, to_line, end_col)

        if not any(err.get('_key') == error_key for err in self.linter.errors):
            error_info = {
                'message': message, 'line': line, 'column': col,
                'to_line': to_line, 'end_column': end_col, # 끝 위치 정보 포함
                'errorType': self.MSG_ID, '_key': error_key
            }
            self.linter.errors.append(error_info)

    # 특정 노드 타입 방문 시 호출될 메서드 (Linter가 호출)
    def check(self, node: astroid.NodeNG):
         """각 서브클래스에서 이 메서드를 구현하여 검사를 수행합니다."""
         raise NotImplementedError


# --- 실시간 분석용 체커 ---

class RTNameErrorChecker(BaseChecker):
    MSG_ID = 'NameErrorRT'
    node_types = (astroid.Name,)

    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load):
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars and node.name not in __builtins__: # type: ignore
                self.add_message(node, f"Potential NameError: Name '{node.name}' might not be defined")


class RTZeroDivisionChecker(BaseChecker):
    MSG_ID = 'ZeroDivisionErrorRT'
    node_types = (astroid.BinOp,)

    def check(self, node: astroid.BinOp):
        if node.op == '/' and isinstance(node.right, astroid.Const) and node.right.value == 0:
            self.add_message(node.right, 'Potential ZeroDivisionError: Division by zero') # node.right에 오류 표시


# --- 상세 분석용 체커 ---

class StaticNameErrorChecker(BaseChecker):
    MSG_ID = 'NameErrorStatic'
    node_types = (astroid.Name,)

    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__: # type: ignore
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars:
                try:
                    node.lookup(node.name)
                except astroid.NotFoundError:
                    self.add_message(node, f"Potential NameError: Name '{node.name}' is not defined in this scope")
                except Exception as e:
                    print(f"Error during name lookup for '{node.name}': {e}", file=sys.stderr)


class StaticTypeErrorChecker(BaseChecker):
    MSG_ID = 'TypeErrorStatic'
    node_types = (astroid.BinOp, astroid.Call) # Call 노드도 검사 가능

    def check(self, node: Union[astroid.BinOp, astroid.Call]):
        if isinstance(node, astroid.BinOp):
            try:
                left_type = get_type(node.left)
                right_type = get_type(node.right)
                if left_type and right_type and not is_compatible(left_type, right_type, node.op):
                    self.add_message(node, f"Potential TypeError: Incompatible types for '{node.op}' operation: {left_type} and {right_type}")
            except astroid.InferenceError: pass
        # elif isinstance(node, astroid.Call): # 함수 호출 타입 검사 (추가 가능)
        #     # 예: func(arg) 호출 시 func의 파라미터 타입과 arg의 타입 비교
        #     pass


class StaticAttributeErrorChecker(BaseChecker):
    MSG_ID = 'AttributeErrorStatic'
    node_types = (astroid.Attribute,)

    def check(self, node: astroid.Attribute):
         try:
             value_inferred_list = list(node.value.infer())
             if not value_inferred_list: return
             has_attribute = False; possible_types = []; found_none_error = False

             for inferred in value_inferred_list:
                 if inferred is astroid.Uninferable: possible_types.append("Uninferable"); continue
                 current_type_name = getattr(inferred, 'name', type(inferred).__name__)
                 if current_type_name == 'NoneType' and any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']==self.MSG_ID for err in self.linter.errors): continue
                 possible_types.append(current_type_name)

                 if isinstance(inferred, astroid.Instance):
                     try: inferred.getattr(node.attrname); has_attribute = True; break
                     except astroid.NotFoundError: pass
                 elif isinstance(inferred, astroid.Const) and inferred.value is None:
                     if not any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']==self.MSG_ID for err in self.linter.errors):
                          self.add_message(node, f"Potential AttributeError: 'NoneType' object has no attribute '{node.attrname}'")
                     found_none_error = True
                 elif isinstance(inferred, astroid.Module):
                      try: inferred.getattr(node.attrname); has_attribute = True; break
                      except astroid.NotFoundError: pass
                 elif hasattr(inferred, node.attrname): has_attribute = True; break

             if not has_attribute and not found_none_error:
                 if not any(err['line']==node.lineno and err['column']==node.col_offset and err['errorType']==self.MSG_ID for err in self.linter.errors):
                      types_str = ", ".join(sorted(list(set(possible_types) - {"Uninferable"})))
                      if types_str:
                           self.add_message(node, f"Potential AttributeError: Object(s) of type '{types_str}' may not have attribute '{node.attrname}'")
         except astroid.InferenceError: pass


class StaticIndexErrorChecker(BaseChecker):
    MSG_ID = 'IndexErrorStatic'
    node_types = (astroid.Subscript,)

    def check(self, node: astroid.Subscript):
        try:
            slice_inferred = list(node.slice.infer()); index_value = None
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
                if isinstance(node.slice, astroid.Name): pass # 변수 인덱스 경고 제거
                return
            elif isinstance(slice_inferred[0], astroid.Const) and isinstance(slice_inferred[0].value, int): index_value = slice_inferred[0].value
            else: return
            if index_value is None: return

            for value_inferred in node.value.infer():
                if value_inferred is astroid.Uninferable: continue
                length = None
                if isinstance(value_inferred, (astroid.List, astroid.Tuple)): length = len(value_inferred.elts)
                elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, str): length = len(value_inferred.value)
                if length is not None and (index_value < -length or index_value >= length):
                    self.add_message(node.slice, f"Potential IndexError: Index {index_value} out of range for sequence of length {length}"); return # node.slice에 오류 표시
        except astroid.InferenceError: pass


class StaticKeyErrorChecker(BaseChecker):
    MSG_ID = 'KeyErrorStatic'
    node_types = (astroid.Subscript,)

    def check(self, node: astroid.Subscript):
        try:
            slice_inferred = list(node.slice.infer()); key_value = None
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable: return
            elif isinstance(slice_inferred[0], astroid.Const): key_value = slice_inferred[0].value
            else: return

            for value_inferred in node.value.infer():
                if value_inferred is astroid.Uninferable: continue
                if isinstance(value_inferred, astroid.Dict):
                    dict_keys = set()
                    can_check_keys = True
                    for k_node, _ in value_inferred.items:
                         if isinstance(k_node, astroid.Const): dict_keys.add(k_node.value)
                         else: can_check_keys = False; break
                    if can_check_keys and key_value not in dict_keys:
                        self.add_message(node.slice, f"Potential KeyError: Key {repr(key_value)} may not be found in dictionary"); return # node.slice에 오류 표시
        except astroid.InferenceError: pass


class StaticInfiniteLoopChecker(BaseChecker):
    MSG_ID = 'InfiniteLoopStatic'
    node_types = (astroid.While,)

    def check(self, node: astroid.While):
        if isinstance(node.test, astroid.Const) and node.test.value is True:
            has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.walk())
            if not has_break: self.add_message(node.test, 'Potential infinite loop: `while True` without a reachable `break` statement') # node.test에 오류 표시

class StaticRecursionChecker(BaseChecker):
    MSG_ID = 'RecursionErrorStatic'
    # 이 체커는 Linter의 analyze 메소드에서 함수 단위로 호출
    def check_function_recursion(self, func_node: astroid.FunctionDef):
         for node in func_node.walk():
             if isinstance(node, astroid.Call):
                 if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                     self.add_message(node.func, f"Potential RecursionError: Recursive call to function '{func_node.name}'") # node.func에 오류 표시


class StaticFileNotFoundChecker(BaseChecker):
     MSG_ID = 'FileNotFoundErrorStatic'
     node_types = (astroid.Call,)

     def check(self, node: astroid.Call):
          if isinstance(node.func, astroid.Name) and node.func.name == 'open':
              if node.args and isinstance(node.args[0], astroid.Const):
                  file_path_value = node.args[0].value
                  if isinstance(file_path_value, str) and not os.path.exists(file_path_value):
                      self.add_message(node.args[0], f"Potential FileNotFoundError: File '{file_path_value}' might not exist") # node.args[0]에 오류 표시


# 체커 클래스 목록
RT_CHECKERS_CLASSES = [
    RTNameErrorChecker,
    RTZeroDivisionChecker,
]

STATIC_CHECKERS_CLASSES = [
    StaticNameErrorChecker,
    RTZeroDivisionChecker, # 재사용
    StaticTypeErrorChecker,
    StaticAttributeErrorChecker,
    StaticIndexErrorChecker,
    StaticKeyErrorChecker,
    StaticInfiniteLoopChecker,
    StaticRecursionChecker, # Linter에서 별도 호출
    StaticFileNotFoundChecker,
]