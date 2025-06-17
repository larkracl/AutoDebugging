import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticRecursionChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-recursion'; node_types = (astroid.FunctionDef,)
    MSGS = {'0701': ("Warning: Possible infinite recursion (Static)", 'infinite-recursion', '')}
    def check_function_recursion(self, node: astroid.FunctionDef):
        try:
            # 함수 내부에서 자기 자신을 호출하는 경우 감지
            for call in node.nodes_of_class(astroid.Call):
                if hasattr(call.func, 'name') and call.func.name == node.name:
                    self.add_message(node, '0701')
                    break
        except Exception as e:
            print(f"Error in StaticRecursionChecker: {e}", file=sys.stderr)
