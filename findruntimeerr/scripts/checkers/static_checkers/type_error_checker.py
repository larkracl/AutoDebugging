import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-type-error'; node_types = (astroid.BinOp,)
    MSGS = {'0202': ("TypeError: Incompatible operand types (Static)", 'type-error', '')}
    def check(self, node: astroid.BinOp):
        try:
            left_type = node.left.inferred()[0] if node.left.inferred() else None
            right_type = node.right.inferred()[0] if node.right.inferred() else None
            if left_type and right_type and type(left_type) != type(right_type):
                self.add_message(node, '0202')
        except Exception as e:
            print(f"Error in StaticTypeErrorChecker: {e}", file=sys.stderr)
