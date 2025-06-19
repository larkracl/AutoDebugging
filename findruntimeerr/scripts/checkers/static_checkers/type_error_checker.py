# scripts/checkers/static_checkers/type_error_checker.py
import astroid
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker
from utils import get_type_astroid, is_compatible_astroid

class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-type-error'; node_types = (astroid.BinOp,)
    MSGS = {'0301': ("TypeError: Incompatible types for '%s' operation: %s and %s (Static)", 'invalid-types-op', '')}
    def check(self, node: astroid.BinOp):
        # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            left_type = get_type_astroid(node.left)
            right_type = get_type_astroid(node.right)
            if left_type and right_type:
                if not is_compatible_astroid(left_type, right_type, node.op):
                    print(f"DEBUG: {self.NAME} FOUND an error for '{node.op}' with types {left_type}, {right_type}", file=sys.stderr)
                    self.add_message(node, '0301', (node.op, left_type, right_type))
        except astroid.InferenceError: pass
        except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)