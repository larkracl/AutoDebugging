# scripts/checkers/static_checkers/infinite_loop_checker.py
import astroid
from checkers.base_checkers import BaseAstroidChecker

class StaticInfiniteLoopChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-infinite-loop'
    node_types = (astroid.While,)
    MSGS = {
        '0701': ("InfiniteLoop: Detected possible infinite loop (Static)", 'infinite-loop', '')
    }

    def check(self, node: astroid.While):
        try:
            if isinstance(node.test, astroid.Const) and node.test.value is True:
                self.add_message(node, '0701', ())
        except Exception:
            pass