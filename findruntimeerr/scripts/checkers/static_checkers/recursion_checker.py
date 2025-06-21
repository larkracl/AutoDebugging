# scripts/checkers/static_checkers/recursion_checker.py
import astroid
import sys

from checkers.base_checkers import BaseAstroidChecker

class StaticRecursionChecker(BaseAstroidChecker):
    """
    함수 내에서 자기 자신을 직접 호출하는 재귀 호출을 탐지하는 체커.
    이 체커는 Linter에서 함수 단위로 직접 호출됩니다.
    """
    MSG_ID_PREFIX = 'W'  # 경고(Warning) 수준
    NAME = 'static-recursion'
    # 이 체커는 AST 전체를 순회하지 않으므로 node_types가 필요 없습니다.
    # node_types = ()
    MSGS = {
        '0801': (
            "Potential recursion: Function '%s' calls itself (Static)",
            'recursive-call',
            'A function that calls itself directly may lead to a RecursionError if there is no proper base case to terminate the recursion.'
        )
    }

    def check_function_recursion(self, func_node: astroid.FunctionDef):
        """
        주어진 함수(FunctionDef) 노드 내에서 재귀 호출이 있는지 검사합니다.
        """
        func_name = func_node.name
        
        try:
            # 함수 본문(body) 내에서 발생하는 모든 호출(Call) 노드를 찾습니다.
            for call_node in func_node.nodes_of_class(astroid.Call):
                # 호출된 함수가 Name 노드이고, 그 이름이 현재 함수의 이름과 같은지 확인합니다.
                if isinstance(call_node.func, astroid.Name) and call_node.func.name == func_name:
                    
                    # 더 정확한 검증: 호출이 일어난 스코프가 현재 함수 스코프와 같은지 확인합니다.
                    # 이를 통해 내부 함수가 외부의 동명 함수를 호출하는 경우 등을 제외할 수 있습니다.
                    if call_node.scope() is func_node:
                        # 재귀 호출을 발견했으므로, 메시지를 추가하고 검사를 종료합니다.
                        # (함수당 한 번만 보고하면 충분합니다)
                        self.add_message(call_node.func, '0801', (func_name,))
                        return
        except Exception:
            # 체커 실행 중 발생하는 모든 예외는 무시합니다.
            pass