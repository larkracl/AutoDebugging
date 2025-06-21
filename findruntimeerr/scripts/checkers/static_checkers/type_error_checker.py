# scripts/checkers/static_checkers/type_error_checker.py
import astroid
import sys
from typing import Optional, Tuple

# 상위 디렉토리의 base_checkers와 utils에서 필요한 모듈 import
from checkers.base_checkers import BaseAstroidChecker
from utils import get_type_astroid, is_compatible_astroid

class StaticTypeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-type-error'
    node_types = (astroid.BinOp,) # 이항 연산 노드를 검사
    MSGS = {'0301': ("TypeError: Incompatible types for '%s' operation: %s and %s (Static)", 'invalid-types-op', '')}

    def check(self, node: astroid.BinOp):
        # --- 디버깅 로그 1: 체커 실행 확인 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        
        try:
            # 왼쪽과 오른쪽 피연산자의 타입을 추론
            left_type = get_type_astroid(node.left)
            right_type = get_type_astroid(node.right)

            # --- 디버깅 로그 2: 추론된 타입 확인 ---
            print(f"  [TypeErrorChecker-DEBUG] Op: '{node.op}', Left: '{node.left.as_string()}' (type: {left_type}), Right: '{node.right.as_string()}' (type: {right_type})", file=sys.stderr)

            # 두 피연산자의 타입을 모두 추론했을 경우에만 호환성 검사
            if left_type and right_type:
                compatible = is_compatible_astroid(left_type, right_type, node.op)
                # --- 디버깅 로그 3: 호환성 검사 결과 확인 ---
                print(f"  [TypeErrorChecker-DEBUG] Compatibility check for ({left_type}, {right_type}, '{node.op}') -> {compatible}", file=sys.stderr)

                if not compatible:
                    # --- 디버깅 로그 4: 오류 탐지 확인 ---
                    print(f"DEBUG: {self.NAME} FOUND an error for '{node.op}'", file=sys.stderr)
                    self.add_message(node, '0301', (node.op, left_type, right_type))
        
        except astroid.InferenceError:
            # 타입 추론 실패는 자주 발생할 수 있으므로 조용히 넘어감
            # print(f"DEBUG: InferenceError in {self.NAME} for {node.as_string()}", file=sys.stderr)
            pass
        except Exception as e:
            # 그 외 예상치 못한 오류는 로그로 남김
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)