import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticKeyErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-key-error'; node_types = (astroid.Subscript,)
    MSGS = {'0501': ("KeyError: Key may not exist in dict (Static)", 'key-error', '')}
    def check(self, node: astroid.Subscript):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            if isinstance(node.value, astroid.Dict) and isinstance(node.slice, astroid.Const):
                keys = [k.value for k in node.value.keys if isinstance(k, astroid.Const)]
                if node.slice.value not in keys:
                    print(f"DEBUG: {self.NAME} FOUND an error for key {node.slice.value}", file=sys.stderr)
                    self.add_message(node, '0501')
        except Exception as e:
            print(f"Error in StaticKeyErrorChecker: {e}", file=sys.stderr)
