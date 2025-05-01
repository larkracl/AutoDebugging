# checkers.py
import astroid
import os
import sys
from typing import List, Dict, Any, Set, Optional, Tuple, Union
from utils import get_type, is_compatible

class BaseChecker:
    """모든 체커의 베이스 클래스 (astroid 기반)."""
    MSG_ID_PREFIX = 'E'
    NAME = 'base-checker'
    MSGS: Dict[str, Tuple[str, str, str]] = {
        'F0001': ('Internal error: %s', 'fatal-error', 'Internal error during analysis.'),
    }
    node_types: Tuple[type, ...] = () # 검사할 astroid 노드 타입 튜플

    def __init__(self, linter):
        self.linter = linter

    # --- 수정: add_message 호출 시 메시지 키와 인자만 전달 ---
    def add_message(self, node: astroid.NodeNG, msg_key: str, args: Optional[Tuple]=None):
        """Linter에 오류 메시지를 추가합니다."""
        if self.NAME == 'base-checker': return

        if msg_key in self.MSGS:
            message_data = self.MSGS[msg_key]
            message_tmpl = message_data[0]
            final_message = message_tmpl % args if args else message_tmpl
            msg_id = f"{self.MSG_ID_PREFIX}{msg_key}" # 예: E0101
            self.linter.add_message(msg_id, node, final_message) # Linter의 add_message 호출
        else:
             print(f"Warning: Unknown message key '{msg_key}' in checker {self.NAME}", file=sys.stderr)
             # self.linter.add_message('F0001', node, f"Unknown msg key {msg_key}") # linter의 add_message 사용

    # 각 체커는 check 메서드 구현
    def check(self, node: astroid.NodeNG):
        raise NotImplementedError

# --- 실시간 분석용 체커 ---
class RTNameErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-name-error'
    node_types = (astroid.Name,)
    MSGS = {'0101': ("Potential NameError: Name '%s' might not be defined", 'undefined-variable-rt', '')}
    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load):
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars and node.name not in __builtins__: # type: ignore
                self.add_message(node, '0101', (node.name,)) # 메시지 키와 인자 전달

class RTZeroDivisionChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-zero-division'
    node_types = (astroid.BinOp,)
    MSGS = {'0201': ("Potential ZeroDivisionError: Division by zero", 'division-by-zero-rt', '')}
    def check(self, node: astroid.BinOp):
        if node.op == '/' and isinstance(node.right, astroid.Const) and node.right.value == 0:
            self.add_message(node.right, '0201') # 메시지 키 전달

# --- 상세 분석용 체커 ---
class StaticNameErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-name-error'
    node_types = (astroid.Name,)
    MSGS = {'0102': ("NameError: Name '%s' is not defined", 'undefined-variable', '')}
    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__:
            defined_vars = self.linter.get_current_scope_variables()
            if node.name not in defined_vars:
                try: node.lookup(node.name)
                except astroid.NotFoundError: self.add_message(node, '0102', (node.name,))
                except Exception as e: print(f"Error lookup '{node.name}': {e}", file=sys.stderr)

class StaticTypeErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-type-error'
    node_types = (astroid.BinOp,)
    MSGS = {'0301': ("TypeError: Incompatible types for '%s' operation: %s and %s", 'invalid-types-op', '')}
    def check(self, node: astroid.BinOp):
        try:
            left_type = get_type(node.left); right_type = get_type(node.right)
            if left_type and right_type and not is_compatible(left_type, right_type, node.op):
                self.add_message(node, '0301', (node.op, left_type, right_type))
        except astroid.InferenceError: pass

class StaticAttributeErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-attribute-error'
    node_types = (astroid.Attribute,)
    MSGS = {'0401': ("AttributeError: Object of type '%s' may not have attribute '%s'", 'maybe-no-member', ''),
            '0402': ("AttributeError: 'NoneType' object has no attribute '%s'", 'none-attr-error', '')}
    def check(self, node: astroid.Attribute):
         try:
             value_inferred_list = list(node.value.infer()); has_attribute = False; possible_types = []; none_error_reported = False
             if not value_inferred_list: return
             for inferred in value_inferred_list:
                 if inferred is astroid.Uninferable: possible_types.append("Uninferable"); continue
                 current_type_name = getattr(inferred, 'name', type(inferred).__name__)
                 if isinstance(inferred, astroid.Const) and inferred.value is None:
                     if not none_error_reported: self.add_message(node, '0402', (node.attrname,)); none_error_reported = True; continue
                 possible_types.append(current_type_name)
                 if isinstance(inferred, astroid.Instance):
                     try: inferred.getattr(node.attrname); has_attribute = True; break
                     except astroid.NotFoundError: pass
                 elif isinstance(inferred, astroid.Module):
                      try: inferred.getattr(node.attrname); has_attribute = True; break
                      except astroid.NotFoundError: pass
                 elif hasattr(inferred, node.attrname): has_attribute = True; break
             if not has_attribute and not none_error_reported:
                 types_str = ", ".join(sorted(list(set(possible_types) - {"Uninferable"})))
                 if types_str: self.add_message(node, '0401', (types_str, node.attrname))
         except astroid.InferenceError: pass

class StaticIndexErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-index-error'; node_types = (astroid.Subscript,)
    MSGS = {'0501': ("IndexError: Index %s out of range for sequence literal of length %s", 'index-out-of-range-literal',''),
            'W0502': ("Potential IndexError: Index %s may be out of range (variable/complex index)", 'variable-index-warning','')}
    def check(self, node: astroid.Subscript):
        try:
            slice_inferred = list(node.slice.infer()); index_value = None; is_const_int = False
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
                if isinstance(node.slice, astroid.Name): self.add_message(node.slice, 'W0502', (node.slice.name,)); return # 경고
            elif isinstance(slice_inferred[0], astroid.Const) and isinstance(slice_inferred[0].value, int): index_value = slice_inferred[0].value; is_const_int = True
            if not is_const_int: return # 현재는 상수 정수만 처리

            for value_inferred in node.value.infer():
                if value_inferred is astroid.Uninferable: continue
                length = None
                if isinstance(value_inferred, (astroid.List, astroid.Tuple)): length = len(value_inferred.elts)
                elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, str): length = len(value_inferred.value)
                if length is not None and (index_value < -length or index_value >= length):
                    self.add_message(node.slice, '0501', (index_value, length)); return
        except astroid.InferenceError: pass


class StaticKeyErrorChecker(BaseChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-key-error'; node_types = (astroid.Subscript,)
    MSGS = {'0601': ("KeyError: Key %s not found in dictionary literal", 'key-not-found-literal',''),
            'W0602': ("Potential KeyError: Key %s may not be found (variable/complex key or dict)", 'variable-key-warning','')}
    def check(self, node: astroid.Subscript):
        try:
            slice_inferred = list(node.slice.infer()); key_value = None; is_const_key = False
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable: pass # 변수 키는 아래에서 처리
            elif isinstance(slice_inferred[0], astroid.Const): key_value = slice_inferred[0].value; is_const_key = True
            if not is_const_key and not isinstance(node.slice, astroid.Name): return # 이름 아니면 처리 불가

            for value_inferred in node.value.infer():
                if value_inferred is astroid.Uninferable: continue
                if isinstance(value_inferred, astroid.Dict):
                    if is_const_key: # 상수 키 검사
                        dict_keys = set(); can_check_keys = True
                        for k_node, _ in value_inferred.items:
                             if isinstance(k_node, astroid.Const): dict_keys.add(k_node.value)
                             else: can_check_keys = False; break
                        if can_check_keys and key_value not in dict_keys:
                            self.add_message(node.slice, '0601', (repr(key_value),)); return
                    else: # 변수 키 경고
                         key_code = node.slice.get_code() # 변수 이름 가져오기
                         self.add_message(node.slice, 'W0602', (key_code,))
                         return # 경고 후 종료
        except astroid.InferenceError: pass


class StaticInfiniteLoopChecker(BaseChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-infinite-loop'; node_types = (astroid.While,)
    MSGS = {'0701': ("Infinite loop: `while True` without a reachable `break` statement", 'infinite-loop','')}
    def check(self, node: astroid.While):
        if isinstance(node.test, astroid.Const) and node.test.value is True:
            has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.walk())
            if not has_break: self.add_message(node.test, '0701')


class StaticRecursionChecker(BaseChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-recursion'
    MSGS = {'0801': ("RecursionError: Recursive call to function '%s'", 'recursive-call','')}
    # 이 체커는 Linter의 analyze 메소드에서 함수 단위로 호출
    def check_function_recursion(self, func_node: astroid.FunctionDef):
         for node in func_node.walk():
             if isinstance(node, astroid.Call):
                 if isinstance(node.func, astroid.Name) and node.func.name == func_node.name:
                     self.add_message(node.func, '0801', (func_node.name,))


class StaticFileNotFoundChecker(BaseChecker):
     MSG_ID_PREFIX = 'W'; NAME = 'static-file-not-found'; node_types = (astroid.Call,)
     MSGS = {'0901': ("FileNotFoundError: File '%s' might not exist", 'file-not-found-warning','')}
     def check(self, node: astroid.Call):
          if isinstance(node.func, astroid.Name) and node.func.name == 'open':
              if node.args and isinstance(node.args[0], astroid.Const):
                  file_path_value = node.args[0].value
                  if isinstance(file_path_value, str) and not os.path.exists(file_path_value):
                      self.add_message(node.args[0], '0901', (file_path_value,))

# 체커 클래스 목록
RT_CHECKERS_CLASSES = [ RTNameErrorChecker, RTZeroDivisionChecker ]
STATIC_CHECKERS_CLASSES = [
     StaticNameErrorChecker, RTZeroDivisionChecker, StaticTypeErrorChecker,
     StaticAttributeErrorChecker, StaticIndexErrorChecker, StaticKeyErrorChecker,
     StaticInfiniteLoopChecker, StaticRecursionChecker, StaticFileNotFoundChecker
]