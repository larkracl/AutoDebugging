import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticInfiniteLoopChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-infinite-loop'; node_types = (astroid.While,)
    MSGS = {'0601': ("Warning: Possible infinite loop (Static)", 'infinite-loop', '')}
    def check(self, node: astroid.While):
        try:
            # while True: 패턴만 단순 감지
            if isinstance(node.test, astroid.Const) and node.test.value is True:
                self.add_message(node, '0601')
        except Exception as e:
            print(f"Error in StaticInfiniteLoopChecker: {e}", file=sys.stderr)
