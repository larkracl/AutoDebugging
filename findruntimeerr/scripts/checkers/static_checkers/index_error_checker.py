import astroid
import sys
from ..base_checkers import BaseAstroidChecker

class StaticIndexErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-index-error'; node_types = (astroid.Subscript,)
    MSGS = {'0401': ("IndexError: Index may be out of range (Static)", 'index-error', '')}
    def check(self, node: astroid.Subscript):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            # 실제 인덱스 범위 체크는 어렵지만, 단순히 상수 인덱스에 대해 음수/큰 값 경고 예시
            if isinstance(node.slice, astroid.Const) and isinstance(node.value, astroid.List):
                idx = node.slice.value
                if isinstance(idx, int) and (idx < 0 or idx >= len(node.value.elts)):
                    print(f"DEBUG: {self.NAME} FOUND an error for index {idx}", file=sys.stderr)
                    self.add_message(node, '0401')
        except Exception as e:
            print(f"Error in StaticIndexErrorChecker: {e}", file=sys.stderr)
