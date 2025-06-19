import astroid
import sys
from checkers.base_checkers import BaseAstroidChecker
from utils import get_type_astroid, is_compatible_astroid

class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-type-error'; node_types = (astroid.BinOp,)
    MSGS = {'0202': ("TypeError: Incompatible operand types (Static)", 'type-error', '')}
    def check(self, node: astroid.BinOp):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            left_type = get_type_astroid(node.left)
            right_type = get_type_astroid(node.right)
            if left_type and right_type and not is_compatible_astroid(left_type, right_type, node.op):
                # --- 디버깅 로그 추가 ---
                print(f"DEBUG: {self.NAME} FOUND an error for '{node.op}' with types {left_type}, {right_type}", file=sys.stderr)
                self.add_message(node, '0202', (node.op, left_type, right_type))
        except Exception as e:
            print(f"Error in StaticTypeErrorChecker: {e}", file=sys.stderr)