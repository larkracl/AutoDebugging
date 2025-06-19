import astroid
import builtins
import sys
from ..base_checkers import BaseAstroidChecker

class StaticNameErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-name-error'; node_types = (astroid.Name,)
    MSGS = {'0102': ("NameError: Name '%s' is not defined (Static)", 'undefined-variable', '')}
    def check(self, node: astroid.Name):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {getattr(node, 'name', str(node))}", file=sys.stderr)
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__:
            try:
                node.lookup(node.name)
            except astroid.NotFoundError:
                print(f"DEBUG: {self.NAME} FOUND an error for undefined name '{node.name}'", file=sys.stderr)
                self.add_message(node, '0102', (node.name,))
            except Exception as e:
                print(f"Error lookup '{node.name}': {e}", file=sys.stderr)
