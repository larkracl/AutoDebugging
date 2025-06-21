# scripts/checkers/static_checkers/recursion_checker.py
import astroid
import sys

from checkers.base_checkers import BaseAstroidChecker

class StaticRecursionChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'
    NAME = 'static-recursion'
    MSGS = {
        '0801': (
            "Potential recursion: Function '%s' calls itself (Static)",
            'recursive-call',
            ''
        )
    }

    # 이 체커는 Linter에서 함수 단위로 직접 호출됨
    def check_function_recursion(self, func_node: astroid.FunctionDef):
        func_name = func_node.name
        print(f"DEBUG: Running {self.NAME} on function: {func_name}", file=sys.stderr)
        try:
            # 함수 본문 내에서 같은 이름의 함수 호출 찾기
            for call_node in func_node.nodes_of_class(astroid.Call):
                # 호출된 함수가 Name 노드이고, 이름이 현재 함수와 같은지 확인
                if isinstance(call_node.func, astroid.Name) and call_node.func.name == func_name:
                    # 호출이 해당 함수 스코프 내에서 일어나는지 확인하여 외부 변수 사용과 구분
                    if call_node.scope() is func_node:
                        print(f"DEBUG: {self.NAME} FOUND a recursive call in '{func_name}'", file=sys.stderr)
                        self.add_message(call_node.func, '0801', (func_name,))
                        return  # 함수당 한 번만 보고
        except Exception as e:
            print(f"Error checking recursion for {func_name}: {e}", file=sys.stderr)