import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticKeyErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-key-error'; node_types = (astroid.Subscript,)
    MSGS = {'0501': ("KeyError: Key may not exist in dict (Static)", 'key-error', '')}
    def check(self, node: astroid.Subscript):
        try:
            if isinstance(node.value, astroid.Dict) and isinstance(node.slice, astroid.Const):
                keys = [k.value for k in node.value.keys if isinstance(k, astroid.Const)]
                if node.slice.value not in keys:
                    self.add_message(node, '0501')
        except Exception as e:
            print(f"Error in StaticKeyErrorChecker: {e}", file=sys.stderr)
