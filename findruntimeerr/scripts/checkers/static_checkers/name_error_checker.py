import astroid
import builtins
import sys
from ..base_checkers import BaseAstroidChecker

class StaticNameErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-name-error'; node_types = (astroid.Name,)
    MSGS = {'0102': ("NameError: Name '%s' is not defined (Static)", 'undefined-variable', '')}
    def check(self, node: astroid.Name):
        if hasattr(node, 'ctx') and isinstance(node.ctx, astroid.Load) and node.name not in __builtins__:
            try: node.lookup(node.name)
            except astroid.NotFoundError: self.add_message(node, '0102', (node.name,))
            except Exception as e: print(f"Error lookup '{node.name}': {e}", file=sys.stderr)
