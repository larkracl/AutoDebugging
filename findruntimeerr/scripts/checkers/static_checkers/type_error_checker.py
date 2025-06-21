# scripts/checkers/static_checkers/type_error_checker.py
import astroid
import sys
import traceback

from checkers.base_checkers import BaseAstroidChecker


class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-type-error'
    node_types = (astroid.BinOp, astroid.UnaryOp, astroid.Call)
    MSGS = {
        '0201': ("TypeError: unsupported operand type(s) for %s: '%s' and '%s' (Static)", 'unsupported-operand-type', ''),
        '0202': ("TypeError: object is not callable (Static)", 'not-callable', '')
    }

    def check(self, node):
        try:
            if isinstance(node, astroid.BinOp):
                left_type = self.get_type(node.left)
                right_type = self.get_type(node.right)
                op = node.op
                if not self.is_compatible(left_type, right_type, op):
                    self.add_message(node, '0201', (op, left_type, right_type))
            elif isinstance(node, astroid.UnaryOp):
                operand_type = self.get_type(node.operand)
                op = node.op
                if not self.is_compatible(operand_type, None, op):
                    self.add_message(node, '0201', (op, operand_type, ''))
            elif isinstance(node, astroid.Call):
                func_type = self.get_type(node.func)
                if func_type not in ('function', 'builtin_function_or_method', 'method', 'type'):
                    self.add_message(node, '0202', ())
        except Exception as e:
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)