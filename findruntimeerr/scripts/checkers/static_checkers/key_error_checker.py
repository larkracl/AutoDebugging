# scripts/checkers/static_checkers/key_error_checker.py
import astroid
from checkers.base_checkers import BaseAstroidChecker

class StaticKeyErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-key-error'
    node_types = (astroid.Subscript,)
    MSGS = {
        '0501': ("KeyError: Key '%s' not found in dict (Static)", 'key-not-found', '')
    }

    def check(self, node: astroid.Subscript):
        try:
            if isinstance(node.value, astroid.Dict):
                if isinstance(node.slice, astroid.Const):
                    key = node.slice.value
                    keys = [k.value for k in node.value.keys if isinstance(k, astroid.Const)]
                    if key not in keys:
                        self.add_message(node, '0501', (key,))
        except Exception:
            pass