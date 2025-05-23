# checkers.py (RTNameErrorParsoChecker _is_definition_context 개선)
import astroid
import parso
from parso.python import tree as pt
import os
import sys
from typing import List, Dict, Any, Set, Optional, Tuple, Union
import builtins

from utils import get_type_astroid, is_compatible_astroid

# --- Base Classes (이전과 동일) ---
class BaseAstroidChecker:
    MSG_ID_PREFIX = 'E'; NAME = 'base-astroid-checker'
    MSGS: Dict[str, Tuple[str, str, str]] = {'F0001': ('Internal error (astroid): %s', 'fatal-error-astroid', '')}
    node_types: Tuple[type, ...] = ()
    def __init__(self, linter): self.linter = linter
    def add_message(self, node: astroid.NodeNG, msg_key: str, args: Optional[Tuple]=None):
        if self.NAME == 'base-astroid-checker': return
        if msg_key in self.MSGS: final_message = (self.MSGS[msg_key][0] % args) if args else self.MSGS[msg_key][0]; self.linter.add_astroid_message(f"{self.MSG_ID_PREFIX}{msg_key}", node, final_message)
        else: print(f"Warning: Unknown msg key '{msg_key}' in {self.NAME}", file=sys.stderr)
    def check(self, node: astroid.NodeNG): raise NotImplementedError

class BaseParsoChecker:
    MSG_ID_PREFIX = 'E'; NAME = 'base-parso-checker'
    MSGS: Dict[str, Tuple[str, str, str]] = {'F0002': ('Internal error (parso): %s', 'fatal-error-parso', '')}
    node_types: Tuple[str, ...] = ()
    def __init__(self, linter): self.linter = linter
    def add_message(self, node: parso.tree.BaseNode, msg_key: str, args: Optional[Tuple]=None):
        if self.NAME == 'base-parso-checker': return
        if msg_key in self.MSGS: final_message = (self.MSGS[msg_key][0] % args) if args else self.MSGS[msg_key][0]; self.linter.add_message(f"{self.MSG_ID_PREFIX}{msg_key}", node, final_message)
        else: print(f"Warning: Unknown msg key '{msg_key}' in {self.NAME}", file=sys.stderr)
    def check(self, node: parso.tree.BaseNode): raise NotImplementedError

# --- 실시간 체커 (Parso 기반) ---
class RTNameErrorParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-name-error-parso'; node_types = ('name',)
    MSGS = {'0101': ("Potential NameError: Name '%s' might not be defined (RT-Parso)", 'undefined-variable-rt-parso', '')}

    def _is_attribute_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'trailer':
            if len(parent.children) == 2 and parent.children[0].type == 'operator' and \
               parent.children[0].value == '.' and parent.children[1] is node:
                return True
        return False

    def _is_keyword_arg_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'argument':
            if len(parent.children) >= 2 and parent.children[0] is node and \
               parent.children[1].type == 'operator' and parent.children[1].value == '=':
                return True
        return False

    def _is_part_of_lhs_assignment(self, node: parso.tree.Leaf) -> bool:
        """이름 노드가 할당문의 LHS(Left-Hand Side)에 속하는지 확인합니다."""
        # current = node (node가 name Leaf)
        # 위로 올라가면서 expr_stmt 또는 namedexpr_test 찾기
        ancestor = node.parent
        while ancestor:
            if ancestor.type == 'expr_stmt':
                # expr_stmt: target_exprs '=' source_expr
                # expr_stmt: target_expr ':' type_expr ['=' source_expr]
                target_exprs_node = ancestor.children[0]
                # node가 target_exprs_node의 일부인지 확인
                q = [target_exprs_node]
                visited_lhs_parts = set()
                while q:
                    current_q = q.pop(0)
                    if current_q is node: return True # node가 LHS의 일부임
                    if hasattr(current_q, 'children'):
                        for child_q in current_q.children:
                            if child_q not in visited_lhs_parts and child_q.type != 'operator' and child_q.value != ',': # 연산자, 쉼표 제외
                                q.append(child_q)
                                visited_lhs_parts.add(child_q)
                return False # expr_stmt인데 node가 LHS에 없으면 정의 아님 (오른쪽 사용 등)
            elif ancestor.type == 'namedexpr_test': # walrus: NAME ':=' ...
                if len(ancestor.children) > 0 and ancestor.children[0] is node:
                    return True # node가 walrus의 LHS NAME임
                return False # namedexpr_test인데 node가 LHS가 아니면 정의 아님
            # 스코프 경계를 넘어가면 더 이상 LHS가 아님
            if ancestor.type in ('file_input', 'suite', 'funcdef', 'classdef', 'lambdef'):
                break
            ancestor = ancestor.parent
        return False

    def _is_definition_name_itself(self, node: parso.tree.Leaf) -> bool:
        """함수/클래스 정의 시 사용된 이름이거나, 파라미터 이름인지 확인합니다."""
        parent = node.parent
        if not parent: return False
        parent_type = parent.type

        # 1. 함수/클래스 정의 이름 ('def NAME()', 'class NAME():')
        if parent_type in ('funcdef', 'classdef'):
            # Parso: funcdef -> 'def' NAME parameters ['->' test] ':' suite
            # Parso: classdef -> 'class' NAME ['(' [arglist] ')'] ':' suite
            # 이름은 children[1]
            if len(parent.children) > 1 and parent.children[1].type == 'name' and parent.children[1] is node:
                return True

        # 2. 함수 파라미터 이름 (def func(PARAM): )
        if parent_type == 'param':
            # param can be NAME, or NAME ':' test, or NAME '=' test, etc.
            # The first child of 'param' that is a 'name' Leaf is the parameter name.
            # Also, param.name attribute should point to the name node.
            if hasattr(parent, 'name') and parent.name is node:
                return True
            # Fallback: check children if parent.name is not directly the node (e.g. complex param)
            if len(parent.children) > 0 and parent.children[0].type == 'name' and parent.children[0] is node:
                return True
        return False

    def check(self, node: parso.tree.Leaf):
        node_value = node.value

        if hasattr(builtins, node_value): return
        if self._is_attribute_name(node): return
        if self._is_keyword_arg_name(node): return
        if self._is_definition_name_itself(node): return # 함수/클래스/파라미터 정의 이름
        if self._is_part_of_lhs_assignment(node): return # 할당문의 왼쪽

        # For 루프 변수, With As 변수, Except As 변수는 collect_defined_variables_parso가 처리하여
        # current_scope_vars에 포함되어야 함. 따라서 아래 infer/scope check에서 걸러짐.

        try:
            if not self.linter.grammar:
                print("Warning: Parso grammar not available in Linter for infer.", file=sys.stderr)
                return

            definitions = list(self.linter.grammar.infer(node))
            if not definitions:
                current_scope_vars = self.linter.get_current_scope_variables_parso()
                if node_value not in current_scope_vars:
                    self.add_message(node, '0101', (node_value,))
        except Exception as e:
            # print(f"Infer error for '{node_value}': {e}", file=sys.stderr)
            current_scope_vars = self.linter.get_current_scope_variables_parso()
            if node_value not in current_scope_vars:
                 self.add_message(node, '0101', (node_value,))

class RTZeroDivisionParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-zero-division-parso'; node_types = ('term', 'arith_expr', 'power')
    MSGS = {'0201': ("Potential ZeroDivisionError: Division by zero (RT-Parso)", 'division-by-zero-rt-parso', '')}
    def _get_actual_value_node(self, node: parso.tree.BaseNode) -> parso.tree.BaseNode:
        current = node;
        while hasattr(current, 'children') and len(current.children) == 1 and current.type != 'number': current = current.children[0]
        return current
    def check(self, node: parso.tree.Node):
        try:
            if hasattr(node, 'children') and len(node.children) >= 3:
                 op_idx = -1;
                 for i, child in enumerate(node.children):
                      if child.type == 'operator' and child.value in ('/', '//'): op_idx = i; break
                 if op_idx > 0 and op_idx + 1 < len(node.children):
                      r_op_container = node.children[op_idx + 1]; actual_r_node = self._get_actual_value_node(r_op_container)
                      if actual_r_node.type == 'number':
                           val_str = actual_r_node.value.lower(); is_zero = False
                           if val_str == '0' or val_str == '0.0' or val_str.startswith('0e'): is_zero = True
                           else:
                                try:
                                     if float(val_str) == 0.0: is_zero = True
                                except ValueError: pass
                           if is_zero: self.add_message(actual_r_node, '0201')
        except Exception as e: node_repr = repr(node); print(f"Error in RTZeroDivision for {node_repr[:100]}...: {e}", file=sys.stderr)

# --- 상세 분석용 체커 (Astroid 기반 - 이전과 동일) ---
# class StaticNameErrorChecker(BaseAstroidChecker): ...
# class StaticTypeErrorChecker(BaseAstroidChecker): ...
# (이하 모든 Static 체커 클래스 정의 - 이전 답변의 전체 내용을 여기에 붙여넣으세요)
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
    def check_function_recursion(self, func_node: astroid.FunctionDef):
         func_name = func_node.name
         try:
             for call_node in func_node.nodes_of_class(astroid.Call):
                 if isinstance(call_node.func, astroid.Name) and call_node.func.name == func_name:
                     if call_node.scope() is func_node:
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
                      if file_path_value and not os.path.isabs(file_path_value):
                          if not os.path.exists(file_path_value):
                              self.add_message(node.args[0], '0901', (file_path_value,))
          except OSError as e: print(f"OSError checking file for {node.args[0].value if node.args and isinstance(node.args[0], astroid.Const) else 'N/A'}: {e}", file=sys.stderr)
          except Exception as e: print(f"Error in StaticFileNotFoundChecker for {repr(node)[:100]}...: {e}", file=sys.stderr)

# --- 체커 목록 (분리 유지) ---
RT_CHECKERS_CLASSES = [ RTNameErrorParsoChecker, RTZeroDivisionParsoChecker ]
STATIC_CHECKERS_CLASSES = [
     StaticNameErrorChecker, StaticTypeErrorChecker, StaticAttributeErrorChecker,
     StaticIndexErrorChecker, StaticKeyErrorChecker, StaticInfiniteLoopChecker,
     # StaticRecursionChecker 는 Linter.analyze_astroid 에서 별도 호출되므로 목록에 넣지 않음
     StaticFileNotFoundChecker
]