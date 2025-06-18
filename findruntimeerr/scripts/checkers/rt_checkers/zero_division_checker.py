import parso
from parso.python import tree as pt
import sys

from checkers.base_checkers import BaseParsoChecker
from symbol_table import Scope

class RTZeroDivisionParsoChecker(BaseParsoChecker):
    NAME = "rt-zero-division-parso"
    node_types = ("atom_expr",)
    MSGS = {
        "0102": ("ZeroDivisionError: division by zero (RT-Parso)", "zero-division-rt-parso", "")
    }

    def check(self, node: parso.tree.Node, current_scope: Scope):
        """
        ZeroDivisionError를 검사합니다. (스코프 인자 추가, 미사용이어도 반드시 받아야 함)
        """
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
