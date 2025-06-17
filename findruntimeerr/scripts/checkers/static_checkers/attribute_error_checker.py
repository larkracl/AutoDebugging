import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticAttributeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-attribute-error'; node_types = (astroid.Attribute,)
    MSGS = {'0301': ("AttributeError: Attribute may not exist (Static)", 'attribute-error', '')}
    def check(self, node: astroid.Attribute):
        try:
            if not list(node.infer()):
                self.add_message(node, '0301')
        except Exception as e:
            print(f"Error in StaticAttributeErrorChecker: {e}", file=sys.stderr)
