# scripts/checkers/static_checkers/index_error_checker.py
import astroid
from typing import Optional
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker

class StaticIndexErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-index-error'; node_types = (astroid.Subscript,)
    MSGS = {
        '0501': ("IndexError: Index %s is out of range for sequence of length %s (Static)", 'index-out-of-range-literal',''),
        'W0502': ("Potential IndexError: Index %s may be out of range (Static)", 'variable-index-warning','')
    }
    def check(self, node: astroid.Subscript):
        # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            slice_inferred = list(node.slice.infer(context=None))
            if not slice_inferred or slice_inferred[0] is astroid.Uninferable:
                self.add_message(node.slice, 'W0502', (node.slice.as_string(),)); return
            inferred_slice = slice_inferred[0]
            if not isinstance(inferred_slice, astroid.Const) or not isinstance(inferred_slice.value, int): return
            index_value = inferred_slice.value
            for value_inferred in node.value.infer(context=None):
                if value_inferred is astroid.Uninferable: continue
                length: Optional[int] = None
                if isinstance(value_inferred, (astroid.List, astroid.Tuple)): length = len(value_inferred.elts)
                elif isinstance(value_inferred, astroid.Const) and isinstance(value_inferred.value, (str, bytes)): length = len(value_inferred.value)
                if length is not None and not (-length <= index_value < length):
                    print(f"DEBUG: {self.NAME} FOUND an IndexError for index {index_value} on length {length}", file=sys.stderr)
                    self.add_message(node.slice, '0501', (index_value, length)); return
        except astroid.InferenceError: pass
        except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)