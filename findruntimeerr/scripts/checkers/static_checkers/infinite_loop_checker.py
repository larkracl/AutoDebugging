# scripts/checkers/static_checkers/infinite_loop_checker.py
import astroid
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker

class StaticInfiniteLoopChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-infinite-loop'; node_types = (astroid.While,)
    MSGS = {'0701': ("Potential infinite loop: `while True` without a reachable `break` (Static)", 'infinite-loop','')}
    def check(self, node: astroid.While):
        # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            test_inferred = list(node.test.infer(context=None))
            if test_inferred and isinstance(test_inferred[0], astroid.Const) and test_inferred[0].value is True:
                has_break = any(isinstance(sub_node, astroid.Break) for sub_node in node.body)
                if not has_break:
                    print(f"DEBUG: {self.NAME} FOUND an infinite loop", file=sys.stderr)
                    self.add_message(node.test, '0701')
        except astroid.InferenceError: pass
        except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)