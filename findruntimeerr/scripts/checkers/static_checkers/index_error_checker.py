# scripts/checkers/static_checkers/index_error_checker.py
import astroid
import sys
import traceback
from checkers.base_checkers import BaseAstroidChecker

class StaticIndexErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-index-error'
    node_types = (astroid.Subscript,)
    MSGS = {
        '0301': ("IndexError: Index %s out of range (Static)", 'index-out-of-range', '')
    }

    def check(self, node: astroid.Subscript):
        try:
            if isinstance(node.value, (astroid.List, astroid.Tuple)):
                if isinstance(node.slice, astroid.Const):
                    idx = node.slice.value
                    if isinstance(idx, int):
                        length = len(node.value.elts)
                        if not (-length <= idx < length):
                            self.add_message(node, '0301', (idx,))
        except Exception as e:
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)