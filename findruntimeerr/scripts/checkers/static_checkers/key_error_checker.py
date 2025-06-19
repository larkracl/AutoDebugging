# scripts/checkers/static_checkers/key_error_checker.py
import astroid
from typing import Any
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker

class StaticKeyErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-key-error'; node_types = (astroid.Subscript,)
    MSGS = {
        '0601': ("KeyError: Key %s not found in dictionary literal (Static)", 'key-not-found-literal',''),
        'W0602': ("Potential KeyError: Key %s may not be found (Static)", 'variable-key-warning','')
    }
    def check(self, node: astroid.Subscript):
        # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            slice_inferred = list(node.slice.infer(context=None)); key_value: Any = None; is_const_key = False
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
                if any(isinstance(vi, astroid.Dict) for vi in node.value.infer(context=None)):
                    self.add_message(node.slice, 'W0602', (node.slice.as_string(),))
                return
            elif isinstance(slice_inferred[0], astroid.Const):
                key_val_candidate = slice_inferred[0].value
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
                        print(f"DEBUG: {self.NAME} FOUND a KeyError for key '{repr(key_value)}'", file=sys.stderr)
                        self.add_message(node.slice, '0601', (repr(key_value),)); return
        except astroid.InferenceError: pass
        except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)