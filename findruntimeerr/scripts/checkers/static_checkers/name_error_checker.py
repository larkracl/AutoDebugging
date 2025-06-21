# scripts/checkers/static_checkers/name_error_checker.py (The real final version)
import astroid
import builtins
import sys
import traceback

from checkers.base_checkers import BaseAstroidChecker

class StaticNameErrorChecker(BaseAstroidChecker):
    """Astroid를 사용하여 정의되지 않은 이름(NameError)을 탐지하는 체커."""
    MSG_ID_PREFIX = 'E'
    NAME = 'static-name-error'
    node_types = (astroid.Name,)
    MSGS = {'0102': ("NameError: Name '%s' is not defined (Static)", 'undefined-variable', '')}

    def check(self, node: astroid.Name):
        """
        주어진 이름(Name) 노드를 검사합니다.
        이름이 사용되는 컨텍스트에서 정의를 찾을 수 없으면 NameError를 보고합니다.
        """
        # 내장 함수/타입은 초기에 제외
        if node.name in builtins.__dict__:
            return

        try:
            # lookup을 시도하여 정의를 찾는다.
            definitions = node.lookup(node.name)

            # --- 여기가 최종 해결책 ---
            # lookup의 결과는 (스코프 리스트, 할당 노드 리스트) 형태의 튜플이다.
            # 두 번째 원소인 '할당 노드 리스트'가 비어있다면,
            # 이는 astroid가 builtins 같은 곳에서 이름을 찾았다고 착각했지만
            # 실제 정의를 찾지는 못한 경우이다.
            # 이 경우를 NameError로 간주해야 한다.
            if not definitions[1]:
                # NotFoundError를 직접 발생시켜 아래 except 블록에서 처리하게 한다.
                raise astroid.NotFoundError

        except astroid.NotFoundError:
            # 정의를 찾지 못했거나, 찾았지만 유효하지 않은 경우
            print(f"DEBUG: {self.NAME} FOUND a REAL error for '{node.name}' (NotFoundError or invalid definition)", file=sys.stderr)
            self.add_message(node, '0102', (node.name,))
        except Exception as e:
            # lookup 과정에서 다른 예외가 발생한 경우
            print(f"ERROR during lookup for '{node.name}': {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)