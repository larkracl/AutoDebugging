# checkers.py (Parso + Astroid 기반 체커 분리, RTNameErrorParsoChecker 개선)
import astroid
import parso # parso import
from parso.python import tree as pt # parso tree types
import os
import sys
from typing import List, Dict, Any, Set, Optional, Tuple, Union
import builtins # 내장 함수/타입 확인용

# utils.py에서 필요한 함수들을 import 합니다.
# 이 함수들은 각 라이브러리(Parso, Astroid)에 맞게 구현되어 있어야 합니다.
from utils import get_type_astroid, is_compatible_astroid

# --- Base Classes ---

# Astroid 기반 체커용 Base 클래스
class BaseAstroidChecker:
    """Astroid 기반 체커의 베이스 클래스."""
    MSG_ID_PREFIX = 'E' # 기본 오류 코드 Prefix
    NAME = 'base-astroid-checker' # 체커 이름
    MSGS: Dict[str, Tuple[str, str, str]] = { # 메시지 정의: {key: (format_string, symbol, description)}
        'F0001': ('Internal error (astroid): %s', 'fatal-error-astroid', 'Internal error during astroid analysis.'),
    }
    # 검사할 astroid 노드 타입 튜플 (astroid 클래스 객체)
    node_types: Tuple[type, ...] = ()

    def __init__(self, linter):
        """Linter 인스턴스를 저장합니다."""
        self.linter = linter # core.Linter 인스턴스

    def add_message(self, node: astroid.NodeNG, msg_key: str, args: Optional[Tuple]=None):
        """Linter에 오류 메시지를 추가합니다 (astroid 노드 기반)."""
        # 기본 클래스에서는 메시지 추가 안 함
        if self.NAME == 'base-astroid-checker': return

        if msg_key in self.MSGS:
            message_data = self.MSGS[msg_key]
            message_tmpl = message_data[0] # 포맷 문자열
            # 인자가 있으면 포맷팅, 없으면 그대로 사용
            final_message = message_tmpl % args if args else message_tmpl
            # 메시지 ID 생성 (Prefix + Key)
            msg_id = f"{self.MSG_ID_PREFIX}{msg_key}"
            # Linter의 astroid용 메시지 추가 메서드 호출 (core.py에 정의됨)
            self.linter.add_astroid_message(msg_id, node, final_message)
        else:
            # 정의되지 않은 메시지 키 사용 시 경고 출력
            print(f"Warning: Unknown message key '{msg_key}' in checker {self.NAME}", file=sys.stderr)

    def check(self, node: astroid.NodeNG):
        """구체적인 검사 로직 (하위 클래스에서 구현 필요)."""
        raise NotImplementedError

# Parso 기반 체커용 Base 클래스
class BaseParsoChecker:
    """Parso 기반 체커의 베이스 클래스."""
    MSG_ID_PREFIX = 'E' # 기본 오류 코드 Prefix
    NAME = 'base-parso-checker' # 체커 이름
    MSGS: Dict[str, Tuple[str, str, str]] = { # 메시지 정의
        'F0002': ('Internal error (parso): %s', 'fatal-error-parso', 'Internal error during parso analysis.'),
    }
    # 검사할 parso 노드 타입 문자열 튜플 (e.g., 'name', 'number')
    node_types: Tuple[str, ...] = ()

    def __init__(self, linter):
        """Linter 인스턴스를 저장합니다."""
        self.linter = linter # core.Linter 인스턴스

    def add_message(self, node: parso.tree.BaseNode, msg_key: str, args: Optional[Tuple]=None):
        """Linter에 오류 메시지를 추가합니다 (parso 노드 기반)."""
        # 기본 클래스에서는 메시지 추가 안 함
        if self.NAME == 'base-parso-checker': return

        if msg_key in self.MSGS:
            message_data = self.MSGS[msg_key]
            message_tmpl = message_data[0]
            final_message = message_tmpl % args if args else message_tmpl
            msg_id = f"{self.MSG_ID_PREFIX}{msg_key}"
             # Linter의 parso용 메시지 추가 메서드 호출 (core.py의 기본 add_message)
            self.linter.add_message(msg_id, node, final_message)
        else:
             print(f"Warning: Unknown message key '{msg_key}' in checker {self.NAME}", file=sys.stderr)

    def check(self, node: parso.tree.BaseNode):
        """구체적인 검사 로직 (하위 클래스에서 구현 필요)."""
        raise NotImplementedError


# --- 실시간 체커 (Parso 기반) ---
class RTNameErrorParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-name-error-parso'; node_types = ('name',)
    MSGS = {'0101': ("Potential NameError: Name '%s' might not be defined (RT-Parso)", 'undefined-variable-rt-parso', '')}

    def _is_attribute_name(self, node: parso.tree.Leaf) -> bool:
        """이름 노드가 객체의 속성으로 사용되었는지 확인합니다 (예: obj.THIS_NAME)."""
        parent = node.parent
        if parent and parent.type == 'trailer':
            if len(parent.children) == 2 and \
               parent.children[0].type == 'operator' and parent.children[0].value == '.' and \
               parent.children[1] is node:
                return True
        return False

    def _is_keyword_arg_name(self, node: parso.tree.Leaf) -> bool:
        """이름 노드가 함수 호출 시 키워드 인자 이름으로 사용되었는지 확인합니다 (예: func(THIS_NAME=value))."""
        parent = node.parent
        if parent and parent.type == 'argument':
            if len(parent.children) > 1 and parent.children[0] is node and \
               parent.children[1].type == 'operator' and parent.children[1].value == '=':
                return True
        return False

    def _is_definition_context(self, node: parso.tree.Leaf) -> bool:
        """이름 노드가 정의의 일부인지 (할당의 왼쪽, 함수/클래스/파라미터 이름 등) 간단히 확인합니다."""
        parent = node.parent
        if not parent: return False
        parent_type = parent.type

        # 함수/클래스 정의 이름
        if parent_type in ('funcdef', 'classdef') and len(parent.children) > 1 and parent.children[1] is node:
            return True
        # 함수 파라미터 이름
        if parent_type == 'param' and len(parent.children)>0 and parent.children[0] is node:
            return True
        # 할당문의 가장 왼쪽 (간단한 경우)
        grandparent = parent.parent
        if grandparent and grandparent.type == 'expr_stmt' and parent is grandparent.children[0] and parent_type == 'name':
             if len(grandparent.children) > 1 and grandparent.children[1].type == 'operator' and grandparent.children[1].value == '=':
                  return True
        # Import 이름 (더 정확한 건 get_defined_names지만, 이건 사용 컨텍스트인지 판단용)
        if grandparent and grandparent.type in ('import_name', 'import_from'): return True
        if parent_type in ('dotted_as_name', 'import_as_name'): return True
        # With item target (with ... as target)
        if parent_type == 'with_item' and len(parent.children) == 3 and isinstance(parent.children[1], parso.tree.Leaf) and parent.children[1].value == 'as' and parent.children[2] is node:
            return True
        # except clause target (except E as target)
        if parent_type == 'except_clause' and len(parent.children) >= 4 and isinstance(parent.children[2], parso.tree.Leaf) and parent.children[2].value == 'as' and parent.children[3] is node:
            return True
        # For loop target (간단한 for x in ...)
        if parent_type == 'for_stmt' and len(parent.children) > 1 and parent.children[1] is node:
            return True
        return False

    def check(self, node: parso.tree.Leaf):
        node_value = node.value

        if hasattr(builtins, node_value): return
        if self._is_attribute_name(node): return
        if self._is_keyword_arg_name(node): return
        if self._is_definition_context(node): return # 정의 컨텍스트면 사용이 아님

        try:
            if not self.linter.grammar: return
            definitions = list(self.linter.grammar.infer(node))
            if not definitions:
                current_scope_vars = self.linter.get_current_scope_variables_parso()
                if node_value not in current_scope_vars:
                     self.add_message(node, '0101', (node_value,))
        except Exception as e:
            # print(f"Error inferring parso node '{node_value}' L{node.start_pos[0]}:{node.start_pos[1]}: {e}", file=sys.stderr)
            current_scope_vars = self.linter.get_current_scope_variables_parso()
            if node_value not in current_scope_vars:
                 self.add_message(node, '0101', (node_value,))

class RTZeroDivisionParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-zero-division-parso'; node_types = ('term', 'arith_expr', 'power')
    MSGS = {'0201': ("Potential ZeroDivisionError: Division by zero (RT-Parso)", 'division-by-zero-rt-parso', '')}

    def _get_actual_value_node(self, node: parso.tree.BaseNode) -> parso.tree.BaseNode:
        current = node
        while hasattr(current, 'children') and len(current.children) == 1 and current.type != 'number':
            current = current.children[0]
        return current

    def check(self, node: parso.tree.Node):
        try:
            if hasattr(node, 'children') and len(node.children) >= 3:
                 op_index = -1
                 for i, child in enumerate(node.children):
                      if child.type == 'operator' and child.value in ('/', '//'):
                           op_index = i; break
                 if op_index > 0 and op_index + 1 < len(node.children):
                      right_operand_container = node.children[op_index + 1]
                      actual_right_node = self._get_actual_value_node(right_operand_container)
                      if actual_right_node.type == 'number':
                           val_str = actual_right_node.value.lower()
                           is_zero = False
                           if val_str == '0': is_zero = True
                           else:
                                try:
                                     if float(val_str) == 0.0: is_zero = True
                                except ValueError: pass
                           if is_zero:
                                self.add_message(actual_right_node, '0201')
        except Exception as e:
             node_repr = repr(node); print(f"Error in RTZeroDivisionParsoChecker for {node_repr[:100]}...: {e}", file=sys.stderr)

# --- 상세 분석용 체커 (Astroid 기반 - 전체 코드) ---
class StaticNameErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-name-error'; node_types = (astroid.Name,)
    MSGS = {'0102': ("NameError: Name '%s' is not defined (Static)", 'undefined-variable', '')}
    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__:
            try: node.lookup(node.name)
            except astroid.NotFoundError: self.add_message(node, '0102', (node.name,))
            except Exception as e: print(f"Error lookup '{node.name}': {e}", file=sys.stderr)

class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-type-error'; node_types = (astroid.BinOp,)
    MSGS = {'0301': ("TypeError: Incompatible types for '%s' operation: %s and %s (Static)", 'invalid-types-op', '')}
    def check(self, node: astroid.BinOp):
        try:
            # from utils import get_type_astroid, is_compatible_astroid # core.py에서 import하므로 여기서 또 할 필요 없음
            left_type = get_type_astroid(node.left)
            right_type = get_type_astroid(node.right)
            if left_type and right_type and not is_compatible_astroid(left_type, right_type, node.op):
                self.add_message(node, '0301', (node.op, left_type, right_type))
        except astroid.InferenceError: pass
        except Exception as e: print(f"Error in StaticTypeErrorChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

class StaticAttributeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-attribute-error'; node_types = (astroid.Attribute,)
    MSGS = {
        '0401': ("AttributeError: Object of type '%s' may not have attribute '%s' (Static)", 'maybe-no-member', ''),
        '0402': ("AttributeError: 'NoneType' object has no attribute '%s' (Static)", 'none-attr-error', '')
    }
    def check(self, node: astroid.Attribute):
         try:
             value_inferred_list = list(node.value.infer(context=None))
             has_attribute = False; possible_types = []; none_error_reported = False
             if not value_inferred_list: return
             for inferred in value_inferred_list:
                 if inferred is astroid.Uninferable: possible_types.append("Uninferable"); continue
                 current_type_name = getattr(inferred, 'qname', getattr(inferred, 'name', type(inferred).__name__))
                 if isinstance(inferred, astroid.Const) and inferred.value is None:
                     if not none_error_reported: self.add_message(node.attrname, '0402', (node.attrname,)); none_error_reported = True
                     continue
                 possible_types.append(current_type_name)
                 try: inferred.getattr(node.attrname); has_attribute = True; break
                 except (astroid.NotFoundError, AttributeError): pass
             if not has_attribute and not none_error_reported:
                 types_str = ", ".join(sorted(list(set(pt for pt in possible_types if pt != "Uninferable"))))
                 if types_str: self.add_message(node.attrname, '0401', (types_str, node.attrname,))
         except astroid.InferenceError: pass
         except Exception as e: print(f"Error in StaticAttributeErrorChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

class StaticIndexErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-index-error'; node_types = (astroid.Subscript,)
    MSGS = {
        '0501': ("IndexError: Index %s out of range for sequence literal of length %s (Static)", 'index-out-of-range-literal',''),
        'W0502': ("Potential IndexError: Index %s may be out of range (variable/complex index) (Static)", 'variable-index-warning','')
    }
    def check(self, node: astroid.Subscript):
        try:
            slice_inferred_list = list(node.slice.infer(context=None)); index_value: Optional[int] = None; is_const_int = False
            if not slice_inferred_list or slice_inferred_list[0] is astroid.Uninferable:
                is_sequence = any(isinstance(vi, (astroid.List, astroid.Tuple)) or (isinstance(vi, astroid.Const) and isinstance(vi.value, (str,bytes))) for vi in node.value.infer(context=None))
                if is_sequence: self.add_message(node.slice, 'W0502', (node.slice.as_string(),))
                return
            elif isinstance(slice_inferred_list[0], astroid.Const) and isinstance(slice_inferred_list[0].value, int):
                index_value = slice_inferred_list[0].value; is_const_int = True
            if not is_const_int or index_value is None: return
            for value_inferred in node.value.infer(context=None):
                if value_inferred is astroid.Uninferable: continue
                length: Optional[int] = None
                if isinstance(value_inferred, (astroid.List, astroid.Tuple)): length = len(value_inferred.elts)
                elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, (str, bytes)): length = len(value_inferred.value)
                if length is not None and (index_value < -length or index_value >= length):
                    self.add_message(node.slice, '0501', (index_value, length)); return
        except astroid.InferenceError: pass
        except Exception as e: print(f"Error in StaticIndexErrorChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

class StaticKeyErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-key-error'; node_types = (astroid.Subscript,)
    MSGS = {
        '0601': ("KeyError: Key %s not found in dictionary literal (Static)", 'key-not-found-literal',''),
        'W0602': ("Potential KeyError: Key %s may not be found (variable/complex key or dict) (Static)", 'variable-key-warning','')
    }
    def check(self, node: astroid.Subscript):
        try:
            slice_inferred_list = list(node.slice.infer(context=None)); key_value: Any = None; is_const_key = False
            if not slice_inferred_list or slice_inferred_list[0] is astroid.Uninferable:
                if any(isinstance(vi, astroid.Dict) for vi in node.value.infer(context=None)): self.add_message(node.slice, 'W0602', (node.slice.as_string(),))
                return
            elif isinstance(slice_inferred_list[0], astroid.Const):
                key_val_candidate = slice_inferred_list[0].value
                try: hash(key_val_candidate); key_value = key_val_candidate; is_const_key = True
                except TypeError: is_const_key = False
            if not is_const_key: return
            for value_inferred in node.value.infer(context=None):
                if value_inferred is astroid.Uninferable: continue
                if isinstance(value_inferred, astroid.Dict):
                    dict_keys = set(); can_check_keys = True
                    for k_node, _ in value_inferred.items:
                         if isinstance(k_node, astroid.Const):
                             try: hash(k_node.value); dict_keys.add(k_node.value)
                             except TypeError: can_check_keys = False; break
                         else: can_check_keys = False; break
                    if can_check_keys and key_value not in dict_keys:
                        self.add_message(node.slice, '0601', (repr(key_value),)); return
        except astroid.InferenceError: pass
        except Exception as e: print(f"Error in StaticKeyErrorChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

class StaticInfiniteLoopChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-infinite-loop'; node_types = (astroid.While,)
    MSGS = {'0701': ("Potential infinite loop: `while True` without a reachable `break` (Static)", 'infinite-loop','')}
    def check(self, node: astroid.While):
        try:
            test_inferred = list(node.test.infer(context=None))
            if test_inferred and isinstance(test_inferred[0], astroid.Const) and test_inferred[0].value is True:
                has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.body)
                if not has_break: self.add_message(node.test, '0701')
        except astroid.InferenceError: pass
        except Exception as e: print(f"Error in StaticInfiniteLoopChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

class StaticRecursionChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-recursion'
    MSGS = {'0801': ("Potential recursion: Function '%s' calls itself (Static)", 'recursive-call','')}
    def check_function_recursion(self, func_node: astroid.FunctionDef): # 이 메서드는 Linter에서 직접 호출
         func_name = func_node.name
         try:
             for call_node in func_node.nodes_of_class(astroid.Call):
                 if isinstance(call_node.func, astroid.Name) and call_node.func.name == func_name:
                     if call_node.scope() is func_node: # 호출이 해당 함수 스코프 내에서 일어나는지 확인
                          self.add_message(call_node.func, '0801', (func_name,)); return
         except Exception as e: print(f"Error checking recursion for {func_name}: {e}", file=sys.stderr)

class StaticFileNotFoundChecker(BaseAstroidChecker):
     MSG_ID_PREFIX = 'W'; NAME = 'static-file-not-found'; node_types = (astroid.Call,)
     MSGS = {'0901': ("Potential FileNotFoundError: File '%s' might not exist (Static)", 'file-not-found-warning','')}
     def check(self, node: astroid.Call):
          try:
              if isinstance(node.func, astroid.Name) and node.func.name == 'open':
                  if node.args and isinstance(node.args[0], astroid.Const) and isinstance(node.args[0].value, str):
                      file_path_value = node.args[0].value
                      if file_path_value and not os.path.isabs(file_path_value): # 상대 경로인 경우만 체크 (또는 다른 전략)
                          # 절대 경로는 환경 의존성이 너무 큼
                          # 실제로는 프로젝트 루트 기준 상대 경로 해석 등 필요
                          if not os.path.exists(file_path_value): # 이 부분은 실행 환경에 따라 오탐 가능
                              self.add_message(node.args[0], '0901', (file_path_value,))
          except OSError as e: print(f"OSError checking file for {node.args[0].value if node.args and isinstance(node.args[0], astroid.Const) else 'N/A'}: {e}", file=sys.stderr)
          except Exception as e: print(f"Error in StaticFileNotFoundChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

# --- 체커 목록 (분리 유지) ---
RT_CHECKERS_CLASSES = [ RTNameErrorParsoChecker, RTZeroDivisionParsoChecker ]
STATIC_CHECKERS_CLASSES = [
     StaticNameErrorChecker, StaticTypeErrorChecker, StaticAttributeErrorChecker,
     StaticIndexErrorChecker, StaticKeyErrorChecker, StaticInfiniteLoopChecker,
     # StaticRecursionChecker 는 Linter.analyze_astroid 에서 별도 호출
     StaticFileNotFoundChecker
]