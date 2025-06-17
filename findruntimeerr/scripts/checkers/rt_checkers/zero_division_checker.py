import parso
from parso.python import tree as pt
import sys
from ..base_checkers import BaseParsoChecker

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
                op_idx = -1
                for i, child in enumerate(node.children):
                    if child.type == 'operator' and child.value in ('/', '//'):
                        op_idx = i; break
                if op_idx > 0 and op_idx + 1 < len(node.children):
                    r_op_container = node.children[op_idx + 1]
                    actual_r_node = self._get_actual_value_node(r_op_container)
                    if actual_r_node.type == 'number':
                        val_str = actual_r_node.value.lower()
                        is_zero = False
                        if val_str == '0' or val_str == '0.0' or val_str.startswith('0e'):
                            is_zero = True
                        else:
                            try:
                                if float(val_str) == 0.0: is_zero = True
                            except ValueError: pass
                        if is_zero:
                            self.add_message(actual_r_node, '0201')
        except Exception as e:
            node_repr = repr(node)
            print(f"Error in RTZeroDivision for {node_repr[:100]}...: {e}", file=sys.stderr)
