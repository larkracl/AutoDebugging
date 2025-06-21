# scripts/checkers/static_checkers/zero_division_checker.py (신규 파일)
import astroid
import sys

from checkers.base_checkers import BaseAstroidChecker

class StaticZeroDivisionChecker(BaseAstroidChecker):
    """Astroid를 사용하여 0으로 나누는 오류를 탐지하는 체커."""
    MSG_ID_PREFIX = 'E'
    NAME = 'static-zero-division'
    node_types = (astroid.BinOp,)  # 이항 연산자 노드를 검사
    MSGS = {
        '0201': ("ZeroDivisionError: division by zero (Static)", 'zero-division-static', '')
    }

    def check(self, node: astroid.BinOp):
        """주어진 이항 연산자 노드가 0으로 나누는 연산인지 확인합니다."""
        # 연산자가 나누기(/) 또는 정수 나누기(//)인지 확인
        if node.op in ('/', '//'):
            try:
                # 오른쪽 피연산자의 값을 추론
                inferred_values = list(node.right.infer(context=None))
                
                # 추론된 값이 있고, Uninferable이 아닐 때
                if inferred_values and inferred_values[0] is not astroid.Uninferable:
                    val = inferred_values[0]
                    # 추론된 값이 숫자 0을 나타내는 상수인지 확인
                    if isinstance(val, astroid.Const) and val.value == 0:
                        print(f"DEBUG: {self.NAME} FOUND an error for '{node.as_string()}'", file=sys.stderr)
                        # 오른쪽 피연산자 노드에 메시지 추가
                        self.add_message(node.right, '0201')

            except astroid.InferenceError:
                # 타입 추론 실패는 자주 발생하므로 조용히 넘어감
                pass
            except Exception as e:
                print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)