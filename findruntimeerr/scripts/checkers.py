# checkers.py
import astroid
import os
import sys
from typing import List, Dict, Any, Set, Union
from utils import get_type, is_compatible

class BaseChecker:
    """모든 체커의 베이스 클래스."""
    MSG_ID = 'BaseError'
    node_types = ()

    def __init__(self, linter):
        self.linter = linter

    def add_message(self, node: astroid.NodeNG, message: str):
        """Linter에 오류 메시지를 추가합니다 (중복 방지 포함)."""
        line = getattr(node, 'fromlineno', 1) or getattr(node, 'lineno', 1) or 1
        col = getattr(node, 'col_offset', 0) or 0
        line = max(1, line); col = max(0, col)
        error_key = (self.MSG_ID, line, col)

        if not any(err.get('_key') == error_key for err in self.linter.errors):
            error_info = {'message': message, 'line': line, 'column': col, 'errorType': self.MSG_ID, '_key': error_key}
            self.linter.errors.append(error_info)


# --- 실시간 분석용 체커 ---

class RTNameErrorChecker(BaseChecker):
    MSG_ID = 'NameErrorRT'
    node_types = (astroid.Name,)

    def check(self, node: astroid.Name):
        """Name 노드에 대한 NameError 검사 (간단 버전)."""
        # --- ctx 속성 존재 여부 확인 추가 ---
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load):
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars and node.name not in __builtins__: # type: ignore
                self.add_message(node, f"Potential NameError: Name '{node.name}' might not be defined")


class RTZeroDivisionChecker(BaseChecker):
    MSG_ID = 'ZeroDivisionErrorRT'
    node_types = (astroid.BinOp,)

    def check(self, node: astroid.BinOp):
        """BinOp 노드에 대한 ZeroDivisionError 검사 (상수 0)."""
        if node.op == '/' and isinstance(node.right, astroid.Const) and node.right.value == 0:
            self.add_message(node, 'Potential ZeroDivisionError: Division by zero')


# --- 상세 분석용 체커 ---

class StaticNameErrorChecker(BaseChecker): # RT 상속 대신 BaseChecker 직접 상속
    MSG_ID = 'NameErrorStatic'
    node_types = (astroid.Name,)

    def check(self, node: astroid.Name):
        """Name 노드에 대한 NameError 검사 (lookup 사용)."""
        # --- ctx 속성 존재 여부 확인 추가 ---
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__: # type: ignore
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars:
                try:
                    node.lookup(node.name)
                except astroid.NotFoundError:
                    self.add_message(node, f"Potential NameError: Name '{node.name}' is not defined in this scope")
                except Exception as e:
                    print(f"Error during name lookup for '{node.name}': {e}", file=sys.stderr)


# --- 다른 상세 분석 체커들 (StaticTypeErrorChecker, StaticAttributeErrorChecker 등) ---
# 이 체커들의 check 메서드 내에서는 ctx 속성을 직접 사용하지 않으므로 수정 불필요
# (만약 다른 체커에서 ctx를 사용한다면 동일하게 hasattr 검사 추가)
class StaticTypeErrorChecker(BaseChecker):
    MSG_ID = 'TypeErrorStatic'
    node_types = (astroid.BinOp,)

    def check(self, node: astroid.BinOp):
        """BinOp 노드에 대한 TypeError 검사."""
        try:
            left_type = get_type(node.left)
            right_type = get_type(node.right)
            if left_type and right_type and not is_compatible(left_type, right_type, node.op):
                self.add_message(node, f"Potential TypeError: Incompatible types for '{node.op}' operation: {left_type} and {right_type}")
        except astroid.InferenceError: pass

class StaticAttributeErrorChecker(BaseChecker):
    MSG_ID = 'AttributeErrorStatic'
    node_types = (astroid.Attribute,)

    def check(self, node: astroid.Attribute):
         """Attribute 노드에 대한 AttributeError 검사."""
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
        """Subscript 노드에 대한 IndexError 검사."""
        try:
            slice_inferred = list(node.slice.infer()); index_value = None
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
                if isinstance(node.slice, astroid.Name):
                    # 변수 인덱스 경고 제거 또는 더 정교하게 변경
                    # self.add_message(node, f"Potential IndexError: Index might be out of range (variable index '{node.slice.name}').")
                    pass
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
                    self.add_message(node, f"Potential IndexError: Index {index_value} out of range for sequence of length {length}"); return
        except astroid.InferenceError: pass


class StaticKeyErrorChecker(BaseChecker):
    MSG_ID = 'KeyErrorStatic'
    node_types = (astroid.Subscript,)

    def check(self, node: astroid.Subscript):
        """Subscript 노드에 대한 KeyError 검사."""
        try:
            slice_inferred = list(node.slice.infer()); key_value = None
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable: return
            elif isinstance(slice_inferred[0], astroid.Const): key_value = slice_inferred[0].value
            else: return
            # if key_value is None: return # 키가 None인 경우도 검사 가능

            for value_inferred in node.value.infer():
                if value_inferred is astroid.Uninferable: continue
                if isinstance(value_inferred, astroid.Dict):
                    dict_keys = set()
                    can_check_keys = True
                    for k_node, _ in value_inferred.items:
                         if isinstance(k_node, astroid.Const):
                             dict_keys.add(k_node.value)
                         else: can_check_keys = False; break
                    if can_check_keys and key_value not in dict_keys:
                        self.add_message(node, f"Potential KeyError: Key {repr(key_value)} may not be found in dictionary"); return
        except astroid.InferenceError: pass


class StaticInfiniteLoopChecker(BaseChecker):
    MSG_ID = 'InfiniteLoopStatic'
    node_types = (astroid.While,)

    def check(self, node: astroid.While):
        """While 노드에 대한 무한 루프 검사."""
        if isinstance(node.test, astroid.Const) and node.test.value is True:
            has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.walk())
            if not has_break: self.add_message(node, 'Potential infinite loop: `while True` without a reachable `break` statement')


class StaticRecursionChecker(BaseChecker):
    MSG_ID = 'RecursionErrorStatic'
    # 이 체커는 함수 단위로 실행되어야 함
    def check_function_recursion(self, func_node: astroid.FunctionDef):
         """함수 노드에 대한 재귀 호출 검사."""
         for node in func_node.walk():
             if isinstance(node, astroid.Call):
                 if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                     self.add_message(node, f"Potential RecursionError: Recursive call to function '{func_node.name}'")
                     # break # 함수당 하나만 찾으려면


class StaticFileNotFoundChecker(BaseChecker):
     MSG_ID = 'FileNotFoundErrorStatic'
     node_types = (astroid.Call,)

     def check(self, node: astroid.Call):
          """Call 노드에 대한 open() 함수 FileNotFound 검사."""
          if isinstance(node.func, astroid.Name) and node.func.name == 'open':
              if node.args and isinstance(node.args[0], astroid.Const):
                  file_path_value = node.args[0].value
                  if isinstance(file_path_value, str) and not os.path.exists(file_path_value):
                      self.add_message(node, f"Potential FileNotFoundError: File '{file_path_value}' might not exist")


# 체커 목록 정의
RT_CHECKERS_CLASSES = [
    RTNameErrorChecker,
    RTZeroDivisionChecker,
]

STATIC_CHECKERS_CLASSES = [
    StaticNameErrorChecker,
    RTZeroDivisionChecker,
    StaticTypeErrorChecker,
    StaticAttributeErrorChecker,
    StaticIndexErrorChecker,
    StaticKeyErrorChecker,
    StaticInfiniteLoopChecker,
    StaticRecursionChecker, # Linter에서 함수 단위로 호출 필요
    StaticFileNotFoundChecker,
]